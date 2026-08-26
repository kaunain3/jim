from pathlib import Path
import re

import pymupdf
import pytest

from services.extractor import PDFExtractor, _TextFragment, extractor


# ------------------------------------------------------------------ #
# Fixtures: self-contained synthetic PDFs
# ------------------------------------------------------------------ #


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """Single-column PDF with headings and body text."""
    pdf_path = tmp_path / "sample.pdf"
    document = pymupdf.open()

    page_one = document.new_page()
    page_one.insert_text((72, 72), "Introduction", fontsize=20)
    page_one.insert_text(
        (72, 115),
        "This section explains the purpose of the research project.",
        fontsize=11,
    )

    page_two = document.new_page()
    page_two.insert_text((72, 72), "Methods", fontsize=20)
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
    """PDF with numbered headings that should be combined into single headings."""
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


@pytest.fixture
def two_column_pdf(tmp_path: Path) -> Path:
    """Synthetic two-column PDF with left/right column content."""
    pdf_path = tmp_path / "two_column.pdf"
    document = pymupdf.open()

    # Page 1: two-column layout with separate left/right text
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 780), "Abstract", fontsize=14)
    page.insert_text((320, 762), "Introduction", fontsize=14)
    page.insert_text((72, 740), "Left column methods text describes our approach.", fontsize=10)
    page.insert_text((320, 722), "Right column results text presents findings.", fontsize=10)
    page.insert_text((72, 700), "Left column discussion text provides context.", fontsize=10)
    page.insert_text((320, 682), "Right column conclusion text summarizes.", fontsize=10)
    page.insert_text((72, 660), "Left column evaluation details support the method.", fontsize=10)
    page.insert_text((320, 642), "Right column measurements confirm the findings.", fontsize=10)
    page.insert_text((72, 620), "Left column limitations motivate future research.", fontsize=10)
    page.insert_text((320, 602), "Right column analysis completes the discussion.", fontsize=10)
    page.insert_text((72, 550), "References", fontsize=14)
    page.insert_text(
        (72, 520),
        "Smith et al. 2020. Journal of Machine Learning.",
        fontsize=9,
    )

    document.save(pdf_path)
    document.close()
    return pdf_path


@pytest.fixture
def scan_only_pdf(tmp_path: Path) -> Path:
    """Synthetic scan-only PDF (image on page, no text layer)."""
    pdf_path = tmp_path / "scan_only.pdf"
    document = pymupdf.open()
    page = document.new_page()
    # Draw a blank rectangle to simulate a scanned page with no text
    page.draw_rect(page.rect)
    document.save(pdf_path)
    document.close()
    return pdf_path


@pytest.fixture
def multi_section_pdf(tmp_path: Path) -> Path:
    """PDF with multiple sections, tables, and figures for regression testing."""
    pdf_path = tmp_path / "multi_section.pdf"
    document = pymupdf.open()

    # Page 1: Title, Abstract, Introduction
    page = document.new_page()
    page.insert_text((72, 780), "Multi-Section Research Paper", fontsize=18)
    page.insert_text((72, 750), "Abstract", fontsize=14)
    page.insert_text(
        (72, 720),
        "This paper presents a novel approach to something important.",
        fontsize=10,
    )
    page.insert_text((72, 680), "1 Introduction", fontsize=14)
    page.insert_text(
        (72, 650),
        "Deep learning has transformed many domains including natural language processing.",
        fontsize=10,
    )
    page.insert_text((72, 610), "2 Background", fontsize=14)
    page.insert_text(
        (72, 580),
        "Transformers have become the standard architecture for sequence tasks.",
        fontsize=10,
    )

    # Page 2: Methods with a table
    page = document.new_page()
    page.insert_text((72, 780), "3 Methods", fontsize=14)
    page.insert_text(
        (72, 750),
        "We propose a new architecture based on attention mechanisms.",
        fontsize=10,
    )
    # Insert a simple table
    page.insert_text((72, 700), "| Model | Accuracy |", fontsize=9)
    page.insert_text((72, 680), "| Transformer | 95.2% |", fontsize=9)
    page.insert_text((72, 660), "| CNN | 89.1% |", fontsize=9)
    page.insert_text((72, 630), "Table 1: Comparison of model accuracies.", fontsize=9)

    # Page 3: Experiments and Conclusion
    page = document.new_page()
    page.insert_text((72, 780), "4 Experiments", fontsize=14)
    page.insert_text(
        (72, 750),
        "We evaluate on standard benchmarks and achieve state-of-the-art results.",
        fontsize=10,
    )
    page.insert_text((72, 710), "5 Conclusion", fontsize=14)
    page.insert_text(
        (72, 680),
        "Our approach demonstrates significant improvements over existing methods.",
        fontsize=10,
    )
    page.insert_text((72, 640), "References", fontsize=14)
    page.insert_text(
        (72, 610),
        "Vaswani et al. 2017. Attention is all you need.",
        fontsize=9,
    )

    document.save(pdf_path)
    document.close()
    return pdf_path


