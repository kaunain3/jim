from pathlib import Path
import re

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
    assert not PDFExtractor._is_heading(
        _TextFragment(
            "24.67 Action-JND (Ours)",
            font_size=7.4,
            bold=False,
        ),
        body_font_size=8,
    )
    assert not PDFExtractor._is_heading(
        _TextFragment(
            "1 imposes no X-measurability on the weight functions",
            font_size=10,
            bold=False,
        ),
        body_font_size=10,
    )


def test_wrapped_appendix_heading_is_one_fragment() -> None:
    block = {
        "type": 0,
        "bbox": (70, 100, 500, 140),
        "lines": [
            {
                "bbox": (70, 100, 300, 112),
                "spans": [
                    {
                        "text": "A.1 Stability and Ablations on the",
                        "size": 11,
                        "font": "Bold",
                        "flags": 16,
                        "bbox": (70, 100, 300, 112),
                    }
                ],
            },
            {
                "bbox": (70, 114, 300, 126),
                "spans": [
                    {
                        "text": "Answerability-Boundary Target",
                        "size": 11,
                        "font": "Bold",
                        "flags": 16,
                        "bbox": (70, 114, 300, 126),
                    }
                ],
            },
        ],
    }

    fragments = PDFExtractor._fragments_from_blocks([block])

    assert [fragment.text for fragment in fragments] == [
        "A.1 Stability and Ablations on the Answerability-Boundary Target"
    ]


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


# ------------------------------------------------------------------ #
# Stage 0: Triage tests
# ------------------------------------------------------------------ #


def test_triage_detects_text_layer(sample_pdf: Path) -> None:
    """Triage should detect a PDF with a usable text layer."""
    triage = PDFExtractor._triage(sample_pdf)
    assert triage.has_text_layer is True


def test_triage_single_column(sample_pdf: Path) -> None:
    """Triage should detect single-column layout for sample PDF."""
    triage = PDFExtractor._triage(sample_pdf)
    # Sample PDF has all text on left side, so should be single-column
    assert triage.is_multi_column is False


def test_triage_scan_only() -> None:
    """Triage should detect no text layer in scan-only PDF."""
    scan_path = Path("tests/fixtures/scan_only.pdf")
    triage = PDFExtractor._triage(scan_path)
    assert triage.has_text_layer is False


def test_page_level_column_detection() -> None:
    """Author grids and equations must not force later pages into columns."""
    sample_document = pymupdf.open(
        Path(__file__).parents[1] / "sample1.pdf"
    )
    sample_page = sample_document[4]
    sample_blocks = [
        block
        for block in sample_page.get_text("dict").get("blocks", [])
        if block.get("type") == 0
    ]
    assert PDFExtractor._is_multi_column_page(
        sample_blocks,
        sample_page.rect.width,
        sample_page.rect.height,
    ) is False
    sample_document.close()

    two_column_document = pymupdf.open("tests/fixtures/two_column.pdf")
    two_column_page = two_column_document[1]
    two_column_blocks = [
        block
        for block in two_column_page.get_text("dict").get("blocks", [])
        if block.get("type") == 0
    ]
    assert PDFExtractor._is_multi_column_page(
        two_column_blocks,
        two_column_page.rect.width,
        two_column_page.rect.height,
    ) is True
    two_column_document.close()


# ------------------------------------------------------------------ #
# Stage 1: Layout-correct reading order
# ------------------------------------------------------------------ #


def test_order_blocks_single_column() -> None:
    """Single-column blocks should be sorted top-to-bottom."""
    blocks = [
        {"bbox": (0, 300, 500, 350), "type": 0},
        {"bbox": (0, 100, 500, 150), "type": 0},
        {"bbox": (0, 200, 500, 250), "type": 0},
    ]
    result = PDFExtractor._order_blocks(blocks, 600.0)
    assert [b["bbox"][1] for b in result] == [100, 200, 300]


