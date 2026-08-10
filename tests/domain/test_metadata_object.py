from dataclasses import is_dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from emip.domain.metadata_object import MetadataObject, ObjectStatus, ObjectType


def _build_object(**overrides: object) -> MetadataObject:
    values: dict[str, object] = {
        "object_type": ObjectType.TABLE,
        "system_name": "warehouse",
        "qualified_name": "sales.customer",
        "name": "customer",
        "status": ObjectStatus.ACTIVE,
    }
    values.update(overrides)
    return MetadataObject(**values)


def test_uuid_is_generated_automatically() -> None:
    metadata_object = _build_object()

    assert isinstance(metadata_object.object_id, UUID)


def test_timestamps_are_generated_automatically() -> None:
    metadata_object = _build_object()

    assert isinstance(metadata_object.created_at, datetime)
    assert isinstance(metadata_object.updated_at, datetime)
    assert metadata_object.created_at.tzinfo is UTC
    assert metadata_object.updated_at.tzinfo is UTC


def test_enum_values_are_exact() -> None:
    assert [member.value for member in ObjectType] == [
        "TABLE",
        "VIEW",
        "FUNCTION",
        "PROCEDURE",
        "TRIGGER",
        "WORKFLOW",
        "SESSION",
        "MAPPING",
        "FILE",
        "DIRECTORY",
    ]
    assert [member.value for member in ObjectStatus] == [
        "ACTIVE",
        "DEPRECATED",
        "DELETED",
        "UNKNOWN",
    ]


def test_metadata_object_is_a_dataclass() -> None:
    metadata_object = _build_object(description="Customer master data")

    assert is_dataclass(metadata_object)
    assert metadata_object.object_type is ObjectType.TABLE
    assert metadata_object.status is ObjectStatus.ACTIVE


def test_display_name_defaults_to_name() -> None:
    metadata_object = _build_object()

    assert metadata_object.display_name == "customer"


def test_create_generates_identity_timestamps_and_defaults() -> None:
    metadata_object = MetadataObject.create(
        object_type=ObjectType.VIEW,
        system_name="warehouse",
        qualified_name="sales.customer_view",
        name="customer_view",
    )

    assert isinstance(metadata_object.object_id, UUID)
    assert metadata_object.display_name == "customer_view"
    assert metadata_object.status is ObjectStatus.ACTIVE
    assert metadata_object.created_at.tzinfo is UTC
    assert metadata_object.updated_at.tzinfo is UTC


@pytest.mark.parametrize("field_name", ["system_name", "qualified_name", "name"])
def test_empty_required_name_raises_value_error(field_name: str) -> None:
    with pytest.raises(ValueError):
        _build_object(**{field_name: ""})


def test_equal_objects_compare_by_dataclass_fields() -> None:
    object_id = uuid4()
    created_at = datetime.now(UTC)
    updated_at = datetime.now(UTC)
    first = _build_object(
        object_id=object_id,
        created_at=created_at,
        updated_at=updated_at,
    )
    second = _build_object(
        object_id=object_id,
        created_at=created_at,
        updated_at=updated_at,
    )

    assert first == second