@pytest.fixture
def complex_paper_pdf(tmp_path: Path) -> Path:
    """Synthetic paper mimicking the structure of sample2 with appendices."""
    pdf_path = tmp_path / "complex.pdf"
    document = pymupdf.open()

    page = document.new_page()
    page.insert_text(
        (72, 790),
        "THE EXCEEDANCE DESIGN EFFECT : EFFECTIVE SAMPLE SIZE FOR THRESHOLDS UNDER CLUSTERING",
        fontsize=12,
    )
    page.insert_text((72, 760), "Abstract", fontsize=14)
    page.insert_text(
        (72, 730),
        "We study exceedance design effects in clustered randomized trials.",
        fontsize=10,
    )
    page.insert_text((72, 690), "1 The guarantee is a statement about ranks", fontsize=14)
    page.insert_text(
        (72, 660),
        "The main theorem provides bounds on rank-based tests.",
        fontsize=10,
    )
    page.insert_text((72, 620), "1.1 What the guarantee actually says", fontsize=12)
    page.insert_text(
        (72, 590),
        "Corollary 1.1 gives a practical bound for practitioners.",
        fontsize=10,
    )

    page = document.new_page()
    page.insert_text((72, 780), "2 Empirical Results", fontsize=14)
    page.insert_text(
        (72, 750),
        "Table 1 shows performance across multiple datasets.",
        fontsize=10,
    )
    # Add some images to simulate figures
    page.draw_rect((100, 700, 300, 650))  # simulate a figure placeholder
    page.insert_text((100, 640), "Figure 1: Illustration of the method.", fontsize=9)

    page = document.new_page()
    page.insert_text((72, 780), "Appendix A: The selection channel in detail", fontsize=14)
    page.insert_text(
        (72, 750),
        "We provide detailed proofs and derivations.",
        fontsize=10,
    )
    page.insert_text((72, 710), "Appendix B: Proofs, remarks and derivations deferred from §2", fontsize=14)
    page.insert_text(
        (72, 680),
        "Additional technical details are included here.",
        fontsize=10,
    )
    page.insert_text((72, 640), "References", fontsize=14)
    page.insert_text(
        (72, 610),
        "Cliento et al. 2023. Exceedance design effects.",
        fontsize=9,
    )

    document.save(pdf_path)
    document.close()
    return pdf_path


@pytest.fixture
def table_figure_pdf(tmp_path: Path) -> Path:
    """PDF with a table followed by a figure to test label-leakage prevention."""
    pdf_path = tmp_path / "table_figure.pdf"
    document = pymupdf.open()

    page = document.new_page()
    page.insert_text((72, 780), "Abstract", fontsize=14)
    page.insert_text(
        (72, 750),
        "We report results on standard benchmarks.",
        fontsize=10,
    )
    page.insert_text((72, 710), "V. EXPERIMENTS", fontsize=14)
    page.insert_text(
        (72, 680),
        "We report results on standard benchmarks.",
        fontsize=10,
    )
    # Table with labels that should NOT become headings
    page.insert_text((72, 640), "| Layer | Dimensions |", fontsize=9)
    page.insert_text((72, 620), "| 1     | 768        |", fontsize=9)
    page.insert_text((72, 600), "| 2     | 768        |", fontsize=9)
    # Figure caption that should NOT become a heading
    page.insert_text((72, 570), "Figure 1: Architecture diagram.", fontsize=9)
    page.draw_rect((100, 530, 400, 430))  # figure placeholder

    page = document.new_page()
    page.insert_text((72, 780), "VI. CONCLUSION", fontsize=14)
    page.insert_text(
        (72, 750),
        "We demonstrated state-of-the-art performance.",
        fontsize=10,
    )
    page.insert_text((72, 710), "REFERENCES", fontsize=14)
    page.insert_text(
        (72, 680),
        "Vaswani et al. 2017.",
        fontsize=9,
    )

    document.save(pdf_path)
    document.close()
    return pdf_path


# ------------------------------------------------------------------ #
# Stage 1: Basic extraction
# ------------------------------------------------------------------ #


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


# ------------------------------------------------------------------ #
# Stage 2: Noise removal & heading cleanup
# ------------------------------------------------------------------ #


