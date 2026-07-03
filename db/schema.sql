-- =====================================================================
--  Sistema de Síntesis Automática de Reportes y Briefings Operacionales
--  CIITEC / Ejército de Chile
--  Modelo de datos PostgreSQL (+ pgvector)
--
--  Cada bloque indica el/los requerimiento(s) que respalda.
--  Convención: todo es append-only donde el requerimiento exige
--  trazabilidad e historia (RF-006, RF-007, RF-009, RNF-003).
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid(), digest() para hash chain
CREATE EXTENSION IF NOT EXISTS vector;     -- pgvector: detección de duplicados (RF-005)

-- ---------------------------------------------------------------------
--  Tipos enumerados
-- ---------------------------------------------------------------------
CREATE TYPE nivel_clasificacion AS ENUM ('PUBLICO', 'RESERVADO', 'SECRETO');     -- RNF-002
CREATE TYPE tipo_fuente         AS ENUM ('PDF', 'WORD', 'EXCEL', 'CORREO', 'BITACORA', 'OTRO'); -- RF-001
CREATE TYPE estado_procesamiento AS ENUM ('PENDIENTE', 'PROCESANDO', 'PROCESADO', 'ERROR');
CREATE TYPE estado_hecho        AS ENUM ('ABIERTO', 'EN_CURSO', 'CERRADO');      -- RF-003
CREATE TYPE estado_briefing     AS ENUM ('BORRADOR', 'APROBADO');               -- RF-007
CREATE TYPE tipo_inconsistencia AS ENUM ('DUPLICADO', 'CONTRADICCION', 'DESACTUALIZADO', 'INCOMPLETO'); -- RF-005
CREATE TYPE formato_export      AS ENUM ('PDF', 'WORD', 'TEXTO');               -- RF-008
CREATE TYPE accion_audit        AS ENUM ('LOGIN', 'INGESTA', 'GENERACION', 'EDICION', 'APROBACION',
                                         'EXPORTACION', 'CONSULTA_CLASIFICADA', 'RECONSTRUCCION'); -- RNF-003

