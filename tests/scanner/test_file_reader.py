from pathlib import Path

import pytest

from emip.scanner.file_reader import (
    EncodingReadError,
    FileReader,
    UnsupportedInputError,
)


def test_reader_strips_utf8_bom(tmp_path: Path) -> None:
    path = tmp_path / "bom.sql"
    path.write_bytes("CREATE TABLE customer (id INT);".encode("utf-8-sig"))

    assert FileReader().read(path) == "CREATE TABLE customer (id INT);"


def test_reader_falls_back_to_cp950(tmp_path: Path) -> None:
    path = tmp_path / "cp950.sql"
    content = "-- 中文註解\nCREATE TABLE customer (id INT);"
    path.write_bytes(content.encode("cp950"))

    assert FileReader().read(path) == content


def test_reader_raises_after_all_encodings_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "invalid.sql"
    path.write_bytes(b"placeholder")
    monkeypatch.setattr(Path, "read_bytes", lambda _path: b"\xff\xfe\xff")

    with pytest.raises(EncodingReadError, match="utf-8-sig"):
        FileReader().read(path)


def test_reader_rejects_postgres_custom_dump(tmp_path: Path) -> None:
    path = tmp_path / "dump.sql"
    path.write_bytes(b"PGDMP\x01\x0d\x00binary")

    with pytest.raises(UnsupportedInputError, match="PG custom-format dump"):
        FileReader().read(path)
