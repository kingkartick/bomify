#!/usr/bin/env bash
# Start an isolated stack (own database, secrets, admin login) for one client.
#
# Usage: bash deploy/add-client.sh <slug> <web-port> ["Display Name"] [admin-password]
# Example: bash deploy/add-client.sh acme 8080 "Acme Corp"
# New clients start empty (no demo data). For a demo client: SEED_DEMO_DATA=true bash deploy/add-client.sh ...
#
# The first client (.env.prod, port 80) is left untouched. Images are built once
# (see docker-compose.prod.yml), so this takes seconds. Remember to open <web-port>
# in the EC2 security group.
set -euo pipefail
cd "$(dirname "$0")/.."

SLUG="${1:?usage: add-client.sh <slug> <web-port> [display-name] [admin-password]}"
PORT="${2:?usage: add-client.sh <slug> <web-port> [display-name] [admin-password]}"
NAME="${3:-$SLUG}"
ADMIN_PW="${4:-$(openssl rand -hex 6)}"
ENV_FILE=".env.$SLUG"

[[ "$SLUG" =~ ^[a-z][a-z0-9]*$ ]] || { echo "slug must be lowercase letters/digits, e.g. acme"; exit 1; }
[[ "$PORT" =~ ^[0-9]+$ ]] || { echo "web-port must be a number, e.g. 8080"; exit 1; }
[[ "$ADMIN_PW" =~ ^[A-Za-z0-9]+$ ]] || { echo "admin password: letters and digits only"; exit 1; }
[ ! -e "$ENV_FILE" ] || { echo "$ENV_FILE already exists - client already created"; exit 1; }

# Images must already exist from the first deploy
docker image inspect bomify-api bomify-web >/dev/null 2>&1 || {
  echo "Images missing. Run once: docker compose -f docker-compose.prod.yml --env-file .env.prod build"
  exit 1
}

cat > "$ENV_FILE" <<EOF
CLIENT_NAME=$NAME
WEB_PORT=$PORT
SECRET_KEY=$(openssl rand -hex 24)
JWT_SECRET_KEY=$(openssl rand -hex 24)
POSTGRES_USER=quadstack
POSTGRES_PASSWORD=$(openssl rand -hex 24)
POSTGRES_DB=quadstack
COPILOT_DB_PASSWORD=$(openssl rand -hex 24)
ADMIN_USERNAME=admin
ADMIN_PASSWORD=$ADMIN_PW
ADMIN_EMAIL=admin@$SLUG.local
ADMIN_FULL_NAME=System Administrator
SEED_DEMO_DATA=${SEED_DEMO_DATA:-false}
GROQ_API_KEY=
EOF
chmod 600 "$ENV_FILE"

docker compose -p "$SLUG" -f docker-compose.prod.yml --env-file "$ENV_FILE" up -d

echo
echo "Client '$NAME' is starting (project: $SLUG)."
echo "  URL:      http://<server-ip>:$PORT"
echo "  Login:    admin / $ADMIN_PW"
echo "  Env file: $ENV_FILE   (keep private)"
echo "  Open TCP $PORT in the EC2 security group."
echo "  Status:   docker compose -p $SLUG -f docker-compose.prod.yml --env-file $ENV_FILE ps"
