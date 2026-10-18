"""
Turns a paid signup into a running client stack; the signup page then shows
(and downloads) the credentials.

Each client gets its own isolated docker compose project created by
deploy/add-client.sh. Steps are idempotent so a failed signup can be retried:
an already-created stack is just brought up again rather than re-created.
"""

import logging
import os
import re
import secrets
import string
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import select, update

from app.config import settings
from app.db import SessionLocal, Signup, SignupStatus

log = logging.getLogger("billing.provisioner")

# One provisioning run at a time so slug/port allocation can't race
_lock = threading.Lock()

RESERVED_SLUGS = {"billing", "bomify", "api", "web", "db", "redis"}


def _deploy_dir() -> Path:
    return Path(settings.DEPLOY_DIR)


def _env_file(slug: str) -> Path:
    return _deploy_dir() / f".env.{slug}"


def _make_password(length: int = 14) -> str:
    # add-client.sh only accepts letters and digits; drop look-alikes (0/O/o, 1/l/I)
    # since customers type this from an email
    alphabet = "".join(c for c in string.ascii_letters + string.digits if c not in "0Oo1lI")
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _ports_in_env_files() -> set[int]:
    """Ports already claimed by stacks created outside the billing service."""
    ports = set()
    for f in _deploy_dir().glob(".env.*"):
        try:
            for line in f.read_text().splitlines():
                if line.startswith("WEB_PORT="):
                    ports.add(int(line.split("=", 1)[1].strip()))
        except (OSError, ValueError):
            continue
    return ports


def _allocate_slug(db, company_name: str) -> str:
    base = re.sub(r"[^a-z0-9]", "", company_name.lower())[:16] or "client"
    if not base[0].isalpha():
        base = "c" + base[:15]
    taken = set(db.scalars(select(Signup.slug).where(Signup.slug.is_not(None))))
    candidate, n = base, 1
    while candidate in RESERVED_SLUGS or candidate in taken or _env_file(candidate).exists():
        n += 1
        candidate = f"{base}{n}"
    return candidate


def _allocate_port(db) -> int:
    taken = set(db.scalars(select(Signup.port).where(Signup.port.is_not(None))))
    taken |= _ports_in_env_files()
    for port in range(settings.CLIENT_PORT_START, settings.CLIENT_PORT_END + 1):
        if port not in taken:
            return port
    raise RuntimeError("No free client ports left; widen CLIENT_PORT_START/END")


def has_capacity() -> bool:
    """True if one more paid signup could still get a port and fit under MAX_CLIENTS."""
    with SessionLocal() as db:
        used = set(db.scalars(select(Signup.port).where(Signup.port.is_not(None))))
        # Paid but not yet allocated: they will each take a slot
        queued = len(list(db.scalars(
            select(Signup.id).where(
                Signup.port.is_(None),
                Signup.status.in_([SignupStatus.PAID, SignupStatus.PROVISIONING]),
            )
        )))
    used |= _ports_in_env_files()
    in_range = {p for p in used if settings.CLIENT_PORT_START <= p <= settings.CLIENT_PORT_END}
    free_ports = (settings.CLIENT_PORT_END - settings.CLIENT_PORT_START + 1) - len(in_range)
    return len(used) + queued < settings.MAX_CLIENTS and free_ports > queued


def _run(cmd: list[str], env: dict | None = None) -> None:
    result = subprocess.run(
        cmd,
        cwd=_deploy_dir(),
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"{' '.join(cmd[:3])} failed ({result.returncode}): "
            f"{(result.stderr or result.stdout)[-2000:]}"
        )


def create_stack(signup: Signup, password: str) -> None:
    """Create the client's stack, or start it if it was created on a previous attempt."""
    if _env_file(signup.slug).exists():
        _run([
            "docker", "compose", "-p", signup.slug,
            "-f", "docker-compose.prod.yml",
            "--env-file", f".env.{signup.slug}",
            "up", "-d",
        ])
        return
    _run(
        ["bash", "deploy/add-client.sh", signup.slug, str(signup.port), signup.company_name, password],
        env={
            "ADMIN_USERNAME": signup.admin_username,
            "ADMIN_EMAIL": signup.email,
            "ADMIN_FULL_NAME": signup.contact_name,
            "SEED_DEMO_DATA": "false",
        },
    )


def wait_until_healthy(port: int) -> None:
    url = f"http://{settings.HEALTHCHECK_HOST}:{port}/api/health"
    deadline = time.monotonic() + settings.PROVISION_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=5).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(5)
    raise RuntimeError(f"Stack did not become healthy at {url} within timeout")


def _claim(signup_id: int) -> bool:
    """Atomically move PAID -> PROVISIONING so webhook + browser can't double-provision."""
    with SessionLocal.begin() as db:
        result = db.execute(
            update(Signup)
            .where(Signup.id == signup_id, Signup.status == SignupStatus.PAID)
            .values(status=SignupStatus.PROVISIONING, error=None)
        )
        return result.rowcount == 1


def provision(signup_id: int) -> None:
    """Provision a paid signup end to end. Safe to call more than once."""
    if not _claim(signup_id):
        return
    with _lock:
        try:
            with SessionLocal.begin() as db:
                signup = db.get(Signup, signup_id)
                if signup.slug is None:
                    signup.slug = _allocate_slug(db, signup.company_name)
                    signup.port = _allocate_port(db)
                    signup.admin_username = settings.CLIENT_ADMIN_USERNAME
                    signup.pending_password = _make_password()
                    signup.app_url = settings.APP_URL_TEMPLATE.format(
                        host=settings.PUBLIC_HOST, port=signup.port, slug=signup.slug
                    )

            create_stack(signup, signup.pending_password)
            wait_until_healthy(signup.port)

            with SessionLocal.begin() as db:
                s = db.get(Signup, signup_id)
                s.status = SignupStatus.ACTIVE
                s.activated_at = datetime.now(timezone.utc)
            log.info("Provisioned signup %s as %s on port %s", signup_id, signup.slug, signup.port)
        except Exception as exc:  # noqa: BLE001 — record any failure for retry
            log.exception("Provisioning signup %s failed", signup_id)
            with SessionLocal.begin() as db:
                s = db.get(Signup, signup_id)
                s.status = SignupStatus.FAILED
                s.error = str(exc)[-4000:]


def resume_pending() -> None:
    """Provision signups that were paid but not processed (e.g. service restarted)."""
    with SessionLocal.begin() as db:
        # Single process: anything mid-provisioning at startup was interrupted
        db.execute(
            update(Signup)
            .where(Signup.status == SignupStatus.PROVISIONING)
            .values(status=SignupStatus.PAID)
        )
    with SessionLocal() as db:
        ids = list(db.scalars(select(Signup.id).where(Signup.status == SignupStatus.PAID)))
    for signup_id in ids:
        threading.Thread(target=provision, args=(signup_id,), daemon=True).start()
