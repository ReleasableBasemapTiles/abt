"""Tests for abt.utils.zip_tools.extract_zip."""

from zipfile import ZipFile

from abt.utils.zip_tools import extract_zip


def test_extract_zip_flattens_nested_paths(tmp_path):
    zip_path = tmp_path / "archive.zip"
    with ZipFile(zip_path, "w") as zf:
        zf.writestr("nested/folder/data.csv", "row1")
        zf.writestr("top.txt", "toplevel")

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    message = extract_zip(zip_path, out_dir)

    assert (out_dir / "data.csv").read_text() == "row1"
    assert (out_dir / "top.txt").read_text() == "toplevel"
    assert not (out_dir / "nested").exists()
    assert "archive.zip" in message
    assert str(out_dir) in message


def test_extract_zip_skips_directory_entries(tmp_path):
    zip_path = tmp_path / "with_dirs.zip"
    with ZipFile(zip_path, "w") as zf:
        zf.writestr("folder/", "")  # directory entry, no data
        zf.writestr("folder/file.txt", "content")

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    extract_zip(zip_path, out_dir)

    assert (out_dir / "file.txt").read_text() == "content"
    assert not (out_dir / "folder").exists()


def test_extract_zip_silently_overwrites_same_basename_from_different_dirs(tmp_path):
    """Known issue (see docs/code-review-findings.md): flattening
    directory structure means two archive entries that share a basename
    in different folders silently collide on extraction, with
    last-extracted-wins and no warning or error raised."""
    zip_path = tmp_path / "collide.zip"
    with ZipFile(zip_path, "w") as zf:
        zf.writestr("a/x.csv", "from a")
        zf.writestr("b/x.csv", "from b")

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    extract_zip(zip_path, out_dir)

    # Only one x.csv survives -- whichever entry ZipFile's infolist()
    # (write order, for a freshly created archive) extracted last.
    matches = list(out_dir.glob("x.csv"))
    assert len(matches) == 1
    assert matches[0].read_text() == "from b"
