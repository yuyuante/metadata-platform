from pathlib import Path


def test_emip_column_primary_key_contains_greenplum_distribution_key() -> None:
    migration = (
        Path(__file__).parents[2] / "scripts" / "sql" / "003_create_emip_column.sql"
    ).read_text(encoding="utf-8")

    assert "PRIMARY KEY (OBJECT_ID, COLUMN_ID)" in migration
    assert "DISTRIBUTED BY (OBJECT_ID)" in migration
    assert "CREATE INDEX IF NOT EXISTS" not in migration
    assert "c.relname = 'emip_idx_column_object'" in migration
