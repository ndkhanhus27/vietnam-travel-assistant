# Corpus entity retirement

## Scope

Retrieval now uses dense BGE-M3 + title/content BM25, weighted RRF, then the
existing BGE reranker. Corpus entity fields are not used, even when present
in an old Qdrant collection. Query-time `plan.entities` and conversation place
tracking are retained. Coverage uses whole-place matches in the document title,
or at least two mentions in chunk content. This is a heuristic, not proof that
every claim is supported; test comparisons and web fallback separately.

`entity_candidates` is no longer mapped or queried by the app. Historical
Alembic migrations are unchanged, so a fresh `upgrade head` can still create
this legacy table. Cleanup below is a separate, explicit SQL migration. Normal
deployments never drop the table, preserving a rollback window.

Corpus exports use format 2 with documents only. Import accepts v1 or v2 but
ignores legacy entity rows. Retain a full PostgreSQL backup if those rows are
needed for rollback; a v2 corpus export is not a full database backup.

## Local verification (PowerShell)

### Completed local evaluation

The full workflow and its judge completed on 17 October 2026 (Vietnam time):
`workflow_no_entity_20261016_233751.json` and
`judge_no_entity_20261016_233751.json`, 110 cases each. The judge source SHA-256
matches the workflow file. Raw hybrid+BGE Recall@5 is 83.08%; workflow degraded
is 36.36%, with one retained Gemini 503 failure. See the
[measured report](../backend/evaluation/reports/report_vi.md). This is a local
measurement, not an EC2 acceptance test or proof of production readiness.
The commands below reproduce a NEW run; they are not required for publishing docs.

Run from `D:\abc\backend`, with local PostgreSQL/Qdrant available. Do not change
chunking, model revisions, source documents, or dataset labels during comparison.
The copy command requires a NEW target; it never deletes the source or overwrites
an existing target. Stop index writers while copying; a count check cannot detect
same-count concurrent content changes. A failed partial target must not be used.

```powershell
..\.venv\Scripts\python.exe -m scripts.copy_entity_free_index --source travel_chunks --target travel_chunks_no_entity_20261016
$env:QDRANT_COLLECTION = "travel_chunks_no_entity_20261016"
$env:PYTHONIOENCODING = "utf-8"
..\.venv\Scripts\python.exe -m evaluation.validate_dataset --qdrant-url http://localhost:6333
..\.venv\Scripts\python.exe -m evaluation.retrieval_benchmark --output evaluation/reports/retrieval_no_entity_20261016.json
```

If the copy/report already exists, inspect it instead of rerunning with that name;
use a new target/report name for a fresh attempt. IDs/vectors stay unchanged, so
gold chunk IDs remain valid. The benchmark does not call Gemini or travel APIs,
but may download local model weights if uncached. Dense should remain equivalent
on a fixed corpus. Hybrid and hybrid+reranker may improve or regress; measure it.

Start the backend from a terminal with `QDRANT_COLLECTION` set to the new name.
BM25 is loaded in memory and needs a backend restart after any index switch.
For persistent local selection, change only `QDRANT_COLLECTION` in `backend/.env`.

Only after reviewing retrieval results, run paid-quota workflows manually:

```powershell
$tag = Get-Date -Format "yyyyMMdd_HHmmss"
$workflow = "evaluation/reports/workflow_no_entity_$tag.json"
$judge = "evaluation/reports/judge_no_entity_$tag.json"
..\.venv\Scripts\python.exe -m evaluation.evaluate --approved-only --delay-seconds 15 --output $workflow
..\.venv\Scripts\python.exe -m evaluation.judge $workflow --output $judge --delay-seconds 5
```

These commands call real providers. A new retrieval benchmark alone does not
establish end-to-end answer quality; do not reuse old judge scores for new answers.

## EC2 transition (Bash, manual)

### Publish the new code

From the repository root, review and split changes before pushing. Do not add
`.env` files, generated JSON/CSV outputs, or the unrelated interview handbook
under `docs/` as part of this release:

