"""Export repository metadata as deterministic static web artifacts."""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from collections import OrderedDict, defaultdict
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from threading import Lock
from typing import Protocol
from uuid import UUID

from emip.domain import MetadataObject, Relation
from emip.scanner.file_reader import FileReader
from emip.services.data_flow import DataFlowService
from emip.services.dynamic_sql_details import dynamic_sql_details
from emip.services.source_traceability import SourceTraceabilityService


class WebExportRepository(Protocol):
    """Repository reads required by the static exporter."""

    def find_objects(self) -> list[MetadataObject]: ...

    def find_relations(self) -> list[Relation]: ...


@dataclass(frozen=True, slots=True)
class ExportStatistics:
    """Measured result of one static export."""

    object_count: int
    detail_count: int
    flow_count: int
    elapsed_seconds: float
    output_bytes: int

    def to_dict(self) -> dict[str, int | float]:
        return {
            "object_count": self.object_count,
            "detail_count": self.detail_count,
            "flow_count": self.flow_count,
            "elapsed_seconds": self.elapsed_seconds,
            "output_bytes": self.output_bytes,
        }


class _CachedFileReader(FileReader):
    def __init__(self) -> None:
        super().__init__()
        self._cache: OrderedDict[Path, str] = OrderedDict()
        self._lock = Lock()

    def read(self, path: Path) -> str:
        resolved = path.resolve()
        with self._lock:
            if resolved not in self._cache:
                self._cache[resolved] = super().read(resolved)
                if len(self._cache) > 8:
                    self._cache.popitem(last=False)
            self._cache.move_to_end(resolved)
            return self._cache[resolved]


class StaticWebExporter:
    """Create a browser-only metadata application from repository data."""

    _ASSETS = ("index.html", "app.css", "app.js")

    def __init__(self, repository: WebExportRepository) -> None:
        self._repository = repository

    def export(self, output_dir: Path, *, depth: int = 6) -> ExportStatistics:
        if depth < 0:
            raise ValueError("--depth must be non-negative")
        started_at = time.perf_counter()
        objects = sorted(self._repository.find_objects(), key=_object_sort_key)
        relations = list(self._repository.find_relations())
        by_id = {item.object_id: item for item in objects}
        flow_index = DataFlowService().prepare(objects, relations)
        dependencies, used_by = _relationship_indexes(by_id, relations)

        object_dir = output_dir / "data" / "objects"
        flow_dir = output_dir / "data" / "flows"
        search_dir = output_dir / "data" / "search"
        object_dir.mkdir(parents=True, exist_ok=True)
        flow_dir.mkdir(parents=True, exist_ok=True)
        search_dir.mkdir(parents=True, exist_ok=True)
        self._copy_assets(output_dir)

        search_items = [_search_item(item) for item in objects]

        def export_object(
            item: MetadataObject, source_service: SourceTraceabilityService
        ) -> None:
            object_id = str(item.object_id)
            detail_path = f"data/objects/{object_id}.json"
            flow_path = f"data/flows/{object_id}.json"
            _write_json(
                output_dir / detail_path,
                _detail_payload(
                    item,
                    source_service,
                    dependencies[item.object_id],
                    used_by[item.object_id],
                ),
            )
            _write_json(output_dir / flow_path, flow_index.build(item, depth).to_dict())

        def export_group(group: tuple[MetadataObject, ...]) -> None:
            source_service = SourceTraceabilityService(_CachedFileReader())
            for item in group:
                export_object(item, source_service)

        worker_count = min(8, (os.cpu_count() or 1) + 4)
        groups = _source_groups(objects)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            for _ in executor.map(export_group, groups):
                pass

        shard_paths = _write_search_shards(search_dir, search_items)
        index_payload = {
            "schema_version": 2,
            "generated": {"object_count": len(objects), "flow_depth": depth},
            "minimum_query_length": 3,
            "default_object_id": search_items[0]["id"] if search_items else None,
            "shards": shard_paths,
        }
        _write_json(output_dir / "data" / "index.json", index_payload)
        elapsed = time.perf_counter() - started_at
        output_bytes = sum(
            path.stat().st_size for path in output_dir.rglob("*") if path.is_file()
        )
        statistics = ExportStatistics(
            object_count=len(objects),
            detail_count=len(objects),
            flow_count=len(objects),
            elapsed_seconds=elapsed,
            output_bytes=output_bytes,
        )
        _write_json(
            output_dir / "data" / "export-statistics.json",
            statistics.to_dict(),
        )
        return statistics

    @classmethod
    def _copy_assets(cls, output_dir: Path) -> None:
        asset_root = files("emip.web").joinpath("static")
        for asset in cls._ASSETS:
            destination = output_dir / asset
            destination.parent.mkdir(parents=True, exist_ok=True)
            with asset_root.joinpath(asset).open("rb") as source:
                with destination.open("wb") as target:
                    shutil.copyfileobj(source, target)


def _object_sort_key(item: MetadataObject) -> tuple[str, str, str]:
    return (
        item.qualified_name.casefold(),
        item.object_type.value,
        str(item.object_id),
    )


