/****************************************************************
** EMIP migration: create object column metadata
** Target: Greenplum 6.x
****************************************************************/

CREATE TABLE IF NOT EXISTS EMIP_COLUMN (
    COLUMN_ID         UUID         NOT NULL,
    OBJECT_ID         UUID         NOT NULL,
    COLUMN_NAME       VARCHAR(255) NOT NULL,
    ORDINAL_POSITION  INTEGER      NOT NULL,
    DATATYPE          VARCHAR(255),
    NULLABLE          BOOLEAN      NOT NULL,
    DEFAULT_VALUE     TEXT,
    IS_PRIMARY_KEY    BOOLEAN      NOT NULL,
    IS_UNIQUE         BOOLEAN      NOT NULL,
    CONSTRAINT EMIP_PK_COLUMN PRIMARY KEY (COLUMN_ID),
    CONSTRAINT EMIP_UK_COLUMN UNIQUE (OBJECT_ID, COLUMN_NAME)
)
DISTRIBUTED BY (OBJECT_ID);

CREATE INDEX IF NOT EXISTS EMIP_IDX_COLUMN_OBJECT
    ON EMIP_COLUMN (OBJECT_ID);
