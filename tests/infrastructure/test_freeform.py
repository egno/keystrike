from pathlib import Path

from keystrike.infrastructure.freeform import FileFreeformTextProvider


def test_wraps_long_paragraph(tmp_path: Path):
    file = tmp_path / "practice.txt"
    file.write_text("word " * 40, encoding="utf-8")
    provider = FileFreeformTextProvider(width=40)
    text = provider.load(file)
    for line in text.splitlines():
        assert len(line) <= 40


def test_preserves_paragraph_breaks(tmp_path: Path):
    file = tmp_path / "practice.txt"
    file.write_text("first paragraph\n\nsecond paragraph\n", encoding="utf-8")
    provider = FileFreeformTextProvider(width=80)
    text = provider.load(file)
    assert text.splitlines() == ["first paragraph", "second paragraph"]


def test_strips_blank_lines(tmp_path: Path):
    file = tmp_path / "practice.txt"
    file.write_text("\n\n  \nhello\n\n", encoding="utf-8")
    provider = FileFreeformTextProvider()
    assert provider.load(file) == "hello"