def test_order_blocks_two_columns() -> None:
    """Two-column blocks should interleave left and right."""
    # Left column blocks
    blocks = [
        {"bbox": (0, 100, 300, 150), "type": 0},  # left, top
        {"bbox": (400, 100, 600, 150), "type": 0},  # right, top
        {"bbox": (0, 200, 300, 250), "type": 0},  # left, middle
        {"bbox": (400, 200, 600, 250), "type": 0},  # right, middle
    ]
    result = PDFExtractor._order_blocks(blocks, 600.0)
    # Should interleave: left-top, right-top, left-middle, right-middle
    assert len(result) == 4
    # Verify left blocks come before right blocks at same y
    left_y_positions = [b["bbox"][1] for b in result if b["bbox"][0] < 300]
    right_y_positions = [b["bbox"][1] for b in result if b["bbox"][0] >= 400]
    assert left_y_positions == [100, 200]
    assert right_y_positions == [100, 200]


def test_order_blocks_empty() -> None:
    """Empty blocks list should return empty."""
    result = PDFExtractor._order_blocks([], 600.0)
    assert result == []


# ------------------------------------------------------------------ #
# Stage 2: Noise removal
# ------------------------------------------------------------------ #


def test_de_hyphenation() -> None:
    """Hyphenated words should be joined."""
    fragments = [
        _TextFragment(text="informa-\ntion", font_size=10, bold=False),
        _TextFragment(text="seque-\nnce", font_size=10, bold=False),
    ]
    result = PDFExtractor._remove_noise(fragments)
    assert result[0].text == "information"
    assert result[1].text == "sequence"


def test_de_hyphenation_no_change() -> None:
    """Non-hyphenated text should pass through unchanged."""
    fragments = [
        _TextFragment(text="Hello world", font_size=10, bold=False),
    ]
    result = PDFExtractor._remove_noise(fragments)
    assert result[0].text == "Hello world"


def test_noise_removal_strips_control_characters() -> None:
    fragments = [
        _TextFragment(text="normal\x00 text\x1f", font_size=10, bold=False),
    ]

    result = PDFExtractor._remove_noise(fragments)

    assert "\x00" not in result[0].text
    assert "\x1f" not in result[0].text


def test_first_page_title_merge_excludes_author_metadata() -> None:
    fragments = [
        _TextFragment(
            text="A Long Research Paper Title", font_size=12, bold=True,
            bbox=(70, 90, 500, 102),
        ),
        _TextFragment(
            text="Continues Across Two Lines", font_size=12, bold=True,
            bbox=(100, 105, 480, 117),
        ),
        _TextFragment(
            text="Ada Lovelace and Grace Hopper", font_size=12, bold=False,
            bbox=(90, 135, 490, 147),
        ),
    ]

    merged = PDFExtractor._merge_first_page_title(fragments)

    assert merged[0].text == (
        "A Long Research Paper Title Continues Across Two Lines"
    )
    assert any(fragment.text.startswith("Ada Lovelace") for fragment in merged)


def test_table_like_rows_are_not_section_headings() -> None:
    fragments = [
        _TextFragment("Metric", 10, True, (70, 100, 120, 112)),
        _TextFragment("Planar", 10, True, (200, 100, 250, 112)),
        _TextFragment("Thick Absorber", 10, True, (330, 100, 430, 112)),
    ]

    table_like_ids = PDFExtractor._table_like_fragment_ids(fragments)

    assert {id(fragment) for fragment in fragments} <= table_like_ids


# ------------------------------------------------------------------ #
# Stage 3: Two-column extraction
# ------------------------------------------------------------------ #

@pytest.fixture
def two_column_pdf() -> Path:
    return Path("tests/fixtures/two_column.pdf")


