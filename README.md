# QuadStack: Manufacturing Operations Management Platform

A full-stack operations platform for manufacturing workflows, with a FastAPI backend, React frontend, PostgreSQL, Redis, and an integrated AI copilot module.

## Quick Start (2 Minutes)
### Option 1: Docker Compose (Recommended)
Run the full stack (PostgreSQL + Redis + API + Web) with hot reload
```bash
docker compose up --build
```
If your Docker setup uses the legacy command:
```bash
docker-compose up --build
``
Services:
- Frontend: http://localhost:5173
- API: http://localhost:8000
- API docs (Swagger): http://localhost:8000/docs
Default seeded admin credentials (development):
- Username: `admin`
- Email: `admin@quadstack.local`
- Password: `admin123`


## Architecture Snapshot

- `apps/api`: FastAPI backend, SQLAlchemy, Alembic migrations, Redis-backed features, JWT auth, seed utilities.
- `apps/web`: React + Vite + TypeScript frontend with Ant Design and Tailwind.
- Root workspace: Turborepo monorepo orchestration (`dev`, `build`, `lint`).

## Available Scripts

### Root
- `npm run dev` → Run all apps (Turborepo)
- `npm run build` → Build all packages
- `npm run lint` → Lint all workspaces

### API (`apps/api`)
- `npm run dev --workspace=api` → Run FastAPI (port 8000, Windows)
- `npm run dev:unix --workspace=api` → Same (Unix)

### Web (`apps/web`)
- `npm run dev --workspace=web` → Start Vite
- `npm run build --workspace=web` → Build + type-check
- `npm run lint --workspace=web` → Run ESLint
- `npm run preview --workspace=web` → Preview build


## Database, Migrations, and Seed
From `apps/api`:
Run migrations:
```bash
alembic upgrade head
```
Create a new migration:
```bash
alembic revision --autogenerate -m "your_migration_name"
```
Run seed manually:
```bash
python -m app.seed
```

## How to Use Testing

The repository includes API integration tests under [pytests/tests](pytests/tests), configured by [pytests/tests/conftest.py](pytests/tests/conftest.py).

What these tests cover:
- Authentication and users
- Parties
- Inventory
- Sales
- Purchases
- Production
- Dispatch
- Settings and health APIs

### 1) Start required services

These tests expect PostgreSQL and Redis to be available.

Using Docker (recommended):

```bash
docker compose up -d db redis
```

Or run local services on:
- PostgreSQL: `localhost:5432`
- Redis: `localhost:6379`

### 2) Prepare API virtual environment

From `apps/api`, install test dependencies into `apps/api/.venv`.

Windows:

```bash
cd apps/api
.venv\Scripts\pip install pytest pytest-asyncio pytest-cov httpx
```

macOS/Linux:

```bash
cd apps/api
.venv/bin/pip install pytest pytest-asyncio pytest-cov httpx
```

### 3) Run tests

From repository root:

Windows:

```bash
apps\api\.venv\Scripts\python.exe -m pytest pytests/tests -v
```

macOS/Linux:

```bash
apps/api/.venv/bin/python -m pytest pytests/tests -v
```

Run a single file:

```bash
apps\api\.venv\Scripts\python.exe -m pytest pytests/tests/test_settings.py -v
```

Run with coverage:

```bash
apps\api\.venv\Scripts\python.exe -m pytest pytests/tests --cov=app --cov-report=term-missing
```

## Environment Variables

Primary environment variables are defined in [.env.example](./.env.example):
- App/client identity and environment mode
- PostgreSQL connection settings
- Redis URL
- JWT settings
- Seeded admin credentials
- Copilot agent configuration (`GOOGLE_API_KEY`, model and timeout settings)

Note: `apps/api/app/core/config.py` reads from `.env` using Pydantic settings.

