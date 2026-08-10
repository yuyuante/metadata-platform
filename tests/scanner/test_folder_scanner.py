from pathlib import Path

from emip.scanner.folder_scanner import FolderScanner


def test_scan_empty_folder(tmp_path: Path) -> None:
    assert FolderScanner.scan(tmp_path) == []


def test_scan_nested_folders_and_multiple_files(tmp_path: Path) -> None:
    first = tmp_path / "nested" / "first.txt"
    second = tmp_path / "second" / "second.sql"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    (tmp_path / "root.py").write_text("root", encoding="utf-8")

    assert FolderScanner.scan(tmp_path) == sorted([first, second, tmp_path / "root.py"])


def test_scan_ignores_directories_and_includes_hidden_files(tmp_path: Path) -> None:
    hidden = tmp_path / ".hidden"
    directory = tmp_path / "empty-directory"
    hidden.write_text("hidden", encoding="utf-8")
    directory.mkdir()

    assert FolderScanner.scan(tmp_path) == [hidden]


def test_scan_includes_symbolic_link_to_file(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    link = tmp_path / "link.txt"
    target.write_text("target", encoding="utf-8")
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        assert FolderScanner.scan(tmp_path) == [target]
    else:
        assert FolderScanner.scan(tmp_path) == sorted([link, target])
