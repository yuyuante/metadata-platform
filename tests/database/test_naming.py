from emip.database import DatabaseNaming
from emip.database.tables import OBJECT, OBJECT_VERSION


def test_schema_and_prefix_are_applied() -> None:
    naming = DatabaseNaming(schema="public", table_prefix="EMIP_")

    assert naming.table(OBJECT) == "public.EMIP_OBJECT"
    assert naming.table(OBJECT_VERSION) == "public.EMIP_OBJECT_VERSION"


def test_empty_schema_returns_unqualified_name() -> None:
    naming = DatabaseNaming(schema="", table_prefix="EMIP_")

    assert naming.table(OBJECT) == "EMIP_OBJECT"


def test_different_prefix_is_applied() -> None:
    naming = DatabaseNaming(schema="metadata", table_prefix="APP_")

    assert naming.table(OBJECT) == "metadata.APP_OBJECT"