def _source_groups(
    objects: Iterable[MetadataObject], *, maximum_group_size: int = 512
) -> list[tuple[MetadataObject, ...]]:
    """Keep objects from one source together so each file is parsed only once."""
    grouped: defaultdict[str, list[MetadataObject]] = defaultdict(list)
    for item in objects:
        source_keys = sorted(
            f"{location.source_root}\\{location.source_file}".casefold()
            for location in item.source_locations
        )
        key = source_keys[0] if source_keys else ""
        grouped[key].append(item)
    result: list[tuple[MetadataObject, ...]] = []
    for key in sorted(grouped):
        group = grouped[key]
        for offset in range(0, len(group), maximum_group_size):
            result.append(tuple(group[offset : offset + maximum_group_size]))
    return result


def _search_item(item: MetadataObject) -> dict[str, object]:
    return {
        "id": str(item.object_id),
        "qualified_name": item.qualified_name,
        "name": item.name,
        "object_type": item.object_type.value,
        "provider": item.system_name,
    }


_SEARCH_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


def _search_prefixes(item: dict[str, object]) -> set[str]:
    prefixes: set[str] = set()
    for field in ("qualified_name", "name", "object_type", "provider"):
        value = str(item.get(field) or "").lower()
        for token in _SEARCH_TOKEN.findall(value):
            if len(token) >= 3:
                prefixes.add(token[:3])
    return prefixes


def _write_search_shards(
    search_dir: Path, search_items: list[dict[str, object]]
) -> dict[str, dict[str, object]]:
    shards: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
    for item in search_items:
        for prefix in _search_prefixes(item):
            shards[prefix].append(item)

    paths: dict[str, dict[str, object]] = {}
    for prefix in sorted(shards):
        filename = prefix.encode("utf-8").hex()
        relative_path = f"data/search/{filename}.json"
        paths[prefix] = {
            "object_count": len(shards[prefix]),
            "path": relative_path,
        }
        _write_json(
            search_dir / f"{filename}.json",
            {"schema_version": 1, "objects": shards[prefix]},
            compact=True,
        )
    return paths


def _relationship_indexes(
    by_id: dict[UUID, MetadataObject], relations: Iterable[Relation]
) -> tuple[
    defaultdict[UUID, list[dict[str, str]]],
    defaultdict[UUID, list[dict[str, str]]],
]:
    dependencies: defaultdict[UUID, list[dict[str, str]]] = defaultdict(list)
    used_by: defaultdict[UUID, list[dict[str, str]]] = defaultdict(list)
    seen: set[tuple[UUID, str, UUID]] = set()
    for relation in relations:
        source = relation.source_object_id
        target = relation.target_object_id
        relation_type = str(relation.relation_type)
        key = (source, relation_type, target)
        invalid = source not in by_id or target not in by_id or source == target
        if invalid or key in seen:
            continue
        seen.add(key)
        dependencies[source].append(_related_item(by_id[target], relation_type))
        used_by[target].append(_related_item(by_id[source], relation_type))
    for values in (*dependencies.values(), *used_by.values()):
        values.sort(
            key=lambda value: (
                value["qualified_name"].casefold(),
                value["relation_type"],
                value["id"],
            )
        )
    return dependencies, used_by


def _related_item(item: MetadataObject, relation_type: str) -> dict[str, str]:
    return {
        "id": str(item.object_id),
        "qualified_name": item.qualified_name,
        "object_type": item.object_type.value,
        "provider": item.system_name,
        "relation_type": relation_type,
    }


def _detail_payload(
    item: MetadataObject,
    source_service: SourceTraceabilityService,
    dependencies: list[dict[str, str]],
    used_by: list[dict[str, str]],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "object": {
            "id": str(item.object_id),
            "qualified_name": item.qualified_name,
            "name": item.name,
            "display_name": item.display_name,
            "object_type": item.object_type.value,
            "provider": item.system_name,
            "system": item.system_name,
            "owner": item.owner_name,
            "description": item.description,
            "status": item.status.value,
        },
        "properties": [
            {"name": value.property_name, "value": value.property_value}
            for value in sorted(
                item.properties,
                key=lambda value: (
                    value.property_name.casefold(),
                    value.property_value or "",
                ),
            )
        ],
        "dynamic_sql": dynamic_sql_details(item),
        "columns": [
            {
                "name": value.column_name,
                "ordinal_position": value.ordinal_position,
                "datatype": value.datatype,
                "nullable": value.nullable,
                "default": value.default_value,
                "primary_key": value.is_primary_key,
                "unique": value.is_unique,
            }
            for value in sorted(
                item.columns,
                key=lambda value: (
                    value.ordinal_position,
                    value.column_name.casefold(),
                ),
            )
        ],
        "source": source_service.retrieve(item),
        "dependencies": dependencies,
        "used_by": used_by,
    }


def _write_json(path: Path, payload: object, *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if compact:
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    else:
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    path.write_text(
        serialized + "\n",
        encoding="utf-8",
        newline="\n",
    )
