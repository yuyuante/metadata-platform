import json
import shutil
import subprocess
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest

from emip.domain import (
    MetadataObject,
    ObjectType,
    Relation,
    RelationType,
    SourceLocation,
    SourceType,
)
from emip.web import StaticWebExporter


class CountingRepository:
    def __init__(
        self, objects: list[MetadataObject], relations: list[Relation]
    ) -> None:
        self.objects = objects
        self.relations = relations
        self.object_reads = 0
        self.relation_reads = 0

    def find_objects(self) -> list[MetadataObject]:
        self.object_reads += 1
        return list(self.objects)

    def find_relations(self) -> list[Relation]:
        self.relation_reads += 1
        return list(self.relations)


def _object(
    object_id: str,
    kind: ObjectType,
    qualified_name: str,
    *,
    provider: str = "TEST",
    source_locations: tuple[SourceLocation, ...] = (),
) -> MetadataObject:
    return MetadataObject(
        object_id=UUID(object_id),
        object_type=kind,
        system_name=provider,
        qualified_name=qualified_name,
        name=qualified_name.rsplit("::", 1)[-1].rsplit(".", 1)[-1],
        source_locations=source_locations,
    )


def _read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return cast(dict[str, object], payload)


def _search_items(output: Path) -> list[dict[str, object]]:
    manifest = _read_json(output / "data" / "index.json")
    shards = manifest["shards"]
    assert isinstance(shards, dict)
    by_id: dict[str, dict[str, object]] = {}
    shard_paths: set[str] = set()
    for shard in shards.values():
        assert isinstance(shard, dict)
        relative_path = shard["path"]
        assert isinstance(relative_path, str)
        shard_paths.add(relative_path)
    for relative_path in sorted(shard_paths):
        payload = _read_json(output / relative_path)
        items = payload["objects"]
        assert isinstance(items, list)
        for item in items:
            assert isinstance(item, dict)
            object_id = item["id"]
            assert isinstance(object_id, str)
            by_id[object_id] = item
    return sorted(
        by_id.values(),
        key=lambda item: (str(item["qualified_name"]).casefold(), item["id"]),
    )


def test_export_is_partitioned_deterministic_and_reads_repository_once(
    tmp_path: Path,
) -> None:
    table_id = "00000000-0000-0000-0000-000000000001"
    source_id = "00000000-0000-0000-0000-000000000002"
    workflow_id = "00000000-0000-0000-0000-000000000003"
    table = _object(table_id, ObjectType.TABLE, "dbo.STKOUT", provider="SQLSERVER")
    source = _object(
        source_id,
        ObjectType.SOURCE_DEFINITION,
        "AI7101B::wf_AI7101B::sc_STKOUT",
        provider="INFORMATICA",
    )
    workflow = _object(
        workflow_id,
        ObjectType.WORKFLOW,
        "AI7101B::wf_AI7101B",
        provider="INFORMATICA",
    )
    repository = CountingRepository(
        [workflow, source, table],
        [
            Relation(
                source_object_id=source.object_id,
                target_object_id=table.object_id,
                relation_type=RelationType.READS,
            ),
            Relation(
                source_object_id=workflow.object_id,
                target_object_id=source.object_id,
                relation_type=RelationType.EXECUTES,
            ),
        ],
    )
    first_output = tmp_path / "first"
    second_output = tmp_path / "second"

    statistics = StaticWebExporter(repository).export(first_output, depth=4)
    StaticWebExporter(
        CountingRepository([table, source, workflow], repository.relations)
    ).export(second_output, depth=4)

    assert repository.object_reads == 1
    assert repository.relation_reads == 1
    assert statistics.object_count == 3
    assert statistics.detail_count == 3
    assert statistics.flow_count == 3
    assert (first_output / "index.html").is_file()
    assert (first_output / "app.css").is_file()
    assert (first_output / "app.js").is_file()
    index = _read_json(first_output / "data" / "index.json")
    assert index["schema_version"] == 2
    assert index["minimum_query_length"] == 3
    assert index["default_object_id"] == workflow_id
    assert "objects" not in index
    shards = index["shards"]
    assert isinstance(shards, dict)
    assert {"ai7", "dbo", "sou", "stk", "tab", "wor"}.issubset(shards)
    stk_shard = shards["stk"]
    assert isinstance(stk_shard, dict)
    assert stk_shard["object_count"] == 2
    stk_shard_path = stk_shard["path"]
    assert stk_shard_path == "data/search/73746b.json"
    assert isinstance(stk_shard_path, str)
    st_shard = _read_json(first_output / stk_shard_path)
    assert {item["id"] for item in st_shard["objects"]} == {table_id, source_id}
    items = _search_items(first_output)
    assert [item["qualified_name"] for item in items] == [
        "AI7101B::wf_AI7101B",
        "AI7101B::wf_AI7101B::sc_STKOUT",
        "dbo.STKOUT",
    ]
    for item in items:
        object_id = item["id"]
        assert isinstance(object_id, str)
        detail_path = f"data/objects/{object_id}.json"
        flow_path = f"data/flows/{object_id}.json"
        assert (first_output / detail_path).is_file()
        assert (first_output / flow_path).is_file()
    table_flow = _read_json(first_output / "data" / "flows" / f"{table_id}.json")
    downstream = table_flow["downstream"]
    assert isinstance(downstream, list)
    assert source_id in downstream
    assert _read_json(first_output / "data" / "index.json") == _read_json(
        second_output / "data" / "index.json"
    )
    assert {
        path.relative_to(first_output / "data" / "search"): path.read_bytes()
        for path in (first_output / "data" / "search").glob("*.json")
    } == {
        path.relative_to(second_output / "data" / "search"): path.read_bytes()
        for path in (second_output / "data" / "search").glob("*.json")
    }
    assert _read_json(first_output / "data" / "objects" / f"{table_id}.json") == (
        _read_json(second_output / "data" / "objects" / f"{table_id}.json")
    )
    assert table_flow == _read_json(
        second_output / "data" / "flows" / f"{table_id}.json"
    )