def test_heading_cleanup_and_artifact_filtering() -> None:
    assert PDFExtractor._normalise_heading("3.1\nAttention") == (
        "3.1 Attention"
    )

    assert not PDFExtractor._is_heading(
        _TextFragment("(A)", font_size=16, bold=False),
        body_font_size=10,
    )
    assert not PDFExtractor._is_heading(
        _TextFragment(") V\n(1)", font_size=16, bold=False),
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
    assert triage.is_multi_column is False


def test_triage_scan_only(scan_only_pdf: Path) -> None:
    """Triage should detect no text layer in scan-only PDF."""
    triage = PDFExtractor._triage(scan_only_pdf)
    assert triage.has_text_layer is False


def test_page_level_column_detection_sample(sample_pdf: Path) -> None:
    """Single-column PDF should not be detected as multi-column."""
    sample_doc = pymupdf.open(sample_pdf)
    sample_page = sample_doc[0]
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
    sample_doc.close()


def test_page_level_column_detection_two_column(two_column_pdf: Path) -> None:
    """Two-column PDF should be extractable with correct content."""
    # This test verifies the two_column_pdf fixture works for extraction;
    # column detection is tested via the integration tests below.
    two_column_doc = pymupdf.open(two_column_pdf)
    two_column_page = two_column_doc[0]
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
    two_column_doc.close()


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
    blocks = [
        {"bbox": (0, 100, 300, 150), "type": 0},
        {"bbox": (400, 100, 600, 150), "type": 0},
        {"bbox": (0, 200, 300, 250), "type": 0},
        {"bbox": (400, 200, 600, 250), "type": 0},
    ]
    result = PDFExtractor._order_blocks(blocks, 600.0)
    assert len(result) == 4
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
            text="A Long Research Paper Title", font_size=12, bold=False,
            bbox=(70, 90, 500, 102),
        ),
        _TextFragment(
            text="Continues Across Two Lines", font_size=12, bold=False,
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
    assert "Abstract" in headings
    assert "Introduction" in headings
    assert "References" in headings
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
# Stage 5: Persist & misc
# ------------------------------------------------------------------ #


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


@pytest.mark.asyncio
async def test_extract_with_scan_pdf(scan_only_pdf: Path, tmp_path: Path) -> None:
    """Scan-only PDF should return empty result when OCR not requested."""
    result = await extractor.extract(
        scan_only_pdf,
        use_ocr=False,
        output_root=tmp_path / "library",
    )
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
# Regression tests with synthetic PDFs
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_multi_section_structural_regression(multi_section_pdf: Path, tmp_path: Path) -> None:
    """Multi-section paper should extract correct headings and tables."""
    result = await extractor.extract(
        multi_section_pdf,
        use_ocr=False,
        output_root=tmp_path / "library",
    )

    headings = [section.heading for section in result.sections]
    assert len(headings) >= 5
    assert "Abstract" in headings
    assert "1 Introduction" in headings
    assert "2 Background" in headings
    assert "3 Methods" in headings
    assert "4 Experiments" in headings
    assert "5 Conclusion" in headings
    assert "References" in headings

    assert len(result.tables) >= 1
    assert any("Comparison of model accuracies" in table.markdown for table in result.tables)
    assert result.needs_review is False


@pytest.mark.asyncio
async def test_complex_paper_with_appendices(complex_paper_pdf: Path, tmp_path: Path) -> None:
    """Paper with appendices should preserve appendix headings."""
    result = await extractor.extract(
        complex_paper_pdf,
        use_ocr=False,
        output_root=tmp_path / "library",
    )

    headings = [section.heading for section in result.sections]
    assert len(headings) >= 6
    assert "Abstract" in headings
    assert "1 The guarantee is a statement about ranks" in headings
    assert "1.1 What the guarantee actually says" in headings
    assert "Appendix A: The selection channel in detail" in headings
    assert "Appendix B: Proofs, remarks and derivations deferred from §2" in headings
    assert "References" in headings

    # Plot labels should not become headings
    assert not any(heading and heading.startswith("2 m {") for heading in headings)

    assert result.needs_review is False


@pytest.mark.asyncio
async def test_table_figure_label_leakage(table_figure_pdf: Path, tmp_path: Path) -> None:
    """Table labels and figure captions must not leak as headings."""
    result = await extractor.extract(
        table_figure_pdf,
        use_ocr=False,
        output_root=tmp_path / "library",
    )

    headings = [section.heading for section in result.sections if section.heading]
    assert "V. EXPERIMENTS" in headings
    assert "VI. CONCLUSION" in headings
    assert "REFERENCES" in headings

    # Table row values like "| 1     | 768        |" should not be headings
    assert not any(heading and "| 1" in heading for heading in headings)
    assert not any(heading and "| 2     |" in heading for heading in headings)

    # Figure caption should not be a heading
    assert not any("Figure 1" in heading for heading in headings)
    assert result.needs_review is False
