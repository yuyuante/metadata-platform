from pathlib import Path
from typing import cast

from emip.domain import MetadataObject
from emip.repository.metadata_repository import MetadataRepository
from emip.services.pipeline import MetadataPipeline, ScanResult


class InMemoryMetadataRepository:
    def __init__(self) -> None:
        self.objects: list[MetadataObject] = []

    def create_object(self, metadata_object: MetadataObject) -> MetadataObject:
        self.objects.append(metadata_object)
        return metadata_object


def test_pipeline_scans_parses_and_persists_sql_objects(tmp_path: Path) -> None:
    sql_path = tmp_path / "warehouse.sql"
    sql_path.write_text(
        "CREATE TABLE sales.customer (id INT); "
        "CREATE VIEW sales.active_customer AS SELECT 1;",
        encoding="utf-8",
    )
    (tmp_path / "notes.txt").write_text("not SQL", encoding="utf-8")

    repository = InMemoryMetadataRepository()
    pipeline = MetadataPipeline(
        repository=cast(MetadataRepository, repository),
    )

    result = pipeline.run(tmp_path)

    assert result == ScanResult(
        files_scanned=2,
        files_parsed=1,
        objects_created=2,
    )
    assert [item.name for item in repository.objects] == [
        "customer",
        "active_customer",
    ]
