from datetime import UTC, datetime
from uuid import uuid4

import psycopg2
import pytest

from emip.domain import MetadataObject, ObjectStatus, ObjectType
from emip.repository.metadata_repository import MetadataRepository


def _object() -> MetadataObject:
    now = datetime.now(UTC)
    return MetadataObject(
        object_id=uuid4(),
        object_type=ObjectType.TABLE,
        system_name="EMIP_TEST",
        qualified_name=f"test.{uuid4()}",
        name="test_object",
        display_name="Test Object",
        description="Repository integration test object",
        owner_name="EMIP_TEST",
        status=ObjectStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )


def test_metadata_object_crud_against_greenplum() -> None:
    try:
        repository = MetadataRepository()
        metadata_object = _object()
        if repository.exists_object(metadata_object):
            repository.delete_object(metadata_object)
    except (psycopg2.Error, RuntimeError, ValueError) as exc:
        pytest.skip(f"Greenplum EMIP_OBJECT is unavailable: {exc}")

    created = repository.create_object(metadata_object)
    assert created == metadata_object
    assert repository.exists_object(metadata_object)

    fetched = repository.get_object(metadata_object)
    assert fetched == metadata_object

    updated = MetadataObject(
        object_id=metadata_object.object_id,
        object_type=metadata_object.object_type,
        system_name=metadata_object.system_name,
        qualified_name=metadata_object.qualified_name,
        name="updated_test_object",
        display_name="Updated Test Object",
        description=metadata_object.description,
        owner_name=metadata_object.owner_name,
        status=metadata_object.status,
        created_at=metadata_object.created_at,
        updated_at=datetime.now(UTC),
    )
    assert repository.update_object(updated) == updated
    assert repository.get_object(updated) == updated

    assert repository.delete_object(updated) == updated
    assert not repository.exists_object(updated)
