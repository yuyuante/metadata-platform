/****************************************************************
** EMIP migration: expand SYSTEM_NAME for production source names
** Target: Greenplum 6.x
****************************************************************/

BEGIN;

ALTER TABLE EMIP_OBJECT
    DROP CONSTRAINT IF EXISTS EMIP_UK_OBJECT;

ALTER TABLE EMIP_OBJECT
    ALTER COLUMN SYSTEM_NAME TYPE VARCHAR(255);

ALTER TABLE EMIP_OBJECT
    ADD CONSTRAINT EMIP_UK_OBJECT UNIQUE (SYSTEM_NAME, QUALIFIED_NAME);

COMMIT;
