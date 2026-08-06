from pathlib import Path

from bot.files import dest_path, sanitize_filename


def test_sanitize_replaces_unsafe_runs_with_dash():
    assert sanitize_filename("Road Toll 2026.pdf") == "Road-Toll-2026.pdf"


def test_sanitize_strips_leading_dots():
    assert not sanitize_filename("...secret.pdf").startswith(".")


def test_sanitize_empty_becomes_file():
    assert sanitize_filename("???") == "file"


def test_dest_path_creates_dirs_and_avoids_collisions(tmp_path):
    p1 = dest_path(tmp_path, "doc.pdf", "2026-08")
    p1.write_text("a")
    p2 = dest_path(tmp_path, "doc.pdf", "2026-08")
    assert p1 == tmp_path / "2026-08" / "doc.pdf"
    assert p2 == tmp_path / "2026-08" / "doc-2.pdf"
    assert p2.parent.is_dir()


def test_dest_path_counts_up(tmp_path):
    for expected in ["doc.pdf", "doc-2.pdf", "doc-3.pdf"]:
        p = dest_path(tmp_path, "doc.pdf", "2026-08")
        assert p.name == expected
        p.write_text("x")
