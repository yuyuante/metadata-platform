CREATE TABLE IF NOT EXISTS EMIP_COLUMN_LINEAGE_UNRESOLVED (
    LINEAGE_ID UUID NOT NULL,
    TARGET_QUALIFIED_NAME TEXT NOT NULL,
    TARGET_COLUMN_NAME VARCHAR(512) NOT NULL,
    SOURCE_OBJECT_ID UUID NULL,
    SOURCE_COLUMN_NAME VARCHAR(512) NULL,
    CLASSIFICATION VARCHAR(32) NOT NULL,
    EXPRESSION TEXT NOT NULL,
    STATEMENT_SQL TEXT NOT NULL,
    SOURCE_TYPE VARCHAR(64) NOT NULL,
    SOURCE_ROOT TEXT NULL,
    SOURCE_FILE TEXT NULL,
    SOURCE_OBJECT TEXT NOT NULL,
    EVIDENCE TEXT NOT NULL,
    UNRESOLVED_REASON VARCHAR(128) NOT NULL,
    CREATED_AT TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (LINEAGE_ID)
)
DISTRIBUTED BY (LINEAGE_ID);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relname = 'emip_idx_column_lineage_unresolved_source'
          AND n.nspname = current_schema()
    ) THEN
        CREATE INDEX emip_idx_column_lineage_unresolved_source
            ON EMIP_COLUMN_LINEAGE_UNRESOLVED (SOURCE_OBJECT_ID);
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relname = 'emip_idx_column_lineage_unresolved_target'
          AND n.nspname = current_schema()
    ) THEN
        CREATE INDEX emip_idx_column_lineage_unresolved_target
            ON EMIP_COLUMN_LINEAGE_UNRESOLVED (TARGET_QUALIFIED_NAME);
    END IF;
END
$$;
