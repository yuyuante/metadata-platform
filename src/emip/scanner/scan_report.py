"""Scan failure details and report file generation."""

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class FailedFile:
    """Details about a file that could not be processed."""

    absolute_path: Path
    relative_path: str
    parser: str
    stage: str
    error_type: str
    error_message: str
    statement_type: str | None = None


@dataclass(frozen=True, slots=True)
class ScanSummary:
    """Aggregate results for one repository scan."""

    files_scanned: int
    files_supported: int
    files_failed: int
    objects_created: int
    elapsed_seconds: float


class ScanReportWriter:
    """Write scan statistics and failed-file details to disk."""

    def write(
        self,
        summary: ScanSummary,
        failures: list[FailedFile],
        output_dir: Path = Path("scan-report"),
    ) -> Path:
        """Write all report formats and return the output directory."""

        output_dir.mkdir(parents=True, exist_ok=True)
        self._write_summary(output_dir / "summary.json", summary)
        self._write_csv(output_dir / "failed-files.csv", failures)
        self._write_log(output_dir / "failed-files.log", failures)
        return output_dir

    @staticmethod
    def _write_summary(path: Path, summary: ScanSummary) -> None:
        values: dict[str, Any] = {
            "files_scanned": summary.files_scanned,
            "files_supported": summary.files_supported,
            "files_failed": summary.files_failed,
            "objects_created": summary.objects_created,
            "elapsed_seconds": round(summary.elapsed_seconds, 3),
        }
        path.write_text(
            json.dumps(values, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _write_csv(path: Path, failures: list[FailedFile]) -> None:
        with path.open("w", newline="", encoding="utf-8") as report_file:
            writer = csv.DictWriter(
                report_file,
                fieldnames=(
                    "relative_path",
                    "parser",
                    "stage",
                    "error_type",
                    "error_message",
                ),
            )
            writer.writeheader()
            for failure in failures:
                writer.writerow(
                    {
                        "relative_path": failure.relative_path,
                        "parser": failure.parser,
                        "stage": failure.stage,
                        "error_type": failure.error_type,
                        "error_message": failure.error_message,
                    }
                )

    @staticmethod
    def _write_log(path: Path, failures: list[FailedFile]) -> None:
        blocks: list[str] = []
        for failure in failures:
            statement_type = failure.statement_type or "Unknown"
            blocks.append(
                "\n".join(
                    (
                        "=================================================",
                        failure.relative_path,
                        f"Absolute path: {failure.absolute_path}",
                        f"Parser: {failure.parser}",
                        f"Stage: {failure.stage}",
                        f"Exception: {failure.error_type}",
                        f"Statement type: {statement_type}",
                        f"Message: {failure.error_message}",
                        "=================================================",
                    )
                )
            )
        path.write_text(
            "\n\n".join(blocks) + ("\n" if blocks else ""), encoding="utf-8"
        )
