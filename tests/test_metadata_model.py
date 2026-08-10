from dataclasses import is_dataclass
from uuid import UUID

from emip.models import MetadataObject, ObjectType, RelationType, ScanStatus


def _metadata_object(name: str) -> MetadataObject:
    return MetadataObject(
        object_type=ObjectType.TABLE,
        system_name="warehouse",
        qualified_name=f"sales.{name}",
        name=name,
        display_name=name.title(),
    )


def test_metadata_object_generates_uuid() -> None:
    first = _metadata_object("customers")
    second = _metadata_object("orders")

    assert isinstance(first.object_id, UUID)
    assert first.object_id != second.object_id


def test_enums_validate_known_values() -> None:
    assert ObjectType("TABLE") is ObjectType.TABLE
    assert RelationType("READS") is RelationType.READS
    assert ScanStatus("SUCCESS") is ScanStatus.SUCCESS


def test_metadata_object_is_a_dataclass() -> None:
    metadata_object = _metadata_object("customers")

    assert is_dataclass(metadata_object)
    assert metadata_object.object_type is ObjectType.TABLE
    assert metadata_object.qualified_name == "sales.customers"
