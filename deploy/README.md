# Production deployment runbook

This deployment runs one public Caddy container and five private services:

```text
Internet -> caddy:80/443 -> nginx:80 -> /api -> backend:8000
                                           -> postgres:5432
                                           -> redis:6379
                                           -> qdrant:6333
```

Only Caddy publishes host ports. It provisions and renews HTTPS certificates
for `APP_DOMAIN`; Nginx and all data services remain private. The backend has
one Uvicorn worker because
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

The app never imports corpus data or indexes Qdrant during startup. PostgreSQL
is the durable corpus source of truth; Qdrant is a derived index. On a fresh
database, import a validated corpus bundle after Alembic and before indexing:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml cp \
  corpus.corpus.json.gz backend:/home/app/corpus.corpus.json.gz
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T backend \
  python -m scripts.corpus_transfer import \
  --input /home/app/corpus.corpus.json.gz
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T backend \
  rm -f /home/app/corpus.corpus.json.gz
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm backend \
  python -m pipeline.rag.index_documents --recreate
```

The bundle contains only `documents` and `entity_candidates`, preserves their
UUIDs, and imports idempotently. Transfer it to the server through a protected
administrative channel; never commit it. Do not use `host.docker.internal` or
a developer database for production reindexing.

## 3. Required production environment

Create `/opt/vietnam-travel-advisor/.env.production` from the example and set
permissions to `600`. Required application values include:

- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DATABASE_URL`
- `REDIS_URL`, `QDRANT_URL`, `QDRANT_COLLECTION`
- `JWT_SECRET_KEY`, `GOOGLE_CLIENT_ID`
- `GEMINI_API_KEY`, `TAVILY_API_KEY`
- `OPENWEATHER_API_KEY`, `GOONG_API_KEY`
- `APP_DOMAIN`, `ACME_EMAIL`

The Compose-internal URLs must use `postgres`, `redis`, and `qdrant`, not
`localhost`. For same-origin production traffic, `CORS_ORIGINS` may be empty.
Never store the production file in Git or print it in CI logs.
URL-encode reserved characters in `POSTGRES_PASSWORD` when placing that value
inside `DATABASE_URL`.

`GOOGLE_CLIENT_ID` is public configuration, not a client secret. Set the same
value as the GitHub `production` environment variable `GOOGLE_CLIENT_ID`;
Vite embeds that public ID in the frontend image at build time. Never put a
Google client secret in frontend configuration.

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
- TCP 443: public
- Never expose 5432, 6379, 6333, 6334, or 8000 publicly

## 6. GitHub configuration

Create the GitHub Environment `production`, protect it as desired, and add:

- Environment secrets: `EC2_HOST`, `EC2_USER`, `EC2_SSH_KEY`,
  `EC2_KNOWN_HOSTS`
- Environment variable: `GOOGLE_CLIENT_ID`
- Repository variable: `PRODUCTION_DEPLOY_ENABLED`

The frontend build job is attached to the `production` environment and fails
before building when `GOOGLE_CLIENT_ID` is empty or malformed. The validation
prints only the variable name, never its value.

Keep `PRODUCTION_DEPLOY_ENABLED` unset or set to `false` until the EC2 host,
production secrets, and `/opt/vietnam-travel-advisor/.env.production` are
ready. Set it to `true` to enable automatic deployment after successful CI on
`main`. Manual `workflow_dispatch` remains available for deliberate releases.

Generate `EC2_KNOWN_HOSTS` from a trusted network and verify the fingerprint
out of band. Do not replace it with `StrictHostKeyChecking=no`.

CI runs on pushes and pull requests. When `PRODUCTION_DEPLOY_ENABLED=true`, a
successful CI run on `main` starts the deploy workflow. It builds two GHCR
images tagged `sha-<full-commit-sha>`, uploads only
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

## 8. Corpus backup and recovery

Create a corpus-only PostgreSQL backup from the running production backend:

```bash
docker compose --env-file .deploy.env --env-file .env.production \
  -f docker-compose.prod.yml exec -T backend \
  python -m scripts.corpus_transfer export \
  --output /home/app/corpus.corpus.json.gz
docker compose --env-file .deploy.env --env-file .env.production \
  -f docker-compose.prod.yml cp \
  backend:/home/app/corpus.corpus.json.gz ./corpus.corpus.json.gz
docker compose --env-file .deploy.env --env-file .env.production \
  -f docker-compose.prod.yml exec -T backend \
  rm -f /home/app/corpus.corpus.json.gz
```

Store that file encrypted and off-instance. To recover, run Alembic, copy the
bundle into the backend container, run the import command from section 2, then
rebuild `travel_chunks` explicitly with `index_documents --recreate`. Verify
the collection count and a real RAG query. A Qdrant snapshot may shorten
recovery, but it never replaces the PostgreSQL corpus backup.

On a fresh Linux server, initialize data services before the public app:

