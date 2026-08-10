from dataclasses import is_dataclass
from uuid import UUID

from emip.models import MetadataObject, ObjectType, RelationType, ScanStatus


def test_metadata_object_generates_uuid() -> None:
    first = MetadataObject(name="customers")
    second = MetadataObject(name="orders")

    assert isinstance(first.object_id, UUID)
    assert first.object_id != second.object_id


def test_enums_validate_known_values() -> None:
    assert ObjectType("TABLE") is ObjectType.TABLE
    assert RelationType("READS") is RelationType.READS
    assert ScanStatus("SUCCESS") is ScanStatus.SUCCESS


def test_metadata_object_is_a_dataclass() -> None:
    metadata_object = MetadataObject(
        object_type=ObjectType.TABLE,
        name="customers",
        qualified_name="sales.customers",
    )

    assert is_dataclass(metadata_object)
    assert metadata_object.object_type is ObjectType.TABLE
    assert metadata_object.qualified_name == "sales.customers"
