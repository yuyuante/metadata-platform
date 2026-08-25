from uuid import uuid4

import pytest

from emip.domain import SourceLocation, SourceType


def test_source_location_rebinds_without_changing_traceability() -> None:
    original_id = uuid4()
    persisted_id = uuid4()
    location = SourceLocation(
        object_id=original_id,
        source_root="D:/sql",
        source_file="customer.sql",
        source_type=SourceType.SQL,
        start_line=4,
        end_line=8,
    )

    rebound = location.for_object(persisted_id)

    assert rebound.object_id == persisted_id
    assert rebound.source_location_id == location.source_location_id
    assert rebound.source_file == location.source_file
    assert rebound.start_line == 4
    assert rebound.end_line == 8


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"source_file": ""}, "source_file must not be empty"),
        ({"start_line": 0}, "start_line must be positive"),
        ({"end_line": 2}, "end_line requires start_line"),
        ({"start_line": 4, "end_line": 3}, "end_line must not precede start_line"),
    ],
)
def test_source_location_validates_ranges(
    kwargs: dict[str, object], message: str
) -> None:
    values: dict[str, object] = {
        "object_id": uuid4(),
        "source_root": "D:/sql",
        "source_file": "customer.sql",
        "source_type": SourceType.SQL,
    }
    values.update(kwargs)

    with pytest.raises(ValueError, match=message):
        SourceLocation(**values)  # type: ignore[arg-type]