```bash
docker compose --env-file .deploy.env --env-file .env.production \
  -f docker-compose.prod.yml up -d postgres redis qdrant
docker compose --env-file .deploy.env --env-file .env.production \
  -f docker-compose.prod.yml run --rm backend alembic upgrade head
docker compose --env-file .deploy.env --env-file .env.production \
  -f docker-compose.prod.yml run --rm --no-deps \
  --volume "$PWD/corpus.corpus.json.gz:/tmp/corpus.corpus.json.gz:ro" \
  backend python -m scripts.corpus_transfer import \
  --input /tmp/corpus.corpus.json.gz
docker compose --env-file .deploy.env --env-file .env.production \
  -f docker-compose.prod.yml run --rm --no-deps backend \
  python -m pipeline.rag.index_documents --recreate
docker compose --env-file .deploy.env --env-file .env.production \
  -f docker-compose.prod.yml up -d --remove-orphans
```

Transfer the corpus bundle separately over an authenticated administrative
channel. For example, from the machine holding the encrypted backup:

```bash
scp corpus.corpus.json.gz \
  <deploy-user>@<ec2-host>:/opt/vietnam-travel-advisor/corpus.corpus.json.gz
```

On EC2, restrict the file before importing it and remove it after a successful
bootstrap:

```bash
cd /opt/vietnam-travel-advisor
chmod 600 corpus.corpus.json.gz
# Run the import and index commands above, then validate the counts below.
rm -f corpus.corpus.json.gz
```

Validate the known production baseline without exposing connection strings:

```bash
docker compose --env-file .deploy.env --env-file .env.production \
  -f docker-compose.prod.yml exec -T postgres sh -lc \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc \
  "SELECT '\''documents='\'' || count(*) FROM documents
   UNION ALL
   SELECT '\''entity_candidates='\'' || count(*) FROM entity_candidates;"'

docker compose --env-file .deploy.env --env-file .env.production \
  -f docker-compose.prod.yml exec -T backend python -c \
  'from app.core.config import settings; from qdrant_client import QdrantClient; c=QdrantClient(url=settings.qdrant_url); i=c.get_collection(settings.qdrant_collection); v=i.config.params.vectors; print(f"collection={settings.qdrant_collection} points={i.points_count} vector_size={v.size} distance={v.distance}")'
```

Expected output is `documents=84`, `entity_candidates=1843`, and
`collection=travel_chunks points=287 vector_size=1024 distance=Cosine`. A
mismatch is a failed bootstrap, not a reason to make normal deploys destructive.

Warm both RAG models and exercise real retrieval from inside the EC2 backend:

```bash
docker compose --env-file .deploy.env --env-file .env.production \
  -f docker-compose.prod.yml exec -T backend \
  python -m pipeline.rag.ask "Ga Đà Lạt có gì đặc biệt?"
docker stats --no-stream
```

The lifecycle is:

```text
start PostgreSQL/Redis/Qdrant -> Alembic upgrade -> import corpus bundle
-> explicit index_documents --recreate -> verify travel_chunks -> start/verify app
```

The normal backend startup remains fast and non-destructive: it does not
import corpus data, recreate Qdrant, or calculate embeddings.

## 9. Operations

```bash
cd /opt/vietnam-travel-advisor
docker compose --env-file .deploy.env --env-file .env.production \
  -f docker-compose.prod.yml ps
docker compose --env-file .deploy.env --env-file .env.production \
  -f docker-compose.prod.yml logs --tail=200 backend nginx
docker compose --env-file .deploy.env --env-file .env.production \
  -f docker-compose.prod.yml logs --since=15m backend
docker compose --env-file .deploy.env --env-file .env.production \
  -f docker-compose.prod.yml logs --since=15m nginx
docker compose --env-file .deploy.env --env-file .env.production \
  -f docker-compose.prod.yml restart backend nginx
docker stats --no-stream
```

Docker logs rotate at 10 MB with three files. Application logs go to standard
output/error and must never contain passwords, tokens, credentials, or keys.

Back up PostgreSQL with tested `pg_dump`/restore procedures. Create and export
Qdrant snapshots separately; the named volumes protect against container
replacement but are not off-instance backups. Redis is cache/rate-limit state,
not the system of record.

## 10. Domain, HTTPS, and Google OAuth

Allocate an Elastic IP and point `APP_DOMAIN` to it before deployment. Caddy
then obtains a public certificate automatically, redirects domain traffic from
HTTP to HTTPS, and stores certificate state in the persistent `caddy_data`
volume. Do not deploy with a placeholder hostname.

After HTTPS works, add `https://<real-domain>` to the Google OAuth Web Client's
authorized JavaScript origins. Set backend `GOOGLE_CLIENT_ID` to the same Web
Client ID. Same-origin `/api` routing avoids wildcard production CORS.

Google does not allow a public raw IP as a JavaScript origin and permits plain
HTTP only for localhost development. Therefore Google Sign-In is intentionally
unavailable at `http://<public-ip>`; do not try to bypass this with an HTTP
redirect or disabled token verification.

Official references:

- Docker Engine on Ubuntu: https://docs.docker.com/engine/install/ubuntu/
- Docker Compose plugin: https://docs.docker.com/compose/install/linux/
- GitHub environments: https://docs.github.com/actions/deployment/targeting-different-environments
- Google web client origins: https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid
- Qdrant health and readiness: https://qdrant.tech/documentation/ops-monitoring/monitoring/
