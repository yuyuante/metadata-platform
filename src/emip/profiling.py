"""Optional, reusable low-overhead execution profiling for EMIP scans."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any

STAGES = (
    "File discovery",
    "Directory traversal",
    "File filtering",
    "File reading",
    "Encoding detection",
    "XML parsing",
    "SQL parsing",
    "Namespace processing",
    "Folder extraction",
    "Workflow extraction",
    "Worklet extraction",
    "Task extraction",
    "TaskInstance extraction",
    "Session extraction",
    "Mapping extraction",
    "Transformation extraction",
    "Source extraction",
    "Target extraction",
    "WorkflowLink extraction",
    "Relation generation",
    "Relation extraction",
    "MetadataObject generation",
    "MetadataObject creation",
    "Metadata integration",
    "Repository lookup",
    "Object persistence",
    "Source-location persistence",
    "Relation lookup",
    "Relation resolution",
    "Repository persistence",
    "Metadata persistence",
    "Relation persistence",
    "Graph construction",
    "Graph traversal",
    "Summary generation",
    "Report generation",
    "Total execution",
)


@dataclass
class StageStat:
    elapsed_seconds: float = 0.0
    objects_processed: int = 0


@dataclass
class RepositoryStat:
    metadata_persistence_seconds: float = 0.0
    relation_persistence_seconds: float = 0.0
    transaction_count: int = 0
    insert_count: int = 0
    metadata_insert_count: int = 0
    relation_insert_count: int = 0
    skipped_count: int = 0
    commit_count: int = 0
    query_count: int = 0
    round_trip_count: int = 0
    source_location_insert_count: int = 0


@dataclass
class Profiler:
    """Collect timings only when explicitly requested by the caller."""

    started_at: float = field(default_factory=perf_counter)
    stages: dict[str, StageStat] = field(
        default_factory=lambda: {name: StageStat() for name in STAGES}
    )
    counts: dict[str, int] = field(default_factory=dict)
    repository: RepositoryStat = field(default_factory=RepositoryStat)
    reasons: dict[str, str] = field(default_factory=dict)
    _active: dict[str, list[float]] = field(default_factory=dict, repr=False)
    _finished_total: float | None = field(default=None, init=False, repr=False)

    def start(self, stage: str) -> None:
        """Start a stage timer; repeated and nested uses are supported."""

        self._active.setdefault(stage, []).append(perf_counter())

    def stop(self, stage: str, objects: int = 0) -> float:
        """Stop a stage timer and return its elapsed seconds."""

        starts = self._active.get(stage)
        if not starts:
            return 0.0
        elapsed = perf_counter() - starts.pop()
        if not starts:
            self._active.pop(stage, None)
        self.record(stage, elapsed, objects)
        return elapsed

    def record(self, stage: str, elapsed_seconds: float, objects: int = 0) -> None:
        stat = self.stages.setdefault(stage, StageStat())
        stat.elapsed_seconds += elapsed_seconds
        stat.objects_processed += objects

    def count(self, name: str, amount: int = 1) -> None:
        self.counts[name] = self.counts.get(name, 0) + amount

    def set_reason(self, stage: str, reason: str) -> None:
        self.reasons[stage] = reason

    def repository_event(self, event: str, amount: int = 1) -> None:
        if event.startswith("stage:"):
            self.record(event.removeprefix("stage:"), amount / 1_000_000_000)
        elif event == "transaction":
            self.repository.transaction_count += amount
        elif event in {"insert", "metadata_insert", "relation_insert"}:
            self.repository.insert_count += amount
            if event == "metadata_insert":
                self.repository.metadata_insert_count += amount
            elif event == "relation_insert":
                self.repository.relation_insert_count += amount
        elif event in {"skip", "skipped"}:
            self.repository.skipped_count += amount
        elif event == "commit":
            self.repository.commit_count += amount
        elif event == "query":
            self.repository.query_count += amount
        elif event == "round_trip":
            self.repository.round_trip_count += amount
        elif event == "source_location_insert":
            self.repository.source_location_insert_count += amount

    def finish(self) -> None:
        """Freeze total execution time and make reports reproducible."""

        if self._finished_total is None:
            self._finished_total = perf_counter() - self.started_at
            total_objects = sum(stat.objects_processed for stat in self.stages.values())
            self.record("Total execution", self._finished_total, total_objects)

    @property
    def total_seconds(self) -> float:
        return (
            self._finished_total
            if self._finished_total is not None
            else perf_counter() - self.started_at
        )

    def _stage_dict(self, name: str, stat: StageStat, total: float) -> dict[str, Any]:
        average_ms = (
            stat.elapsed_seconds * 1000 / stat.objects_processed
            if stat.objects_processed
            else 0.0
        )
        objects_per_second = (
            stat.objects_processed / stat.elapsed_seconds
            if stat.elapsed_seconds > 0
            else 0.0
        )
        return {
            "name": name,
            "elapsed_seconds": round(stat.elapsed_seconds, 6),
            "percentage": round(stat.elapsed_seconds / total * 100, 6),
            "objects_processed": stat.objects_processed,
            "average_milliseconds_per_object": round(average_ms, 6),
            "objects_per_second": round(objects_per_second, 6),
            "reason": self.reasons.get(name, ""),
        }

    def to_dict(self) -> dict[str, Any]:
        self.finish()
        total = max(self.total_seconds, 0.000001)
        stages = [
            self._stage_dict(name, stat, total) for name, stat in self.stages.items()
        ]
        ranked = sorted(
            (item for item in stages if item["name"] != "Total execution"),
            key=lambda item: float(item["elapsed_seconds"]),
            reverse=True,
        )
        hotspots = [
            {
                "rank": index,
                "stage": item["name"],
                "elapsed_seconds": item["elapsed_seconds"],
                "percentage": item["percentage"],
                "reason": item["reason"],
            }
            for index, item in enumerate(ranked[:10], start=1)
            if float(item["elapsed_seconds"]) > 0
        ]
        return {
            "schema_version": 1,
            "total_seconds": round(total, 6),
            "stages": stages,
            "counts": dict(sorted(self.counts.items())),
            "repository": {
                "metadata_insert_count": self.repository.metadata_insert_count,
                "relation_insert_count": self.repository.relation_insert_count,
                "insert_count": self.repository.insert_count,
                "skipped_count": self.repository.skipped_count,
                "commit_count": self.repository.commit_count,
                "transaction_count": self.repository.transaction_count,
                "query_count": self.repository.query_count,
                "round_trip_count": self.repository.round_trip_count,
                "source_location_insert_count": (
                    self.repository.source_location_insert_count
                ),
            },
            "hotspots": hotspots,
        }

    def render(self) -> str:
        data = self.to_dict()
        lines = [
            "=" * 96,
            "Performance Summary",
            "=" * 96,
            "",
            f"{'Stage':<30}"
            + f" {'Time (s)':>12} {'%':>8} {'Count':>12} "
            + f"{'Avg ms/object':>16} {'Objects/sec':>14}",
            "-" * 96,
        ]
        for stage in data["stages"]:
            lines.append(
                f"{stage['name']:<30} {stage['elapsed_seconds']:>12.2f} "
                f"{stage['percentage']:>7.2f} {stage['objects_processed']:>12} "
                f"{stage['average_milliseconds_per_object']:>16.3f} "
                f"{stage['objects_per_second']:>14.2f}"
            )
        repository = data["repository"]
        lines.extend(
            [
                "",
                "Repository Statistics",
                f"  Metadata INSERT count: {repository['metadata_insert_count']}",
                f"  Relation INSERT count: {repository['relation_insert_count']}",
                f"  Skipped count: {repository['skipped_count']}",
                f"  Commit count: {repository['commit_count']}",
                f"  Transaction count: {repository['transaction_count']}",
                f"  Query count: {repository['query_count']}",
                f"  Database round-trip count: {repository['round_trip_count']}",
                "  Source-location INSERT count: "
                f"{repository['source_location_insert_count']}",
                "",
                "Object Counts",
            ]
        )
        for name in (
            "Workflow",
            "Task",
            "TaskInstance",
            "Session",
            "Mapping",
            "Transformation",
            "MetadataObject",
            "Relation",
        ):
            lines.append(f"  {name}: {self.counts.get(name, 0)}")
        total = float(data["total_seconds"])
        metadata_count = self.counts.get("MetadataObject", 0)
        relation_count = self.counts.get("Relation", 0)
        lines.extend(
            [
                f"  Objects/sec: {metadata_count / total:.2f}",
                f"  Relations/sec: {relation_count / total:.2f}",
                "",
                "Top 10 Slowest Stages",
                "Top 5 Slowest Stages (legacy view is included above)",
            ]
        )
        for item in data["hotspots"]:
            reason = f" ({item['reason']})" if item["reason"] else ""
            lines.append(
                f"{item['rank']}. {item['stage']} - {item['elapsed_seconds']:.2f} sec "
                f"({item['percentage']:.2f}%){reason}"
            )
        lines.extend(("", "-" * 96, f"Total: {total:.2f} sec", "=" * 96, ""))
        return "\n".join(lines)

    def write(self, output_path: Path) -> None:
        """Write text and the adjacent stable JSON performance report."""

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(self.render(), encoding="utf-8")
        json_path = output_path.with_suffix(".json")
        json_path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
