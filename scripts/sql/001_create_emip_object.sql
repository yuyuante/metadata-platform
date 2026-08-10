drop TABLE IF EXISTS EMIP_OBJECT;

/****************************************************************
** 安全等級 : 機密
** 程序代碼 : EMIP_OBJECT
** 程序名稱 : EMIP Metadata Object Table
** 設 計 者 :
** 編碼日期 : 2026-08-10
** 說    明 : 建立 EMIP Metadata Object 主資料表、主鍵、唯一約束與查詢索引。
** 資 料 表 : EMIP_OBJECT (R/W)
** 異動日期 :
** 異動人員 :
** 異動說明 : 初次建立。
****************************************************************/

CREATE TABLE IF NOT EXISTS EMIP_OBJECT (
    OBJECT_ID       UUID          NOT NULL,
    OBJECT_TYPE     VARCHAR(50)   NOT NULL,
    SYSTEM_NAME     VARCHAR(50)   NOT NULL,
    QUALIFIED_NAME  VARCHAR(1000) NOT NULL,
    NAME            VARCHAR(255)  NOT NULL,
    DISPLAY_NAME    VARCHAR(255)  NOT NULL,
    DESCRIPTION     TEXT,
    OWNER_NAME      VARCHAR(255),
    STATUS          VARCHAR(30)   NOT NULL,
    CREATED_AT      TIMESTAMP     NOT NULL,
    UPDATED_AT      TIMESTAMP     NOT NULL,
    CONSTRAINT EMIP_PK_OBJECT PRIMARY KEY (OBJECT_ID),
    CONSTRAINT EMIP_UK_OBJECT UNIQUE (SYSTEM_NAME, QUALIFIED_NAME)
)
DISTRIBUTED REPLICATED;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_class AS c
        JOIN pg_namespace AS n
          ON n.oid = c.relnamespace
        WHERE n.nspname = current_schema()
          AND c.relname = 'EMIP_IDX_OBJECT_NAME'
    ) THEN
        CREATE INDEX EMIP_IDX_OBJECT_NAME
            ON EMIP_OBJECT (NAME);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_class AS c
        JOIN pg_namespace AS n
          ON n.oid = c.relnamespace
        WHERE n.nspname = current_schema()
          AND c.relname = 'EMIP_IDX_OBJECT_TYPE'
    ) THEN
        CREATE INDEX EMIP_IDX_OBJECT_TYPE
            ON EMIP_OBJECT (OBJECT_TYPE);
    END IF;
END;
$$;