def test_export_preserves_ambiguous_names_and_reports_dangling_relations(
    tmp_path: Path,
) -> None:
    first = _object(
        "00000000-0000-0000-0000-000000000011",
        ObjectType.TABLE,
        "dbo.CUSTOMER",
        provider="SQLSERVER",
    )
    second = _object(
        "00000000-0000-0000-0000-000000000012",
        ObjectType.TABLE,
        "public.CUSTOMER",
        provider="GREENPLUM",
    )
    missing = UUID("00000000-0000-0000-0000-000000000099")
    output = tmp_path / "web-dist"

    StaticWebExporter(
        CountingRepository(
            [second, first],
            [
                Relation(
                    source_object_id=first.object_id,
                    target_object_id=missing,
                    relation_type=RelationType.READS,
                )
            ],
        )
    ).export(output)

    items = _search_items(output)
    assert [item["name"] for item in items] == ["CUSTOMER", "CUSTOMER"]
    assert {item["provider"] for item in items} == {"GREENPLUM", "SQLSERVER"}
    flow = _read_json(output / "data" / "flows" / f"{first.object_id}.json")
    warnings = flow["warnings"]
    assert isinstance(warnings, dict)
    assert warnings["dangling_relations"] == 1


def test_export_source_is_rendered_as_text_and_missing_source_is_a_warning(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "unsafe.sql"
    source_path.write_text("<script>alert('unsafe')</script>", encoding="utf-8")
    object_id = UUID("00000000-0000-0000-0000-000000000021")
    location = SourceLocation(
        object_id=object_id,
        source_root=str(tmp_path),
        source_file=source_path.name,
        source_type=SourceType.SQL,
        start_line=1,
        end_line=1,
    )
    missing_location = SourceLocation(
        object_id=object_id,
        source_root=str(tmp_path),
        source_file="missing.sql",
        source_type=SourceType.SQL,
        start_line=1,
    )
    item = _object(
        str(object_id),
        ObjectType.PROCEDURE,
        "dbo.unsafe_proc",
        source_locations=(location, missing_location),
    )
    output = tmp_path / "web-dist"

    StaticWebExporter(CountingRepository([item], [])).export(output)

    detail = _read_json(output / "data" / "objects" / f"{object_id}.json")
    source = detail["source"]
    assert isinstance(source, dict)
    locations = source["locations"]
    assert isinstance(locations, list)
    assert locations[1]["excerpt"] == "<script>alert('unsafe')</script>"
    assert locations[0]["warning"].startswith("Source unavailable:")
    javascript = (output / "app.js").read_text(encoding="utf-8")
    assert ".textContent" in javascript
    assert "innerHTML" not in javascript


def test_browser_uses_lazy_search_shards_and_restorable_history(tmp_path: Path) -> None:
    item = _object(
        "00000000-0000-4000-8000-000000000031",
        ObjectType.TABLE,
        "dbo.STKOUT",
        provider="SQLSERVER",
    )
    output = tmp_path / "web-dist"

    StaticWebExporter(CountingRepository([item], [])).export(output)

    javascript = (output / "app.js").read_text(encoding="utf-8")
    assert 'loadJson("data/index.json")' in javascript
    assert "state.manifest.shards[prefix]" in javascript
    assert "object_count" in javascript
    assert "matches.length===100" in javascript
    assert "setTimeout" in javascript
    assert "history.pushState" in javascript
    assert 'addEventListener("popstate"' in javascript
    assert 'addEventListener("hashchange"' in javascript
    assert 'navigateRoot(requested,"none")' in javascript

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the browser history regression")
    harness = Path(__file__).with_name("navigation_regression.cjs")
    subprocess.run([node, str(harness), str(output / "app.js")], check=True, timeout=10)
