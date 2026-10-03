#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <backend-image> <frontend-image>" >&2
    exit 2
fi

BACKEND_IMAGE="$1"
FRONTEND_IMAGE="$2"
APP_DIR="${APP_DIR:-/opt/vietnam-travel-advisor}"
COMPOSE_FILE="$APP_DIR/docker-compose.prod.yml"
APP_ENV="$APP_DIR/.env.production"
DEPLOY_ENV="$APP_DIR/.deploy.env"
NEXT_ENV="$APP_DIR/.deploy.env.next"
PREVIOUS_ENV="$APP_DIR/.deploy.env.previous"
HEALTH_URL="${DEPLOY_HEALTH_URL:-http://127.0.0.1/health}"

cd "$APP_DIR"

if [[ ! -f "$APP_ENV" ]]; then
    echo "Missing $APP_ENV; create it before deploying." >&2
    exit 1
fi

for key in \
    POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD \
    DATABASE_URL REDIS_URL QDRANT_URL JWT_SECRET_KEY \
    GOOGLE_CLIENT_ID GEMINI_API_KEY TAVILY_API_KEY \
    OPENWEATHER_API_KEY GOONG_API_KEY; do
    if ! grep -Eq "^${key}=.+" "$APP_ENV"; then
        echo "Required setting ${key} is missing from .env.production." >&2
        exit 1
    fi
done

if grep -Eq '=replace-with-' "$APP_ENV"; then
    echo ".env.production still contains replace-with placeholders." >&2
    exit 1
fi

printf 'BACKEND_IMAGE=%s\nFRONTEND_IMAGE=%s\n' \
    "$BACKEND_IMAGE" "$FRONTEND_IMAGE" > "$NEXT_ENV"
chmod 600 "$NEXT_ENV"

compose_with() {
    local deployment_env="$1"
    shift
    docker compose \
        --env-file "$deployment_env" \
        --env-file "$APP_ENV" \
        -f "$COMPOSE_FILE" \
        "$@"
}

echo "Pulling immutable deployment images..."
compose_with "$NEXT_ENV" pull

echo "Applying forward database migrations..."
compose_with "$NEXT_ENV" run --rm backend alembic upgrade head

if [[ -f "$DEPLOY_ENV" ]]; then
    cp "$DEPLOY_ENV" "$PREVIOUS_ENV"
fi
mv "$NEXT_ENV" "$DEPLOY_ENV"

echo "Starting production services..."
compose_with "$DEPLOY_ENV" up -d --remove-orphans

healthy=false
for attempt in $(seq 1 20); do
    if curl --fail --silent --show-error --max-time 5 "$HEALTH_URL" >/dev/null; then
        healthy=true
        break
    fi
    echo "Health check attempt ${attempt}/20 failed; retrying..."
    sleep 5
done

if [[ "$healthy" == true ]]; then
    echo "Deployment is healthy."
    compose_with "$DEPLOY_ENV" ps
    exit 0
fi

echo "Deployment health check failed." >&2

if [[ -f "$PREVIOUS_ENV" ]]; then
    echo "Restoring the previous application image tags..." >&2
    cp "$PREVIOUS_ENV" "$DEPLOY_ENV"
    compose_with "$DEPLOY_ENV" up -d --remove-orphans
else
    echo "No previous image metadata exists; stopping application containers." >&2
    compose_with "$DEPLOY_ENV" stop nginx backend || true
fi

echo "Image rollback completed. Database migrations were not downgraded." >&2
exit 1
