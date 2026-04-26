-- Force RLS policies to apply even for the table owner / superuser role.
-- Without FORCE, the postgres superuser (used by the app) bypasses RLS entirely.
-- After this migration the app MUST inject app.tenant_id on every connection
-- (handled by pgxpool BeforeAcquire in internal/repository/db.go).

ALTER TABLE sessions        FORCE ROW LEVEL SECURITY;
ALTER TABLE messages        FORCE ROW LEVEL SECURITY;
ALTER TABLE entity_mentions FORCE ROW LEVEL SECURITY;
ALTER TABLE memory_records  FORCE ROW LEVEL SECURITY;