```powershell
cd D:\abc
git diff --check
git add backend/app backend/pipeline backend/scripts backend/tests backend/evaluation/evaluate.py
git diff --cached --stat
git commit -m "refactor(rag): retire corpus entities and preserve index transition"
git add frontend/src/api/types.ts frontend/src/pages/AdminPage.tsx frontend/src/styles.css frontend/e2e/app-layout.pw.ts
git commit -m "fix(admin): remove entity metrics and resize knowledge grid"
git add README.md backend/evaluation/README.md backend/evaluation/RUNBOOK.md backend/evaluation/reports/report_vi.md deploy/README.md deploy/ENTITY-RETIREMENT.md
git commit -m "docs(eval): publish entity-free workflow results and rollout steps"
git fetch origin
git log --oneline HEAD..origin/main
git push origin main
```

If the log shows remote-only commits, stop and integrate them before pushing;
do not force-push. Inspect each staged change set before committing. Local raw
reports remain ignored, including the preserved partial CMD output moved to
`backend/evaluation/reports/accidental_cmd_workflow_partial_20261016.json`.

Pushing alone does not guarantee an EC2 update. After CI succeeds, open GitHub
Actions, select **Build and deploy production**, choose **Run workflow** on
`main`, and verify its commit SHA matches your push. This rebuilds both images
and deploys them. Manual deployment does not invoke a new judge. If automatic
`STAGING_EVAL_ENABLED` is true, a main-branch CI run can trigger live staging
evaluation and consume provider quota before automatic deployment; check that
setting before pushing when avoiding paid/live calls.

Do not assume a successful deployment changed Qdrant data or PostgreSQL tables.
Complete the explicit backup, collection switch, and deferred cleanup below.

Use the production deploy runbook to publish/deploy the new images first, keeping
the old table and collection. None of the following is run automatically.
From `/opt/vietnam-travel-advisor`, define a convenience function:

```bash
dc() { docker compose --env-file .deploy.env --env-file .env.production -f docker-compose.prod.yml "$@"; }
umask 077
mkdir -p backups
stamp=$(date -u +%Y%m%dT%H%M%SZ)
dc exec -T postgres sh -lc 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "backups/before_entity_retirement_$stamp.dump"
test -s "backups/before_entity_retirement_$stamp.dump"
```

Check `pg_dump` succeeded and the archive can be listed with `pg_restore -l`;
prefer a restore rehearsal before destructive cleanup. Retain backups privately,
outside Git. Create a Qdrant snapshot and copy it outside its volume:

```bash
dc exec -T backend python -c 'from app.core.config import settings; from qdrant_client import QdrantClient; c=QdrantClient(url=settings.qdrant_url); print(c.create_snapshot(settings.qdrant_collection))'
```

The response gives the snapshot filename. Using that exact filename and current
collection, download `/collections/<collection>/snapshots/<filename>` from the
private Qdrant API through an authenticated administrative channel. Do not expose
port 6333 publicly. Do not proceed without a verified external backup.

Create the new collection without embeddings or LLM calls:

```bash
dc exec -T backend python -m scripts.copy_entity_free_index --source travel_chunks --target travel_chunks_no_entity_20261016
```

If production uses another source name, substitute it explicitly. If documents
are unchanged, no SQL corpus import is necessary. If a corpus update is needed,
transfer a validated v2 bundle and follow the normal import procedure, then build
a NEW index rather than using `--recreate` on the live collection.

Set `QDRANT_COLLECTION=travel_chunks_no_entity_20261016` in `.env.production`, then:

```bash
dc up -d --force-recreate backend
dc ps
```

Check health, sign-in, factual questions, comparisons, missing-place fallback,
and admin knowledge metrics. A real chat smoke test consumes provider quota.
Until cleanup, rollback is possible by restoring both the previous image tag
and previous collection setting, then recreating the backend. Retain old images.

## Deferred destructive SQL migration

Only after acceptance, verified backups, and confirmation that ALL old app/index
processes are stopped, run this explicit SQL migration:

```bash
dc exec -T backend python -c 'from pathlib import Path; print(Path("scripts/cleanup_legacy_entities.sql").read_text())' > /tmp/vta_cleanup_entities.sql
```

Inspect that file and check the export command succeeded. Then:

```bash
dc exec -T postgres sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < /tmp/vta_cleanup_entities.sql
```

The script drops only `entity_candidates`, without CASCADE. After this point,
rolling back code alone is insufficient: old versions need the backed-up table
and original collection. Keep the old collection until the rollback window ends.
Do not delete PostgreSQL/Qdrant Docker volumes.