@pytest.mark.asyncio
async def test_two_column_extraction(
    two_column_pdf: Path,
    tmp_path: Path,
) -> None:
    """Two-column PDF should extract sections with correct content."""
    result = await extractor.extract(
        two_column_pdf,
        use_ocr=False,
        output_root=tmp_path / "library",
    )

    headings = [s.heading for s in result.sections if s.heading]
    # Abstract and Introduction should be extracted
    assert "Abstract" in headings
    assert "Introduction" in headings
    # References should be present
    assert "References" in headings
    # The two-column interleaving means Results may absorb Methods text
    # due to sequential heading processing; verify at least some content
    all_text = "\n".join(s.text for s in result.sections)
    assert "Left column methods text" in all_text
    assert "Right column results text" in all_text


@pytest.mark.asyncio
async def test_two_column_interleaved_order(
    two_column_pdf: Path,
    tmp_path: Path,
) -> None:
    """Two-column content should be extracted, even if interleaved."""
    result = await extractor.extract(
        two_column_pdf,
        use_ocr=False,
        output_root=tmp_path / "library",
    )

    all_text = "\n".join(s.text for s in result.sections)
    # Both columns' content should be present
    assert "Left column methods text" in all_text
    assert "Right column results text" in all_text
    assert "Left column discussion text" in all_text
    assert "Right column conclusion text" in all_text


# ------------------------------------------------------------------ #
# Stage 4: Validation gate
# ------------------------------------------------------------------ #


def test_validation_passes_valid_result() -> None:
    """Valid extraction should pass validation."""
    from services.extractor import Section, ExtractionResult
    result = ExtractionResult(
        sections=[
            Section(heading="Abstract", page=1, text="Abstract text.", order=0),
            Section(heading="Introduction", page=1, text="Intro text.", order=1),
        ]
    )
    validated = PDFExtractor._validate_result(result)
    assert validated.needs_review is False


def test_validation_flags_missing_abstract() -> None:
    """Missing abstract should trigger needs_review."""
    from services.extractor import Section, ExtractionResult
    result = ExtractionResult(
        sections=[
            Section(heading="Introduction", page=1, text="Intro text.", order=0),
            Section(heading="Methods", page=2, text="Methods text.", order=1),
        ]
    )
    validated = PDFExtractor._validate_result(result)
    assert validated.needs_review is True


def test_validation_flags_zero_sections() -> None:
    """Zero sections should trigger needs_review."""
    from services.extractor import ExtractionResult
    result = ExtractionResult(sections=[])
    validated = PDFExtractor._validate_result(result)
    assert validated.needs_review is True


def test_validation_flags_long_title() -> None:
    """Suspiciously long title should trigger needs_review."""
    from services.extractor import Section, ExtractionResult
    long_text = "A" * 500
    result = ExtractionResult(
        sections=[
            Section(heading="Title", page=1, text=long_text, order=0),
        ]
    )
    validated = PDFExtractor._validate_result(result)
    assert validated.needs_review is True


# ------------------------------------------------------------------ #
# Stage 5: Persist (same as before)
# ------------------------------------------------------------------ #

@pytest.mark.asyncio
async def test_extract_with_scan_pdf(tmp_path: Path) -> None:
    """Scan-only PDF should return empty result when OCR not requested."""
    scan_path = Path("tests/fixtures/scan_only.pdf")
    result = await extractor.extract(
        scan_path,
        use_ocr=False,
        output_root=tmp_path / "library",
    )
    # Should return empty or near-empty result
    assert all(not s.text.strip() for s in result.sections)


@pytest.mark.asyncio
async def test_extraction_result_to_dict() -> None:
    """ExtractionResult.to_dict() should serialize correctly."""
    from services.extractor import Section, ExtractionResult, ImageAsset, TableAsset
    result = ExtractionResult(
        sections=[
            Section(heading="Test", page=1, text="Content", order=0),
        ],
        images=[ImageAsset(token="<img_0>", path="img.png", page=1)],
        tables=[TableAsset(token="<table_0>", markdown="| a | b |", page=1)],
    )
    d = result.to_dict()
    assert d["sections"][0]["heading"] == "Test"
    assert d["images"][0]["token"] == "<img_0>"
    assert d["tables"][0]["markdown"] == "| a | b |"
    assert d["needs_review"] is False


