from pathlib import Path

from emip.scanner.folder_scanner import FolderScanner


def test_scan_empty_folder(tmp_path: Path) -> None:
    assert FolderScanner().scan(tmp_path) == []


def test_scan_single_file(tmp_path: Path) -> None:
    file_path = tmp_path / "single.txt"
    file_path.write_text("content", encoding="utf-8")

    assert FolderScanner().scan(tmp_path) == [file_path.resolve()]


def test_scan_nested_folders_and_multiple_files(tmp_path: Path) -> None:
    first = tmp_path / "nested" / "first.txt"
    second = tmp_path / "second" / "second.sql"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    root_file = tmp_path / "root.py"
    root_file.write_text("root", encoding="utf-8")

    assert FolderScanner().scan(tmp_path) == sorted(
        [first.resolve(), second.resolve(), root_file.resolve()]
    )


def test_scan_ignores_directories_and_includes_hidden_files(tmp_path: Path) -> None:
    hidden = tmp_path / ".hidden"
    directory = tmp_path / "empty-directory"
    hidden.write_text("hidden", encoding="utf-8")
    directory.mkdir()

    assert FolderScanner().scan(tmp_path) == [hidden.resolve()]


def test_scan_includes_chinese_filename(tmp_path: Path) -> None:
    chinese_file = tmp_path / "資料表.sql"
    chinese_file.write_text("CREATE TABLE sample (id INT);", encoding="utf-8")

    assert FolderScanner().scan(tmp_path) == [chinese_file.resolve()]


def test_scan_ignores_testsuite_files(tmp_path: Path) -> None:
    ddl = tmp_path / "deployment.sql"
    test_suite = tmp_path / "deployment.TestSuite.sql"
    ddl.write_text("CREATE TABLE sample (id INT);", encoding="utf-8")
    test_suite.write_text("CREATE TABLE test_only (id INT);", encoding="utf-8")

    assert FolderScanner().scan(tmp_path) == [ddl.resolve()]


def test_scan_returns_deterministic_ordering(tmp_path: Path) -> None:
    paths = [tmp_path / name for name in ("z.txt", "a.txt", "m.txt")]
    for path in paths:
        path.write_text(path.name, encoding="utf-8")

    scanner = FolderScanner()
    first_scan = scanner.scan(tmp_path)
    second_scan = scanner.scan(tmp_path)

    assert first_scan == sorted(path.resolve() for path in paths)
    assert first_scan == second_scan


def test_scan_includes_symbolic_link_to_file(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    link = tmp_path / "link.txt"
    target.write_text("target", encoding="utf-8")
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        assert FolderScanner().scan(tmp_path) == [target.resolve()]
    else:
        assert FolderScanner().scan(tmp_path) == sorted(
            [link.resolve(), target.resolve()]
        )