-- =====================================================================
--  IDENTIDAD Y CONTROL DE ACCESO  (RNF-001, RNF-002)
--  La autenticación es contra LDAP/AD; acá se espeja la identidad y la
--  habilitación de seguridad para resolver RBAC y clasificación.
-- =====================================================================
CREATE TABLE usuarios (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username            TEXT NOT NULL UNIQUE,            -- viene de LDAP/AD
    nombre              TEXT NOT NULL,
    unidad              TEXT,                            -- unidad militar (segmenta RBAC)
    nivel_habilitacion  nivel_clasificacion NOT NULL DEFAULT 'PUBLICO', -- techo de lo que puede ver
    activo              BOOLEAN NOT NULL DEFAULT TRUE,
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE roles (
    id          SMALLINT PRIMARY KEY,
    nombre      TEXT NOT NULL UNIQUE                     -- Oficial de Operaciones, Analista, Asesor, Comandante, Auditor, Administrador, Oficial de Seguridad
);

CREATE TABLE usuario_roles (
    usuario_id  UUID REFERENCES usuarios(id) ON DELETE CASCADE,
    rol_id      SMALLINT REFERENCES roles(id),
    PRIMARY KEY (usuario_id, rol_id)
);

-- =====================================================================
--  FUENTES  (RF-001 ingesta heterogénea, RF-006 trazabilidad)
--  El binario original vive en MinIO; acá solo metadata + puntero.
-- =====================================================================
CREATE TABLE fuentes (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre_archivo      TEXT NOT NULL,
    tipo                tipo_fuente NOT NULL,
    mime                TEXT,
    objeto_minio        TEXT NOT NULL,                   -- key del object store (RF-001)
    hash_sha256         TEXT NOT NULL,                   -- integridad + dedup a nivel archivo
    nivel_clasificacion nivel_clasificacion NOT NULL DEFAULT 'RESERVADO', -- RNF-002
    unidad              TEXT,                            -- unidad propietaria (RBAC por unidad, RNF-001)
    timestamp_fuente    TIMESTAMPTZ,                     -- fecha del CONTENIDO (RF-005 desactualización)
    texto_extraido      TEXT,                            -- texto plano tras el parser (RF-001/002)
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    estado              estado_procesamiento NOT NULL DEFAULT 'PENDIENTE',
    subido_por          UUID REFERENCES usuarios(id),
    subido_en           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_fuentes_timestamp ON fuentes (timestamp_fuente);
CREATE INDEX idx_fuentes_estado    ON fuentes (estado);

-- =====================================================================
--  HECHOS EXTRAÍDOS  (RF-003 extracción, RF-002 normalización,
--                     RF-005 duplicados vía embeddings, RF-006 trazabilidad)
--  Un hecho SIEMPRE apunta a su fuente y al span exacto de origen.
-- =====================================================================
CREATE TABLE hechos (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fuente_id       UUID NOT NULL REFERENCES fuentes(id) ON DELETE CASCADE, -- RF-006
    evento          TEXT NOT NULL,                       -- qué
    ocurrido_en     TIMESTAMPTZ,                         -- cuándo
    ubicacion       TEXT,                                -- dónde
    responsable     TEXT,                                -- quién / unidad
    impacto         TEXT,                                -- personas / medios / servicio
    estado          estado_hecho,                        -- abierto / en curso / cerrado
    texto_origen    TEXT,                                -- cita textual del documento (RF-006)
    ubicacion_origen JSONB,                              -- {pagina, offset, ...} para rastreo fino
    normalizado     JSONB NOT NULL DEFAULT '{}'::jsonb,  -- campos estandarizados (RF-002)
    confianza       REAL,                                -- score del extractor
    embedding       vector(384),                         -- sentence-transformers (RF-005 duplicados)
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_hechos_fuente ON hechos (fuente_id);
-- Índice ANN HNSW para similitud coseno (duplicados, RF-005). Mejor recall que ivfflat
-- y no requiere datos previos ni reentrenar 'lists'.
CREATE INDEX idx_hechos_embedding ON hechos USING hnsw (embedding vector_cosine_ops);

-- =====================================================================
--  BRIEFINGS  (RF-004) + VERSIONADO APPEND-ONLY  (RF-007, RF-009)
--  No se hace UPDATE del contenido: cada cambio es una versión nueva.
--  RF-009 (reconstrucción point-in-time) = versión activa a la hora T.
-- =====================================================================
CREATE TABLE briefings (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    titulo              TEXT NOT NULL,
    periodo_desde       TIMESTAMPTZ,
    periodo_hasta       TIMESTAMPTZ,
    nivel_clasificacion nivel_clasificacion NOT NULL DEFAULT 'RESERVADO',
    unidad              TEXT,                            -- unidad propietaria (RBAC por unidad, RNF-001)
    estado              estado_briefing NOT NULL DEFAULT 'BORRADOR',
    creado_por          UUID REFERENCES usuarios(id),
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE briefing_versiones (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    briefing_id         UUID NOT NULL REFERENCES briefings(id) ON DELETE CASCADE,
    numero_version      INT NOT NULL,                    -- v1, v2, v3...
    -- contenido estructurado del briefing (RF-004):
    -- { resumen_ejecutivo: [...5-10 bullets...], secciones: {situacion, logistica,
    --   personal, incidentes, meteorologia}, tabla_critica: [...], proyeccion_24_72h: ... }
    contenido           JSONB NOT NULL,
    comentario_cambio   TEXT,                            -- qué cambió (RF-007)
    fuentes_agregadas   JSONB NOT NULL DEFAULT '[]'::jsonb,
    generado_por        UUID REFERENCES usuarios(id),
    aprobado_por        UUID REFERENCES usuarios(id),    -- quién aprobó (RF-007)
    aprobado_en         TIMESTAMPTZ,
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now(), -- ancla temporal para RF-009
    UNIQUE (briefing_id, numero_version)
);
CREATE INDEX idx_versiones_briefing_tiempo ON briefing_versiones (briefing_id, creado_en);

-- RF-009: estado del briefing a la hora T  ->
--   SELECT * FROM briefing_versiones
--   WHERE briefing_id = :id AND creado_en <= :T
--   ORDER BY creado_en DESC LIMIT 1;

-- Trazabilidad fina bullet -> hecho (RF-006). Cada bullet del contenido
-- referencia los hechos que lo originaron; hecho -> fuente cierra la cadena.
CREATE TABLE version_bullet_hechos (
    version_id  UUID NOT NULL REFERENCES briefing_versiones(id) ON DELETE CASCADE,
    bullet_key  TEXT NOT NULL,                           -- ruta/índice del bullet dentro de 'contenido'
    hecho_id    UUID NOT NULL REFERENCES hechos(id),
    PRIMARY KEY (version_id, bullet_key, hecho_id)
);

-- =====================================================================
--  INCONSISTENCIAS  (RF-005)
-- =====================================================================
CREATE TABLE inconsistencias (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    briefing_id     UUID REFERENCES briefings(id) ON DELETE CASCADE,
    tipo            tipo_inconsistencia NOT NULL,
    severidad       SMALLINT NOT NULL DEFAULT 1,         -- 1=baja ... 3=alta
    descripcion     TEXT NOT NULL,
    hechos_involucrados JSONB NOT NULL DEFAULT '[]'::jsonb, -- ids de hechos
    resuelto        BOOLEAN NOT NULL DEFAULT FALSE,
    detectado_en    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =====================================================================
--  EXPORTACIONES  (RF-008)
-- =====================================================================
CREATE TABLE exportaciones (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id      UUID NOT NULL REFERENCES briefing_versiones(id),
    formato         formato_export NOT NULL,
    objeto_minio    TEXT NOT NULL,
    nivel_clasificacion nivel_clasificacion NOT NULL,
    generado_por    UUID REFERENCES usuarios(id),
    generado_en     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =====================================================================
--  AUDIT LOG INMUTABLE CON ENCADENAMIENTO DE HASH  (RNF-003)
--  Append-only + tamper-evident: cada fila encadena el hash de la anterior.
--  Retención mínima 5 años (política operacional / purga controlada).
-- =====================================================================
CREATE TABLE audit_log (
    id              BIGSERIAL PRIMARY KEY,
    actor_id        UUID REFERENCES usuarios(id),
    accion          accion_audit NOT NULL,
    entidad_tipo    TEXT,                                -- 'fuente','briefing','version',...
    entidad_id      TEXT,
    detalle         JSONB NOT NULL DEFAULT '{}'::jsonb,
    nivel_afectado  nivel_clasificacion,
    ocurrido_en     TIMESTAMPTZ NOT NULL DEFAULT now(),
    hash_anterior   TEXT,
    hash_actual     TEXT
);
CREATE INDEX idx_audit_tiempo ON audit_log (ocurrido_en);

-- Calcula el hash encadenado al insertar.
CREATE OR REPLACE FUNCTION audit_hash_chain() RETURNS TRIGGER AS $$
DECLARE prev TEXT;
BEGIN
    SELECT hash_actual INTO prev FROM audit_log ORDER BY id DESC LIMIT 1;
    NEW.hash_anterior := prev;
    NEW.hash_actual := encode(
        digest(
            coalesce(prev,'') ||
            coalesce(NEW.actor_id::text,'') ||
            NEW.accion::text ||
            coalesce(NEW.entidad_tipo,'') ||
            coalesce(NEW.entidad_id,'') ||
            NEW.detalle::text ||
            NEW.ocurrido_en::text,
        'sha256'),
    'hex');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_audit_hash
    BEFORE INSERT ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_hash_chain();

-- Bloquea UPDATE y DELETE: el log es inmutable.
CREATE OR REPLACE FUNCTION audit_inmutable() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_log es inmutable: no se permite % ', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_audit_no_update
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_inmutable();