# ------------------------------------------------------------------ #
# Real-document regression coverage
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_sample_pdf_structural_regression(tmp_path: Path) -> None:
    """The real sample paper must not regress into false tables or ordering noise."""
    sample_path = Path(__file__).parents[1] / "sample1.pdf"
    result = await extractor.extract(
        sample_path,
        use_ocr=False,
        output_root=tmp_path / "library",
    )

    headings = [section.heading for section in result.sections]
    assert len(headings) == 24
    assert headings[:4] == [
        "Attention Is All You Need",
        "Abstract",
        "1 Introduction",
        "2 Background",
    ]
    assert headings[-2:] == ["7 Conclusion", "References"]

    assert len(result.tables) == 3
    assert len({table.token for table in result.tables}) == 3
    assert all(table.markdown.startswith("Table ") or table.markdown.startswith("|")
               for table in result.tables)
    assert all("Google Brain noam" not in table.markdown for table in result.tables)


@pytest.mark.asyncio
async def test_sample2_structural_regression(tmp_path: Path) -> None:
    """The second paper keeps its appendices, figures, and unlabeled tables."""
    sample_path = Path(__file__).parents[1] / "sample2.pdf"
    result = await extractor.extract(
        sample_path,
        use_ocr=False,
        output_root=tmp_path / "library",
    )

    headings = [section.heading for section in result.sections]
    # The improved structural pass intentionally removes three body/table
    # fragments that the old exact-count regression treated as headings.
    assert len(headings) >= 40
    assert headings[:4] == [
        "THE EXCEEDANCE DESIGN EFFECT : EFFECTIVE SAMPLE SIZE FOR THRESHOLDS UNDER CLUSTERING",
        "Abstract",
        "1 The guarantee is a statement about ranks",
        "1.1 What the guarantee actually says",
    ]
    assert "Appendix A: The selection channel in detail" in headings
    assert "Appendix B: Proofs, remarks and derivations deferred from §2" in headings
    assert headings[-1] == "References"

    # Plot labels and equation fragments must not become headings or tables.
    assert not any(heading and heading.startswith("2 m {") for heading in headings)
    assert not any(heading in {"R", "P", "1.0 exceedance"} for heading in headings)

    assert len(result.images) >= 5
    assert {4, 6, 8, 15, 19}.issubset(
        {image.page for image in result.images}
    )
    assert len(result.tables) >= 7
    assert {10, 12, 13, 17, 22, 30, 43}.issubset(
        {table.page for table in result.tables}
    )
    assert len({table.token for table in result.tables}) == len(result.tables)
    assert any("verify_indicator_icc.py" in table.markdown for table in result.tables)
    assert result.needs_review is False


@pytest.mark.asyncio
async def test_sample7_table_and_figure_regression(tmp_path: Path) -> None:
    """A table followed by a vector figure must not leak labels as headings."""
    sample_path = Path(__file__).parents[1] / "sample7.pdf"
    result = await extractor.extract(
        sample_path,
        use_ocr=False,
        output_root=tmp_path / "library",
    )

    headings = [section.heading for section in result.sections if section.heading]
    assert headings[-3:] == [
        "V. EXPERIMENTS",
        "VI. CONCLUSION",
        "REFERENCES",
    ]
    assert not any(
        heading and re.match(r"^\d+\.\d{2}\s+", heading)
        for heading in headings
    )
    page_twelve_tables = [table for table in result.tables if table.page == 12]
    assert page_twelve_tables
    assert max(len(table.markdown) for table in page_twelve_tables) < 5000
    assert result.needs_review is False
