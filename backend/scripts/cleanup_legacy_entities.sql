-- MANUAL destructive migration. Back up PostgreSQL first and verify the new app.
-- Do not run while any old backend/indexing/export process is still in use.
-- No CASCADE: unexpected dependencies must prevent deletion.
BEGIN;
SET LOCAL lock_timeout = '5s';
DROP TABLE IF EXISTS entity_candidates;
COMMIT;
