# Production deployment runbook

This deployment runs one public Nginx container and four private services:

```text
Internet -> nginx:80 -> /api -> backend:8000
                              -> postgres:5432
                              -> redis:6379
                              -> qdrant:6333
```

Only Nginx publishes a host port. The backend has one Uvicorn worker because
each worker would allocate its own BGE-M3 and CrossEncoder models.

## 1. Prerequisites

- Docker Engine with the Docker Compose plugin
- An x86_64 Ubuntu LTS EC2 instance
- Enough measured RAM for the backend models and data services
- A persistent Elastic IP before DNS is configured

Do not select a small instance based on guesswork. Start production-like
Compose, exercise one RAG request so both models load, then record:

```bash
docker stats --no-stream
docker compose --env-file .deploy.env --env-file .env.production \
  -f docker-compose.prod.yml ps
```

Record idle and post-RAG memory before choosing the EC2 size. The repository
does not claim that a micro instance is sufficient.

## 2. Local production-like validation

From the repository root:

```bash
cp deploy/.env.production.example .env.production
# Replace every placeholder and add provider keys.
docker compose --env-file .env.production -f docker-compose.prod.yml config
docker compose --env-file .env.production -f docker-compose.prod.yml build
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm backend alembic upgrade head
docker compose --env-file .env.production -f docker-compose.prod.yml up -d
curl --fail http://127.0.0.1/health
```

Open `http://127.0.0.1`. Validate local login, Google login, conversation
history, normal chat, and streaming chat. Restart without deleting volumes:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml restart
```

Confirm PostgreSQL conversations and the Qdrant collection still exist. Do
not use `down -v` unless permanent deletion is intended.

The app never indexes Qdrant during startup. Run the existing indexing command
only as an explicit data operation after checking its collection replacement
behavior:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm backend \
  python -m pipeline.rag.index_documents
```

## 3. Required production environment

Create `/opt/vietnam-travel-advisor/.env.production` from the example and set
permissions to `600`. Required application values include:

- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DATABASE_URL`
- `REDIS_URL`, `QDRANT_URL`, `QDRANT_COLLECTION`
- `JWT_SECRET_KEY`, `GOOGLE_CLIENT_ID`
- `GEMINI_API_KEY`, `TAVILY_API_KEY`
- `OPENWEATHER_API_KEY`, `GOONG_API_KEY`

The Compose-internal URLs must use `postgres`, `redis`, and `qdrant`, not
`localhost`. For same-origin production traffic, `CORS_ORIGINS` may be empty.
Never store the production file in Git or print it in CI logs.
URL-encode reserved characters in `POSTGRES_PASSWORD` when placing that value
inside `DATABASE_URL`.

`GOOGLE_CLIENT_ID` is public configuration, not a client secret. Set the same
value as the GitHub repository variable `GOOGLE_CLIENT_ID`; Vite embeds that
public ID in the frontend image at build time. Never put a Google client
secret in frontend configuration.

## 4. EC2 initial setup

Install Docker Engine and the Compose plugin from Docker's official Ubuntu
repository:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

source /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${UBUNTU_CODENAME:-$VERSION_CODENAME} stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
docker --version
docker compose version
```

Create a non-root deploy user and deployment directory:

```bash
sudo adduser --disabled-password --gecos "" deploy
sudo usermod -aG docker deploy
sudo install -d -o deploy -g deploy -m 750 /opt/vietnam-travel-advisor
```

Log out and back in after adding the Docker group. Put the deploy user's SSH
public key in `~deploy/.ssh/authorized_keys`; disable password authentication
after confirming key login. The server does not need Python, Node, or a Git
checkout.

## 5. AWS Security Group

- TCP 22: only trusted developer/admin IPs or a controlled bastion
- TCP 80: public
- TCP 443: public after TLS is configured
- Never expose 5432, 6379, 6333, 6334, or 8000 publicly

## 6. GitHub configuration

Create the GitHub Environment `production`, protect it as desired, and add:

- Environment secrets: `EC2_HOST`, `EC2_USER`, `EC2_SSH_KEY`,
  `EC2_KNOWN_HOSTS`
- Repository variable: `GOOGLE_CLIENT_ID`

Generate `EC2_KNOWN_HOSTS` from a trusted network and verify the fingerprint
out of band. Do not replace it with `StrictHostKeyChecking=no`.

CI runs on pushes and pull requests. After successful CI on `main`, the deploy
workflow builds two GHCR images tagged `sha-<full-commit-sha>`, uploads only
Compose and the deploy script, migrates with Alembic, starts services, and
checks `/health`. Production concurrency prevents overlapping deploys.

## 7. Migrations and rollback

The deploy order is:

```text
pull images -> alembic upgrade head -> compose up -d -> bounded health check
```

On failed health checks, `deploy.sh` restores `.deploy.env.previous` and
restarts the previous application images. It never runs `alembic downgrade`.
Migrations must therefore remain backward compatible with the previous app
version. A failed migration stops the deployment before image activation.

Manual image rollback:

```bash
cd /opt/vietnam-travel-advisor
cp .deploy.env.previous .deploy.env
docker compose --env-file .deploy.env --env-file .env.production \
  -f docker-compose.prod.yml up -d --remove-orphans
curl --fail http://127.0.0.1/health
```

## 8. Operations

```bash
cd /opt/vietnam-travel-advisor
docker compose --env-file .deploy.env --env-file .env.production \
  -f docker-compose.prod.yml ps
docker compose --env-file .deploy.env --env-file .env.production \
  -f docker-compose.prod.yml logs --tail=200 backend nginx
docker compose --env-file .deploy.env --env-file .env.production \
  -f docker-compose.prod.yml restart backend nginx
```

Docker logs rotate at 10 MB with three files. Application logs go to standard
output/error and must never contain passwords, tokens, credentials, or keys.

Back up PostgreSQL with tested `pg_dump`/restore procedures. Create and export
Qdrant snapshots separately; the named volumes protect against container
replacement but are not off-instance backups. Redis is cache/rate-limit state,
not the system of record.

## 9. Domain, HTTPS, and Google OAuth

Allocate an Elastic IP, point the real domain's DNS A record to it, and only
then add TLS. Use Certbot or another certificate manager, mount the resulting
certificate read-only into Nginx, listen on 443, and redirect port 80 to HTTPS.
Do not request a certificate for a placeholder hostname.

After HTTPS works, add `https://<real-domain>` to the Google OAuth Web Client's
authorized JavaScript origins and rebuild the frontend image. Set backend
`GOOGLE_CLIENT_ID` to the same Web Client ID. Same-origin `/api` routing avoids
wildcard production CORS.

Official references:

- Docker Engine on Ubuntu: https://docs.docker.com/engine/install/ubuntu/
- Docker Compose plugin: https://docs.docker.com/compose/install/linux/
- GitHub environments: https://docs.github.com/actions/deployment/targeting-different-environments
- Qdrant health and readiness: https://qdrant.tech/documentation/ops-monitoring/monitoring/
