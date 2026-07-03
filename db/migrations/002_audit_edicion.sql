-- Migración idempotente: acción de auditoría para ediciones manuales de versiones (RF-007).
-- `db/schema.sql` solo corre en la primera inicialización del volumen; para
-- bases ya existentes, aplicar esta migración manualmente:
--   docker compose exec -T db psql -U $DB_USER -d $DB_NAME < db/migrations/002_audit_edicion.sql

ALTER TYPE accion_audit ADD VALUE IF NOT EXISTS 'EDICION' AFTER 'GENERACION';
