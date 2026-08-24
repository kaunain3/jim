from pathlib import Path

import pymupdf
import pytest

from services.extractor import PDFExtractor, _TextFragment, extractor


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    pdf_path = tmp_path / "sample.pdf"

    document = pymupdf.open()

    page_one = document.new_page()
    page_one.insert_text(
        (72, 72),
        "Introduction",
        fontsize=20,
    )
    page_one.insert_text(
        (72, 115),
        "This section explains the purpose of the research project.",
        fontsize=11,
    )

    page_two = document.new_page()
    page_two.insert_text(
        (72, 72),
        "Methods",
        fontsize=20,
    )
    page_two.insert_text(
        (72, 115),
        "The experiment uses a reproducible evaluation method.",
        fontsize=11,
    )

    document.save(pdf_path)
    document.close()

    return pdf_path


@pytest.fixture
def numbered_pdf(tmp_path: Path) -> Path:
    pdf_path = tmp_path / "numbered.pdf"
    document = pymupdf.open()

    page = document.new_page()
    page.insert_text((72, 72), "1", fontsize=12)
    page.insert_text((88, 72), "Introduction", fontsize=12)
    page.insert_text(
        (72, 110),
        "Recurrent neural networks are useful for sequence modeling.",
        fontsize=10,
    )

    page.insert_text((72, 160), "2", fontsize=12)
    page.insert_text((88, 160), "Background", fontsize=12)
    page.insert_text(
        (72, 198),
        "Attention mechanisms model dependencies between positions.",
        fontsize=10,
    )

    document.save(pdf_path)
    document.close()

    return pdf_path


@pytest.mark.asyncio
async def test_extract_headings(sample_pdf: Path, tmp_path: Path) -> None:
    result = await extractor.extract(
        sample_pdf,
        use_ocr=False,
        output_root=tmp_path / "library",
    )

    assert len(result.sections) > 0
    assert all(section.page >= 1 for section in result.sections)

    headings = [
        section.heading
        for section in result.sections
        if section.heading is not None
    ]

    assert "Introduction" in headings
    assert "Methods" in headings


@pytest.mark.asyncio
async def test_extracts_text(sample_pdf: Path, tmp_path: Path) -> None:
    result = await extractor.extract(
        sample_pdf,
        use_ocr=False,
        output_root=tmp_path / "library",
    )

    all_text = "\n".join(
        section.text
        for section in result.sections
    )

    assert "purpose of the research project" in all_text
    assert "reproducible evaluation method" in all_text


@pytest.mark.asyncio
async def test_numbered_headings_are_combined(
    numbered_pdf: Path,
    tmp_path: Path,
) -> None:
    result = await extractor.extract(
        numbered_pdf,
        use_ocr=False,
        output_root=tmp_path / "library",
    )

    headings = [
        section.heading
        for section in result.sections
        if section.heading is not None
    ]

    assert "1 Introduction" in headings
    assert "2 Background" in headings

    introduction = next(
        section
        for section in result.sections
        if section.heading == "1 Introduction"
    )
    assert "Attention mechanisms" not in introduction.text


def test_heading_cleanup_and_artifact_filtering() -> None:
    assert PDFExtractor._normalise_heading("3.1\nAttention") == (
        "3.1 Attention"
    )

    assert not PDFExtractor._is_heading(
        _TextFragment("(A)", font_size=16, bold=True),
        body_font_size=10,
    )
    assert not PDFExtractor._is_heading(
        _TextFragment(") V\n(1)", font_size=16, bold=True),
        body_font_size=10,
    )


@pytest.mark.asyncio
async def test_missing_pdf_raises_error(tmp_path: Path) -> None:
    missing_pdf = tmp_path / "missing.pdf"

    with pytest.raises(FileNotFoundError):
        await extractor.extract(missing_pdf)


@pytest.mark.asyncio
async def test_output_contains_sha256_directory(
    sample_pdf: Path,
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "library"

    await extractor.extract(
        sample_pdf,
        use_ocr=False,
        output_root=output_root,
    )

    assert output_root.exists()
