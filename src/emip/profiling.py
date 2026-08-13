"""Optional, low-overhead execution profiling for EMIP scans."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter

STAGES = (
    "File discovery",
    "File filtering",
    "File reading",
    "Encoding detection",
    "XML parsing",
    "SQL parsing",
    "Namespace processing",
    "Workflow extraction",
    "Task extraction",
    "Session extraction",
    "Mapping extraction",
    "Transformation extraction",
    "Relation extraction",
    "MetadataObject creation",
    "Repository persistence",
    "Metadata persistence",
    "Relation persistence",
    "Graph construction",
    "Graph traversal",
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
    commit_count: int = 0


@dataclass
class Profiler:
    """Collect timings only when explicitly requested by the caller."""

    started_at: float = field(default_factory=perf_counter)
    stages: dict[str, StageStat] = field(
        default_factory=lambda: {name: StageStat() for name in STAGES}
    )
    counts: dict[str, int] = field(default_factory=dict)
    repository: RepositoryStat = field(default_factory=RepositoryStat)

    def record(self, stage: str, elapsed_seconds: float, objects: int = 0) -> None:
        stat = self.stages.setdefault(stage, StageStat())
        stat.elapsed_seconds += elapsed_seconds
        stat.objects_processed += objects

    def count(self, name: str, amount: int = 1) -> None:
        self.counts[name] = self.counts.get(name, 0) + amount

    def repository_event(self, event: str, amount: int = 1) -> None:
        if event == "transaction":
            self.repository.transaction_count += amount
        elif event == "insert":
            self.repository.insert_count += amount
        elif event == "commit":
            self.repository.commit_count += amount

    @property
    def total_seconds(self) -> float:
        return perf_counter() - self.started_at

    def render(self) -> str:
        total = max(self.total_seconds, 0.000001)
        lines = ["=" * 56, "Performance Summary", "=" * 56, ""]
        for name, stat in self.stages.items():
            percentage = stat.elapsed_seconds / total * 100
            average = (
                stat.elapsed_seconds / stat.objects_processed
                if stat.objects_processed
                else 0.0
            )
            lines.extend(
                (
                    name,
                    f"  Elapsed: {stat.elapsed_seconds:.2f} sec ({percentage:.2f}%)",
                    f"  Objects: {stat.objects_processed}",
                    f"  Average/object: {average:.6f} sec",
                    "",
                )
            )
        lines.extend(
            (
                "Repository Statistics",
                (
                    "  Metadata persistence: "
                    f"{self.repository.metadata_persistence_seconds:.2f} sec"
                ),
                (
                    "  Relation persistence: "
                    f"{self.repository.relation_persistence_seconds:.2f} sec"
                ),
                f"  Transactions: {self.repository.transaction_count}",
                f"  Inserts: {self.repository.insert_count}",
                f"  Commits: {self.repository.commit_count}",
                "",
                "Object Counts",
            )
        )
        for name in (
            "Workflow",
            "Task",
            "Session",
            "Mapping",
            "Transformation",
            "MetadataObject",
            "Relation",
        ):
            lines.append(f"  {name}: {self.counts.get(name, 0)}")
        object_count = self.counts.get("MetadataObject", 0)
        relation_count = self.counts.get("Relation", 0)
        lines.extend(
            (
                f"  Objects/sec: {object_count / total:.2f}",
                f"  Relations/sec: {relation_count / total:.2f}",
                "",
                "Top 5 Slowest Stages",
            )
        )
        ranked = sorted(
            (item for item in self.stages.items() if item[0] != "Total execution"),
            key=lambda item: item[1].elapsed_seconds,
            reverse=True,
        )
        for index, (name, stat) in enumerate(ranked[:5], start=1):
            lines.append(f"{index}. {name} - {stat.elapsed_seconds / total * 100:.2f}%")
        lines.extend(("", "-" * 56, f"Total: {total:.2f} sec", "=" * 56, ""))
        return "\n".join(lines)

    def write(self, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(self.render(), encoding="utf-8")
