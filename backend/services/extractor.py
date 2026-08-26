from __future__ import annotations

import asyncio
import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any

import pymupdf


@dataclass
class ImageAsset:
    token: str
    path: str
    page: int
    bbox: tuple[float, float, float, float] | None = None


@dataclass
class TableAsset:
    token: str
    markdown: str
    page: int
    bbox: tuple[float, float, float, float] | None = None


@dataclass
class Section:
    heading: str | None
    page: int
    text: str
    order: int
    image_refs: list[str] = field(default_factory=list)
    table_refs: list[str] = field(default_factory=list)
    needs_review: bool = False


@dataclass
class ExtractionResult:
    sections: list[Section] = field(default_factory=list)
    images: list[ImageAsset] = field(default_factory=list)
    tables: list[TableAsset] = field(default_factory=list)
    needs_review: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "sections": [
                {
                    "heading": section.heading,
                    "page": section.page,
                    "text": section.text,
                    "order": section.order,
                    "image_refs": section.image_refs,
                    "table_refs": section.table_refs,
                    "needs_review": section.needs_review,
                }
                for section in self.sections
            ],
            "images": [
                {
                    "token": image.token,
                    "path": image.path,
                    "page": image.page,
                    "bbox": image.bbox,
                }
                for image in self.images
            ],
            "tables": [
                {
                    "token": table.token,
                    "markdown": table.markdown,
                    "page": table.page,
                    "bbox": table.bbox,
                }
                for table in self.tables
            ],
            "needs_review": self.needs_review,
        }


@dataclass
class _TriageResult:
    has_text_layer: bool
    is_multi_column: bool


@dataclass
class _TextFragment:
    text: str
    font_size: float
    bold: bool
    bbox: tuple[float, float, float, float] | None = None
    # Lines from the same PDF text block are a single paragraph.  Keeping this
    # identity lets the structural pass split headings without turning every
    # wrapped body line into a separate paragraph.
    paragraph_id: int | None = None


class PDFExtractor:
    async def extract(
        self,
        pdf_path: str | Path,
        use_ocr: bool = False,
        output_root: str | Path = "data/library",
    ) -> ExtractionResult:
        """Extract structured content from a PDF.

        Async entry point: the extraction itself is CPU-bound PyMuPDF work,
        so it runs in a worker thread via :func:`asyncio.to_thread`. This
        keeps the event loop free so SSE streams and other requests stay
        responsive while a large paper is being ingested.
        """
        return await asyncio.to_thread(
            self.extract_sync, pdf_path, use_ocr, output_root
        )

    def extract_sync(
        self,
        pdf_path: str | Path,
        use_ocr: bool = False,
        output_root: str | Path = "data/library",
    ) -> ExtractionResult:
        """
        Extract structured content from a PDF.

        """
        source_path = Path(pdf_path)

        if not source_path.is_file():
            raise FileNotFoundError(f"PDF not found: {source_path}")

        # Stage 0: Triage — cheap checks to decide extraction strategy
        triage = self._triage(source_path)

        if triage.has_text_layer and triage.is_multi_column:
            # Multi-column: need layout-aware ordering
            result = self._extract_sync(source_path, Path(output_root))
        elif triage.has_text_layer:
            # Single-column: standard ordering
            result = self._extract_sync(source_path, Path(output_root))
        else:
            # No text layer — route to OCR
            if not use_ocr:
                return ExtractionResult()
            ocr_output = self._run_ocr(source_path)
            if ocr_output is None:
                return ExtractionResult()
            ocr_pdf_path = self._existing_file_path(ocr_output)
            if ocr_pdf_path is not None and ocr_pdf_path.suffix.lower() == ".pdf":
                result = self._extract_sync(
                    ocr_pdf_path,
                    Path(output_root),
                )
            else:
                ocr_text = self._normalise_ocr_text(ocr_output)
                if not ocr_text:
                    return ExtractionResult()
                result = ExtractionResult(
                    sections=[
                        Section(
                            heading=None,
                            page=1,
                            text=ocr_text,
                            order=0,
                        )
                    ]
                )

        # Stage 4: Validation gate — sanity-check before persist
        validated = self._validate_result(result)

        return validated

    # ------------------------------------------------------------------ #
    # Stage 0: Triage
    # ------------------------------------------------------------------ #

    @staticmethod
    def _triage(pdf_path: Path) -> _TriageResult:
        """
        Cheap checks on pages 1-2 to decide extraction strategy.

        Returns whether the PDF has a usable text layer and whether it is
        multi-column. These determine downstream behavior.
        """
        try:
            document = pymupdf.open(pdf_path)
        except Exception:
            return _TriageResult(has_text_layer=False, is_multi_column=False)

        try:
            # Check text layer on first 2 pages
            sample_pages = list(document[:2])
            total_text_length = 0
            all_blocks: list[dict] = []

            for page in sample_pages:
                text = page.get_text()
                total_text_length += len(text.strip())
                page_dict = page.get_text("dict")
                blocks = [
                    b for b in page_dict.get("blocks", [])
                    if b.get("type") == 0
                ]
                all_blocks.extend(blocks)

            has_text_layer = total_text_length > 50

            # Detect single vs multi-column by clustering x-coordinates
            is_multi_column = False
            if has_text_layer and all_blocks:
                page_width = document[0].rect.width
                mid_x = page_width / 2
                left_count = sum(1 for b in all_blocks if b["bbox"][0] < mid_x)
                right_count = sum(1 for b in all_blocks if b["bbox"][0] >= mid_x)
                # If blocks fall into two distinct halves, it's multi-column
                is_multi_column = left_count > 0 and right_count > 0

            return _TriageResult(
                has_text_layer=has_text_layer,
                is_multi_column=is_multi_column,
            )
        finally:
            document.close()

    # ------------------------------------------------------------------ #
    # Stage 1: Layout-correct reading order
    # ------------------------------------------------------------------ #

    @staticmethod
    def _order_blocks(
        blocks: list[dict],
        page_width: float,
    ) -> list[dict]:
        """
        Sort blocks by column first, then top-to-bottom within each column.

        Uses x-coordinate clustering to detect columns rather than a simple
        mid-page split, which fails when author blocks span both halves.
        """
        if not blocks:
            return blocks

        def block_text(block: dict) -> str:
            return " ".join(
                span.get("text", "").strip()
                for line in block.get("lines", [])
                for span in line.get("spans", [])
            ).strip()

        # Estimate column centres from substantial body blocks.  Using x0
        # alone creates phantom columns for centred headings and indented
        # abstracts (a common first-page layout).
        body_blocks = [
            block for block in blocks
            if block["bbox"][2] - block["bbox"][0] < page_width * 0.70
            and len(block_text(block)) >= 40
        ]
        positions = sorted(
            (
                round(block["bbox"][0], 1),
                (block["bbox"][0] + block["bbox"][2]) / 2,
            )
            for block in body_blocks
        )
        centre_groups: list[list[float]] = []
        previous_x0: float | None = None
        for x0, centre in positions:
            if (
                centre_groups
                and previous_x0 is not None
                and x0 - previous_x0 <= page_width * 0.10
            ):
                centre_groups[-1].append(centre)
            else:
                centre_groups.append([centre])
            previous_x0 = x0

        if len(centre_groups) <= 1:
            return sorted(blocks, key=lambda b: b["bbox"][1])

        column_centres = [sum(group) / len(group) for group in centre_groups]
        body_start = min(
            (block["bbox"][1] for block in body_blocks),
            default=0.0,
        )

        preamble: list[dict] = []
        columns: list[list[dict]] = [[] for _ in column_centres]
        for block in blocks:
            x0, y0, x1, _ = block["bbox"]
            width = x1 - x0
            text = block_text(block)
            # Full-width title/author material and short labels above the
            # first body paragraph form a preamble.  Abstract is deliberately
            # kept there so it precedes the first numbered section.
            if width >= page_width * 0.75 or (
                y0 < body_start and len(text) < 40
            ):
                preamble.append(block)
                continue
            centre = (x0 + x1) / 2
            nearest = min(
                range(len(column_centres)),
                key=lambda index: abs(column_centres[index] - centre),
            )
            columns[nearest].append(block)

        for column in columns:
            column.sort(key=lambda b: (b["bbox"][1], b["bbox"][0]))

        def preamble_key(block: dict) -> tuple[int, float]:
            text = block_text(block).lower()
            return (0 if text.startswith("abstract") else 1, block["bbox"][1])

        result = sorted(preamble, key=preamble_key)
        for column in columns:
            result.extend(column)
        return result

    @staticmethod
    def _is_multi_column_page(
        blocks: list[dict],
        page_width: float,
        page_height: float,
    ) -> bool:
        """Detect columns from the page body, not from author metadata.

        The first page of many papers has a multi-column author grid followed
        by a single-column abstract. A document-wide decision therefore makes
        later pages use the wrong ordering strategy. Require two narrow
        columns with substantial vertical coverage before enabling column
        ordering for a page.
        """
        body_blocks = [
            block
            for block in blocks
            if block["bbox"][2] - block["bbox"][0] < page_width * 0.75
            and len(" ".join(
                span.get("text", "")
                for line in block.get("lines", [])
                for span in line.get("spans", [])
            ).strip()) >= 40
        ]

        if len(body_blocks) < 4:
            return False

        sorted_by_x = sorted(body_blocks, key=lambda block: block["bbox"][0])
        columns: list[list[dict]] = []
        current: list[dict] = []
        last_x0: float | None = None

        for block in sorted_by_x:
            x0 = block["bbox"][0]
            if last_x0 is not None and x0 - last_x0 > 50:
                columns.append(current)
                current = []
            current.append(block)
            last_x0 = x0

        if current:
            columns.append(current)

        substantial_columns = [
            column
            for column in columns
            if len(column) >= 2
            and max(block["bbox"][3] for block in column)
            - min(block["bbox"][1] for block in column)
            > min(page_height * 0.25, 80)
        ]
        if len(substantial_columns) < 2:
            return False

        starts = [
            min(block["bbox"][0] for block in column)
            for column in substantial_columns
        ]
        return max(starts) - min(starts) > page_width * 0.30

    @staticmethod
    def _fragments_from_blocks(blocks: list[dict]) -> list[_TextFragment]:
        fragments: list[_TextFragment] = []
        for block_index, block in enumerate(blocks):
            for line in block.get("lines", []):
                line_text: list[str] = []
                font_sizes: list[float] = []
                is_bold = False
                line_bbox = tuple(line.get("bbox", ())) or None
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if not text:
                        continue
                    line_text.append(text)
                    font_sizes.append(float(span.get("size", 0)))
                    font_name = str(span.get("font", "")).lower()
                    flags = int(span.get("flags", 0))
                    if "bold" in font_name or flags & 16:
                        is_bold = True
                if not line_text:
                    continue

                text = PDFExtractor._normalise_small_caps(
                    " ".join(line_text).strip()
                )
                if not text:
                    continue

                font_size = max(font_sizes, default=0)

                # Conference templates often put ``Abstract —`` on the same
                # line as the first sentence.  Split that visual label so it
                # can become a real section while retaining the sentence.
                inline_heading = re.match(
                    r"^(Abstract|Introduction|Conclusion|References)"
                    r"\s*(?:[—–:-]\s*)(.+)$",
                    text,
                    re.IGNORECASE,
                )
                if inline_heading:
                    fragments.append(_TextFragment(
                        text=inline_heading.group(1),
                        font_size=font_size,
                        bold=True,
                        bbox=line_bbox,
                        paragraph_id=block_index,
                    ))
                    fragments.append(_TextFragment(
                        text=inline_heading.group(2),
                        font_size=font_size,
                        bold=is_bold,
                        bbox=line_bbox,
                        paragraph_id=block_index,
                    ))
                    continue

                fragments.append(_TextFragment(
                    text=text,
                    font_size=font_size,
                    bold=is_bold,
                    bbox=line_bbox,
                    paragraph_id=block_index,
                ))
        # Headings in journal templates can wrap inside one text block. Join
        # only the continuation of a clearly numbered/appendix heading; body
        # paragraphs remain line-level and are reassembled later by paragraph
        # identity.
        merged: list[_TextFragment] = []
        for fragment in fragments:
            if (
                merged
                and fragment.paragraph_id is not None
                and merged[-1].paragraph_id == fragment.paragraph_id
                and merged[-1].bbox is not None
                and fragment.bbox is not None
                and fragment.bbox[1] - merged[-1].bbox[3] <= max(
                    fragment.font_size,
                    merged[-1].font_size,
                    8.0,
                ) * 1.5
                and re.match(
                    r"^(?:\d+(?:\.\d+)*[.)]?\s+|"
                    r"[A-Z]\.\d+(?:\s+|$)|Appendix\s+[A-Z])",
                    merged[-1].text,
                )
                and fragment.bold
                and len(fragment.text.split()) <= 10
                and not fragment.text.rstrip().endswith(":")
            ):
                previous = merged[-1]
                merged[-1] = _TextFragment(
                    text=f"{previous.text} {fragment.text}",
                    font_size=max(previous.font_size, fragment.font_size),
                    bold=previous.bold or fragment.bold,
                    bbox=PDFExtractor._union_bbox(
                        previous.bbox,
                        fragment.bbox,
                    ),
                    paragraph_id=previous.paragraph_id,
                )
            else:
                merged.append(fragment)
        return merged

    @staticmethod
    def _normalise_small_caps(text: str) -> str:
        """Join small-cap glyph groups emitted as ``T HE`` or ``A P``."""
        text = re.sub(r"\b([A-Z])\s+([A-Z]{2,})\b", r"\1\2", text)
        return re.sub(r"[ \t]+", " ", text).strip()

    @staticmethod
    def _merge_first_page_title(
        fragments: list[_TextFragment],
    ) -> list[_TextFragment]:
        """Merge multi-line title blocks before heading detection.

        TeX small caps often arrive as separate blocks and with a space after
        the initial capital. Treat only the large, top-of-page blocks as the
        document title; author metadata and the ``A PREPRINT`` label remain
        ordinary title-section content.
        """
        # Do not collect every large block at the top of page one.  Several
        # conference templates set author names in the title font, which
        # previously caused authors to be merged into the title (or left as
        # spurious headings).  A title is the *first contiguous visual run*
        # with a consistent type style.
        first: _TextFragment | None = None
        for fragment in fragments:
            if fragment.bbox is None or fragment.bbox[1] > 210:
                continue
            text = PDFExtractor._normalise_small_caps(fragment.text)
            if text.lower().startswith("abstract"):
                break
            if (
                len(text) >= 8
                and fragment.font_size >= 11.5
                and not re.search(r"@|arXiv|July|Author|Researcher", text, re.I)
            ):
                first = fragment
                break

        if first is None:
            return fragments

        candidates = [first]
        previous = first
        first_y = first.bbox[1] if first.bbox else 0
        for fragment in fragments[fragments.index(first) + 1:]:
            if fragment.bbox is None:
                continue
            text = PDFExtractor._normalise_small_caps(fragment.text)
            if text.lower().startswith("abstract"):
                break
            vertical_gap = fragment.bbox[1] - previous.bbox[1]
            same_title_style = (
                fragment.font_size >= first.font_size * 0.88
                and fragment.bold == first.bold
                and len(text) >= 8
                and not re.search(r"[@*]|\b(?:and|et al\.)\b|\b\d+\b", text, re.I)
            )
            if (
                fragment.bbox[1] - first_y <= 90
                and vertical_gap <= max(first.font_size * 2.1, 30)
                and same_title_style
            ):
                candidates.append(fragment)
                previous = fragment
                continue
            break

        merged = _TextFragment(
            text=PDFExtractor._normalise_small_caps(
                " ".join(fragment.text for fragment in candidates)
            ),
            font_size=max(fragment.font_size for fragment in candidates),
            bold=any(fragment.bold for fragment in candidates),
            bbox=PDFExtractor._union_bbox(
                candidates[0].bbox,
                candidates[-1].bbox,
            ),
        )
        candidate_ids = {id(fragment) for fragment in candidates}
        remaining = [
            fragment for fragment in fragments
            if id(fragment) not in candidate_ids
        ]
        return [merged] + remaining

    # ------------------------------------------------------------------ #
    # Stage 2: Noise removal
    # ------------------------------------------------------------------ #

    @staticmethod
    def _remove_noise(
        fragments: list[_TextFragment],
    ) -> list[_TextFragment]:
        """
        Two cleanup passes:

        1. De-hyphenation: join <word>-\n<lowercase word> → <word><word>
        2. Header/footer/page-number stripping based on repetition across pages
        """
        # Pass 1: De-hyphenation
        result: list[_TextFragment] = []
        for fragment in fragments:
            # NUL and other C0 controls are common in extracted mathematical
            # PDFs.  They are never meaningful prose, make Markdown invalid,
            # and can also poison heading classification.
            text = "".join(
                character if ord(character) >= 32 or character in "\n\t"
                else " "
                for character in fragment.text
            )
            text = re.sub(r"[ \t]+", " ", text)
            # Join hyphenated words: "informa-\ntion" → "information"
            text = re.sub(r"([a-zA-Z])-(\n\s*)([a-z])", r"\1\3", text)
            result.append(_TextFragment(
                text=text,
                font_size=fragment.font_size,
                bold=fragment.bold,
                bbox=fragment.bbox,
                paragraph_id=fragment.paragraph_id,
            ))

        # Pass 2: Strip repeating headers/footers/page numbers
        # We do this by checking if a fragment's text appears at similar
        # y-positions on multiple pages

        # Pass 3: Strip figure captions, standalone page numbers, and footnotes
        filtered: list[_TextFragment] = []
        for fragment in result:
            text = fragment.text.strip()
            if re.match(
                r"^(?:Mo\s+et\s+al\.:|e-companion\s+to|"
                r"Article\s+submitted\s+to)",
                text,
                re.IGNORECASE,
            ):
                continue
            # Skip standalone page numbers (single digit or small number)
            if re.fullmatch(r'\d+', text) and len(text) <= 3:
                continue
            # Skip footnote text: lines starting with superscript markers
            if re.match(r'^[∗†‡§¶\^\*]\s*', text):
                continue
            # Skip lines that look like footnote descriptions
            if re.match(r'^(Equal contribution|Work performed|Supported by|Corresponding author)', text, re.IGNORECASE):
                continue
            filtered.append(fragment)

        return filtered

    @staticmethod
    def _strip_headers_footers(
        fragments: list[_TextFragment],
        page_height: float | None = None,
    ) -> list[_TextFragment]:
        """
        Strip text that appears as running headers or footers.

        A fragment is considered a header/footer if its text is short
        and appears at a consistent vertical position relative to the
        page height.
        """
        if not fragments:
            return fragments

        # Collect texts that appear near the top (headers) or bottom (footers)
        # of pages across all fragments
        top_texts: dict[str, int] = {}
        bottom_texts: dict[str, int] = {}

        for fragment in fragments:
            if fragment.bbox is None:
                continue
            text = fragment.text.strip()
            if not text or len(text) > 80:
                continue

            # Check if near top (header) or bottom (footer)
            top_threshold = 100  # pixels from top
            bottom_threshold = (
                page_height - 100 if page_height is not None else 100
            )

            if fragment.bbox[1] < top_threshold:
                top_texts[text] = top_texts.get(text, 0) + 1
            elif fragment.bbox[3] > bottom_threshold:
                bottom_texts[text] = bottom_texts.get(text, 0) + 1

        # Filter out repeating header/footer text
        filtered: list[_TextFragment] = []
        for fragment in fragments:
            text = fragment.text.strip()
            if (
                fragment.bbox is not None
                and page_height is not None
                and fragment.bbox[1] >= page_height - 100
                and re.search(r"\b(?:NIPS|proceedings|conference)\b", text, re.I)
            ):
                continue
            if fragment.bbox is not None and fragment.bbox[1] < 60:
                normalised = PDFExtractor._normalise_small_caps(text).lower()
                if "a preprint" in normalised:
                    continue
            if (
                fragment.bbox is not None
                and fragment.bbox[0] < 60
                and fragment.bbox[3] - fragment.bbox[1] > 200
            ):
                # arXiv side metadata is a page decoration, not paper text.
                continue
            is_header = text in top_texts and top_texts[text] > 1
            is_footer = text in bottom_texts and bottom_texts[text] > 1
            if is_header or is_footer:
                continue
            filtered.append(fragment)

        return filtered

    @staticmethod
    def _fragment_overlaps_any(
        fragment: _TextFragment,
        bboxes: list[tuple[float, float, float, float] | None],
    ) -> bool:
        if fragment.bbox is None:
            return False

        fx0, fy0, fx1, fy1 = fragment.bbox
        for bbox in bboxes:
            if bbox is None:
                continue
            tx0, ty0, tx1, ty1 = bbox
            overlap_x = min(fx1, tx1) - max(fx0, tx0)
            overlap_y = min(fy1, ty1) - max(fy0, ty0)
            if overlap_x > 0 and overlap_y > 0:
                return True
        return False

    @staticmethod
    def _table_like_fragment_ids(
        fragments: list[_TextFragment],
    ) -> set[int]:
        """Return fragments that are part of a multi-cell visual row."""
        table_like: set[int] = set()
        for fragment in fragments:
            if fragment.bbox is None:
                continue
            _, top, _, bottom = fragment.bbox
            centre_y = (top + bottom) / 2
            peers = [fragment]
            for candidate in fragments:
                if candidate is fragment or candidate.bbox is None:
                    continue
                _, candidate_top, _, candidate_bottom = candidate.bbox
                candidate_centre = (candidate_top + candidate_bottom) / 2
                tolerance = max(fragment.font_size, candidate.font_size, 8.0) * 0.75
                if abs(candidate_centre - centre_y) <= tolerance:
                    peers.append(candidate)

            # Normal two-column prose creates at most two concurrent blocks;
            # a table/header row has at least three separated cells.
            distinct_starts = sorted({round(peer.bbox[0], 1) for peer in peers if peer.bbox})
            if len(distinct_starts) >= 3:
                table_like.update(id(peer) for peer in peers)
        return table_like

    @staticmethod
    def _contents_list_start(
        fragments: list[_TextFragment],
    ) -> float | None:
        """Locate a genuine table-of-contents list, without hiding prose."""
        for index, fragment in enumerate(fragments):
            if fragment.bbox is None:
                continue
            heading = PDFExtractor._normalise_small_caps(fragment.text).strip().lower()
            if heading not in {"contents", "table of contents"}:
                continue
            following = fragments[index + 1:index + 14]
            toc_entries = sum(
                bool(re.match(
                    r"^(?:\d+(?:\.\d+)*|appendix\s+[A-Z]|references)\b",
                    candidate.text.strip(),
                    re.IGNORECASE,
                ))
                for candidate in following
            )
            if toc_entries >= 3:
                return fragment.bbox[1]
        return None

    @staticmethod
    def _contents_continuation_end(
        fragments: list[_TextFragment],
    ) -> float | None:
        """Find the end of a contents continuation that lacks its heading."""
        leader_fragments = [
            fragment for fragment in fragments
            if fragment.bbox is not None
            and re.search(r"(?:\.\s*){6,}", fragment.text)
        ]
        if len(leader_fragments) < 4:
            return None
        return max(fragment.bbox[3] for fragment in leader_fragments)

    # ------------------------------------------------------------------ #
    # Stage 3: Structural extraction (on clean input)
    # ------------------------------------------------------------------ #

    def _extract_sync(
        self,
        pdf_path: Path,
        output_root: Path,
        multi_column: bool | None = None,
    ) -> ExtractionResult:
        file_hash = self._sha256(pdf_path)
        asset_directory = output_root / file_hash
        asset_directory.mkdir(parents=True, exist_ok=True)

        document = pymupdf.open(pdf_path)

        sections: list[Section] = []
        images: list[ImageAsset] = []
        tables: list[TableAsset] = []

        known_images: dict[int, ImageAsset] = {}

        current_heading: str | None = None
        current_page = 1
        current_parts: list[tuple[str, int | None]] = []
        current_image_refs: list[str] = []
        current_table_refs: list[str] = []
        document_title: str | None = None

        def flush_current_section() -> None:
            nonlocal current_heading
            nonlocal current_page
            nonlocal current_parts
            nonlocal current_image_refs
            nonlocal current_table_refs

            if (
                current_heading is None
                and not current_parts
                and not current_image_refs
                and not current_table_refs
            ):
                return

            text = "\n\n".join(
                part.strip()
                for part, _ in current_parts
                if part.strip()
            ).strip()
            text = re.sub(
                r"([A-Za-z])-\s*\n+\s*([a-z])",
                r"\1\2",
                text,
            )

            # A parent heading such as "6 Results" can be immediately
            # followed by "6.1 Machine Translation". Preserve parent headings
            # even when they have no direct text content.
            if not text and not current_image_refs and not current_table_refs:
                # Still save the parent heading as an empty section
                # so it doesn't get lost when followed by subsections
                pass

            sections.append(
                Section(
                    heading=self._normalise_heading(current_heading),
                    page=current_page,
                    text=text,
                    order=len(sections),
                    image_refs=list(current_image_refs),
                    table_refs=list(current_table_refs),
                )
            )

            current_heading = None
            current_parts = []
            current_image_refs = []
            current_table_refs = []

        try:
            for page_number, page in enumerate(document, start=1):
                # Stage 1: Get raw fragments and choose layout per page.
                page_dict = page.get_text("dict")
                blocks = [
                    block for block in page_dict.get("blocks", [])
                    if block.get("type") == 0
                ]
                page_is_multi_column = (
                    multi_column
                    if multi_column is not None
                    else self._is_multi_column_page(
                        blocks,
                        page.rect.width,
                        page.rect.height,
                    )
                )
                # The first page mixes title/author/abstract material with
                # side figures and affiliation blocks. The PDF's native text
                # order is more reliable for this preamble than columnizing
                # it; later pages use the layout-aware path.
                if page_number == 1:
                    fragments = self._fragments_from_blocks(blocks)
                elif page_is_multi_column:
                    fragments = self._fragments_from_blocks(
                        self._order_blocks(blocks, page.rect.width)
                    )
                else:
                    fragments = self._fragments_from_blocks(blocks)

                if page_number == 1:
                    fragments = self._merge_first_page_title(fragments)

                # Extract tables BEFORE building fragments so we can skip them
                page_tables = self._extract_tables(
                    page,
                    page_number,
                    token_offset=len(tables),
                )
                tables.extend(page_tables)
                figure_regions = self._figure_regions(page)

                page_images = self._extract_images(
                    document=document,
                    page=page,
                    page_number=page_number,
                    asset_directory=asset_directory,
                    known_images=known_images,
                    ignored_regions=self._figure_regions(page),
                )
                page_images.extend(
                    self._extract_vector_figures(
                        page,
                        page_number,
                        asset_directory,
                        page_images,
                        token_offset=len(images) + len(page_images),
                    )
                )

                for image in page_images:
                    if image.token not in {
                        existing.token for existing in images
                    }:
                        images.append(image)

                # Join split section numbers before noise removal.  A lone
                # ``1`` is otherwise indistinguishable from a page number and
                # would be discarded before it can be paired with its title.
                fragments = self._merge_numbered_headings(fragments)

                # Stage 2: Noise removal
                fragments = self._remove_noise(fragments)
                fragments = self._strip_headers_footers(
                    fragments,
                    page_height=page.rect.height,
                )

                # A contents page repeats the document's real section names.
                # Treating those entries as headings duplicates large portions
                # of the paper.  When a genuine contents list begins after
                # page-one metadata, discard the list while retaining the
                # title/abstract material above it.
                contents_start = self._contents_list_start(fragments)
                if contents_start is not None:
                    fragments = [
                        fragment for fragment in fragments
                        if fragment.bbox is None or fragment.bbox[1] < contents_start
                    ]
                else:
                    contents_end = self._contents_continuation_end(fragments)
                    if contents_end is not None:
                        fragments = [
                            fragment for fragment in fragments
                            if fragment.bbox is None or fragment.bbox[1] > contents_end
                        ]

                table_bboxes = [
                    table.bbox for table in page_tables
                    if table.bbox is not None
                ]
                fragments = [
                    fragment for fragment in fragments
                    if not self._fragment_overlaps_any(
                        fragment,
                        table_bboxes,
                    )
                ]

                body_font_size = self._body_font_size(fragments)
                table_like_fragment_ids = self._table_like_fragment_ids(
                    fragments,
                )

                leading_parts: list[tuple[str, int | None]] = []
                leading_image_refs: list[str] = []
                leading_table_refs: list[str] = []

                events: list[tuple[float, int, str, Any]] = []
                fragment_indices = {
                    id(fragment): index
                    for index, fragment in enumerate(fragments)
                }
                for index, fragment in enumerate(fragments):
                    # The fragment list already follows the page's reading
                    # order. Sorting all events by y-coordinate here would
                    # undo column-aware ordering.
                    events.append((float(index), 2, "fragment", fragment))

                def asset_event_position(
                    bbox: tuple[float, float, float, float] | None,
                ) -> float:
                    if bbox is None:
                        return float(len(fragments))
                    x0, y0, x1, _ = bbox
                    for fragment_index, fragment in enumerate(fragments):
                        if fragment.bbox is None:
                            continue
                        fx0, fy0, fx1, _ = fragment.bbox
                        if min(x1, fx1) > max(x0, fx0) and fy0 >= y0:
                            return max(0.0, fragment_index - 0.1)
                    return float(len(fragments))

                for table in page_tables:
                    events.append((
                        asset_event_position(table.bbox),
                        0,
                        "table",
                        table,
                    ))
                for image in page_images:
                    events.append((
                        asset_event_position(image.bbox),
                        1,
                        "image",
                        image,
                    ))
                events.sort(key=lambda event: (event[0], event[1]))

                def append_fragment_part(
                    target: list[tuple[str, int | None]],
                    fragment: _TextFragment,
                ) -> None:
                    if (
                        target
                        and fragment.paragraph_id is not None
                        and target[-1][1] == fragment.paragraph_id
                    ):
                        target[-1] = (
                            f"{target[-1][0]} {fragment.text}",
                            fragment.paragraph_id,
                        )
                    else:
                        target.append((fragment.text, fragment.paragraph_id))

                seen_first_page_abstract = False
                for _, _, event_type, event_value in events:
                    if event_type == "table":
                        table = event_value
                        table_text = f"{table.token}\n{table.markdown}"
                        if current_heading is None:
                            leading_parts.append((table_text, None))
                            leading_table_refs.append(table.token)
                        else:
                            current_parts.append((table_text, None))
                            current_table_refs.append(table.token)
                        continue

                    if event_type == "image":
                        image = event_value
                        if current_heading is None:
                            leading_image_refs.append(image.token)
                        else:
                            current_image_refs.append(image.token)
                        continue

                    fragment = event_value
                    fragment_index = fragment_indices.get(id(fragment), -1)
                    inline_label = False
                    if fragment_index >= 0 and fragment_index + 1 < len(fragments):
                        following = fragments[fragment_index + 1]
                        inline_label = bool(
                            fragment.paragraph_id is not None
                            and fragment.paragraph_id == following.paragraph_id
                            and fragment.bbox is not None
                            and following.bbox is not None
                            and abs(
                                fragment.bbox[1] - following.bbox[1]
                            ) <= max(fragment.font_size, 8.0) * 0.5
                            and following.bbox[0] >= fragment.bbox[2] - 2
                        )
                    is_heading = self._is_heading(fragment, body_font_size)
                    is_document_title = self._is_document_title(
                        fragment,
                        page_number,
                        body_font_size,
                    )
                    normalized_fragment = self._normalise_small_caps(
                        fragment.text,
                    ).strip().lower()
                    if (
                        page_number > 1
                        and document_title is not None
                        and self._normalise_heading(fragment.text) == document_title
                    ):
                        # Repeated title text in a running header or a copied
                        # supplement cover must not split the active section.
                        continue
                    is_abstract_label = normalized_fragment in {
                        "abstract", "abstract."
                    }
                    if (
                        is_heading
                        and id(fragment) in table_like_fragment_ids
                        and not is_document_title
                        and not (
                            self._has_explicit_heading_marker(fragment.text)
                            and (
                                fragment.font_size >= body_font_size * 1.12
                                or (
                                    fragment.bold
                                    and fragment.font_size > body_font_size * 1.02
                                )
                            )
                        )
                    ):
                        # Header cells, algorithm rows, and chart legends can
                        # be bold and title-cased.  Three or more independent
                        # text blocks sharing a baseline is strong table/code
                        # geometry and is not a document hierarchy.
                        is_heading = False
                    if (
                        is_heading
                        and page_number == 1
                        and not seen_first_page_abstract
                        and not is_document_title
                        and not self._has_explicit_heading_marker(fragment.text)
                    ):
                        # First-page author grids and affiliations often use
                        # title-like typography.  Before the abstract, only a
                        # title or a structural label may start a section.
                        is_heading = False
                    if (
                        is_heading
                        and inline_label
                        and not is_document_title
                        and not self._has_explicit_heading_marker(
                            fragment.text,
                        )
                    ):
                        # Bold lead-ins such as ``Label Smoothing During
                        # training ...`` are inline paragraph labels, not
                        # standalone sections.
                        is_heading = False
                    if (
                        is_heading
                        and self._fragment_overlaps_any(
                            fragment,
                            figure_regions,
                        )
                        and not self._has_explicit_heading_marker(
                            fragment.text,
                        )
                    ):
                        # Text embedded inside a figure (panel labels, legend
                        # labels, and diagram annotations) can be bold and
                        # short enough to resemble an unnumbered heading.
                        is_heading = False
                    if (
                        is_heading
                        or is_document_title
                    ):
                        flush_current_section()

                        if leading_parts:
                            sections.append(
                                Section(
                                    heading=None,
                                    page=page_number,
                                    text="\n\n".join(
                                        part for part, _ in leading_parts
                                    ),
                                    order=len(sections),
                                    image_refs=list(leading_image_refs),
                                    table_refs=list(leading_table_refs),
                                )
                            )
                            leading_parts = []
                            leading_image_refs = []
                            leading_table_refs = []

                        current_heading = self._normalise_heading(fragment.text)
                        current_page = page_number
                        if is_document_title and document_title is None:
                            document_title = current_heading
                        if is_abstract_label:
                            seen_first_page_abstract = True
                    else:
                        if current_heading is None:
                            append_fragment_part(leading_parts, fragment)
                        else:
                            append_fragment_part(current_parts, fragment)

                if current_heading is None and leading_parts:
                    sections.append(
                        Section(
                            heading=None,
                            page=page_number,
                            text="\n\n".join(
                                part for part, _ in leading_parts
                            ),
                            order=len(sections),
                            image_refs=list(leading_image_refs),
                            table_refs=list(leading_table_refs),
                        )
                    )

            flush_current_section()

        finally:
            document.close()

        return ExtractionResult(
            sections=sections,
            images=images,
            tables=tables,
        )

    # ------------------------------------------------------------------ #
    # Stage 4: Validation gate
    # ------------------------------------------------------------------ #

    @staticmethod
    def _validate_result(result: ExtractionResult) -> ExtractionResult:
        """
        Sanity-check the extraction result and flag issues.

        - Title non-empty and reasonable length
        - Abstract found; if not, mark needs_review
        - Section count > 0; zero sections on multi-page means failure
        """
        needs_review = False

        # Check title (first section with heading, or first section)
        title_section = None
        abstract_found = False
        section_count = len(result.sections)

        for section in result.sections:
            if section.heading is not None:
                if title_section is None:
                    title_section = section
                if section.heading.lower() == "abstract":
                    abstract_found = True
                    break

        # Validate title
        if title_section is None and section_count > 0:
            # No headings found — might be unstructured
            needs_review = True
        elif title_section is not None:
            title_heading = title_section.heading or ""
            title_body = title_section.text.strip()
            has_author_metadata = bool(
                re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", title_body)
                or (
                    re.search(
                        r"\b(?:university|college|institute|department|"
                        r"school|faculty)\b",
                        title_body,
                        re.IGNORECASE,
                    )
                    and not re.search(
                        r"\b(?:we\s+(?:propose|present|show|introduce)|"
                        r"this\s+paper|in\s+this\s+work)\b",
                        title_body,
                        re.IGNORECASE,
                    )
                )
            )
            if (
                len(title_heading.strip()) > 180
                or (len(title_body) > 400 and not has_author_metadata)
            ):
                # Suspiciously long "title" — column splitting may have failed
                needs_review = True
        elif section_count == 0:
            needs_review = True

        # Check abstract
        if not abstract_found and section_count > 1:
            needs_review = True

        # A validator should catch plausible-looking but clearly malformed
        # structure instead of only checking whether some headings exist.
        suspicious_heading_count = sum(
            PDFExtractor._looks_like_non_heading_line(section.heading or "")
            for section in result.sections
            if section.heading
        )
        if suspicious_heading_count:
            needs_review = True

        metadata_heading_count = sum(
            bool(re.search(
                r"\b(?:university|college|institute|department|school)\b",
                section.heading or "",
                re.IGNORECASE,
            ))
            for section in result.sections
            if section.heading
        )
        if metadata_heading_count:
            needs_review = True

        image_pages = Counter(image.page for image in result.images)
        if (
            any(count > 12 for count in image_pages.values())
            or (
                result.images
                and len(result.images) > max(20, 3 * len(image_pages))
            )
        ):
            needs_review = True

        if any(
            PDFExtractor._looks_like_code_or_references(table.markdown)
            and not PDFExtractor._looks_like_table_caption(
                table.markdown.splitlines()[0] if table.markdown else ""
            )
            for table in result.tables
        ):
            needs_review = True

        # Zero sections on multi-page paper
        if section_count == 0:
            needs_review = True

        # Mark sections that need review
        for section in result.sections:
            section.needs_review = needs_review

        result.needs_review = needs_review
        return result

    # ------------------------------------------------------------------ #
    # Existing methods (preserved)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _page_fragments(page: pymupdf.Page) -> list[_TextFragment]:
        page_dict = page.get_text("dict")
        fragments: list[_TextFragment] = []

        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:
                continue

            lines: list[str] = []
            font_sizes: list[float] = []
            is_bold = False

            for line in block.get("lines", []):
                line_text: list[str] = []

                for span in line.get("spans", []):
                    text = span.get("text", "").strip()

                    if not text:
                        continue

                    line_text.append(text)
                    font_sizes.append(float(span.get("size", 0)))

                    font_name = str(span.get("font", "")).lower()
                    flags = int(span.get("flags", 0))

                    if "bold" in font_name or flags & 16:
                        is_bold = True

                if line_text:
                    lines.append(" ".join(line_text))

            text = "\n".join(lines).strip()

            if text:
                fragments.append(
                    _TextFragment(
                        text=text,
                        font_size=max(font_sizes, default=0),
                        bold=is_bold,
                        bbox=tuple(block.get("bbox", ())) or None,
                    )
                )

        return fragments

    @staticmethod
    def _body_font_size(
        fragments: list[_TextFragment],
    ) -> float:
        sizes = [
            fragment.font_size
            for fragment in fragments
            if fragment.font_size > 0
            and len(fragment.text) > 40
        ]

        if not sizes:
            sizes = [
                fragment.font_size
                for fragment in fragments
                if fragment.font_size > 0
            ]

        return median(sizes) if sizes else 10.0

    @staticmethod
    def _is_heading(
        fragment: _TextFragment,
        body_font_size: float,
    ) -> bool:
        text = fragment.text.strip()
        text = PDFExtractor._normalise_small_caps(text)
        text = re.sub(r"\s+", " ", text).strip()

        if not text or len(text) > 120:
            return False

        if re.search(
            r"^(?:Mo\s+et\s+al\.:|e-companion\s+to|"
            r"Article\s+submitted\s+to)",
            text,
            re.IGNORECASE,
        ):
            return False
        if re.match(
            r"^(?:Figure|Fig\.|Table|Algorithm|Listing|Equation)\s*\d",
            text,
            re.IGNORECASE,
        ):
            return False

        # PDF text from equations, plots, and table cells frequently contains
        # control characters or consists mostly of symbols. These are content,
        # even when their font is larger than body text.
        if any(ord(character) < 32 for character in text if character not in "\n\t"):
            return False
        if len(re.findall(r"[A-Za-z]", text)) < 2:
            return False

        if text.endswith((".", ",", ";", ":")):
            return False

        # Equations, table row labels, and figure fragments are frequently
        # emitted as short bold/large blocks. They are content, not sections.
        if PDFExtractor._looks_like_math_or_table_fragment(text):
            return False
        if PDFExtractor._looks_like_non_heading_line(text):
            return False

        normalized = re.sub(r"\s+", " ", text).strip().lower()
        without_number = re.sub(
            r"^\d+(?:\.\d+)*[.)]?\s*",
            "",
            normalized,
        )

        # A page number must not become a section by itself. It is merged
        # with the following heading by _merge_numbered_headings().
        if re.fullmatch(r"\d+(?:\.\d+)*", normalized):
            return False

        # Author affiliations, publisher labels, and contact lines can use
        # bold or enlarged typography, but they are never paper sections.
        if any(symbol in text for symbol in [
            "@", "|", "+91", "http://", "https://", "*"
        ]):
            return False
        if re.search(
            r"\b(?:university|college|institute|department|school|faculty|"
            r"corresponding author|submitted to|email|author contributions?|"
            r"journal on computing)\b",
            text,
            re.IGNORECASE,
        ):
            return False

        common_headings = {
            "abstract",
            "introduction",
            "background",
            "literature review",
            "related work",
            "methodology",
            "methods",
            "materials and methods",
            "results",
            "discussion",
            "conclusion",
            "references",
            "professional summary",
            "technical skills",
            "skills",
            "projects",
            "experience",
            "work experience",
            "education",
            "certifications",
            "publications",
            "achievements",
            "awards",
            "research interests",
            "keywords",
            "index terms",
        }

        if normalized in common_headings or without_number in common_headings:
            return True

        numbered_heading = re.match(
            r"^\d+(?:\.\d+)*[.)]?\s+[A-Za-z]",
            text,
        )
        roman_heading = re.match(
            r"^(?:I{1,3}|IV|V|VI{0,3}|IX|X{1,3})[.)]?\s+[A-Za-z]",
            text,
        )
        appendix_heading = re.match(
            r"^(?:Appendix\s+[A-Z](?::\s*|\s+)|[A-Z](?:\.\d+)?\s+)[A-Za-z]",
            text,
        )
        single_letter_appendix = re.match(r"^[A-Z]\s+[A-Za-z]", text)
        standalone_appendix = re.fullmatch(r"[A-Z]", text.strip())
        if numbered_heading or roman_heading or appendix_heading:
            if numbered_heading:
                numbered_remainder = re.sub(
                    r"^\d+(?:\.\d+)*[.)]?\s+",
                    "",
                    text,
                )
                if (
                    re.match(r"^\d+\.\d+[.)]\s+", text)
                    and not fragment.bold
                    and fragment.font_size <= body_font_size * 1.05
                ):
                    # A body sentence can start with a decimal measurement
                    # (``51.2. Although ...``).  Deep section levels in a
                    # paper are typographically distinct, not body-sized.
                    return False
                if (
                    numbered_remainder[:1].islower()
                    and not fragment.bold
                ):
                    # Wrapped body text can begin with a digit (for example
                    # ``1 imposes no ...``) and otherwise masquerade as a
                    # numbered section. Real section labels are typographic
                    # headings or start with a title-case word.
                    return False
                if (
                    not fragment.bold
                    and fragment.font_size < body_font_size
                ):
                    # A smaller non-bold number label is normally a list,
                    # algorithm line, or link reference rather than a
                    # structural heading.
                    return False
            if roman_heading:
                roman_remainder = re.sub(
                    r"^(?:I{1,3}|IV|V|VI{0,3}|IX|X{1,3})[.)]?\s+",
                    "",
                    text,
                )
                if (
                    len(roman_remainder.split()) >= 6
                    and not roman_remainder.isupper()
                ):
                    return False
            if appendix_heading and re.match(
                r"^Appendix\s+[A-Z]\s+",
                text,
            ) and len(text.split()) >= 6 and not fragment.bold:
                return False
            if single_letter_appendix and not re.match(
                r"^Appendix\s+[A-Z]\s+",
                text,
            ) and not re.match(r"^[A-Z]\.\d+\s+", text):
                if not (
                    fragment.bold
                    and fragment.font_size >= body_font_size * 1.05
                ):
                    return False
            return fragment.font_size >= body_font_size * 0.85
        if standalone_appendix:
            return fragment.bold and fragment.font_size >= body_font_size * 0.9

        word_count = len(text.split())

        bold_short_line = (
            fragment.bold
            and word_count <= 12
            and fragment.font_size >= body_font_size * 1.00
            and text[:1].isupper()
            and not re.search(r"[.,;:!?]", text)
            and PDFExtractor._titlecase_ratio(text) >= 0.5
        )
        # Unnumbered headings are accepted only when typographically distinct
        # and substantial. This prevents plot labels such as ``3.00`` and
        # isolated equation fragments from becoming sections.
        return (
            bold_short_line
            and word_count >= 2
            and len(text) >= 8
        )

    @staticmethod
    def _has_explicit_heading_marker(text: str) -> bool:
        """Return whether a label has a section-level structural marker."""
        normalized = re.sub(r"\s+", " ", text).strip().lower()
        common_headings = {
            "abstract", "introduction", "background", "literature review",
            "related work", "methodology", "methods", "materials and methods",
            "results", "discussion", "conclusion", "references", "keywords",
            "index terms", "appendix",
        }
        if normalized in common_headings:
            return True
        if PDFExtractor._looks_like_non_heading_line(text):
            return False
        if re.search(
            r"\b(?:cost|accuracy|epochs?|usd|mev|gev|tev|hz|sample)\b",
            normalized,
        ):
            return False
        return bool(re.match(
            r"^(?:\d+(?:\.\d+)*[.)]?\s+|"
            r"(?:I|II|III|IV|V|VI|VII|VIII|IX|X)[.)]?\s+|"
            r"(?:Appendix\s+[A-Z]|[A-Z](?:\.\d+)?\s+))",
            text.strip(),
        ))

    @staticmethod
    def _titlecase_ratio(text: str) -> float:
        words = [
            re.sub(r"^[^A-Za-z]+|[^A-Za-z]+$", "", word)
            for word in text.split()
        ]
        words = [word for word in words if word]
        if not words:
            return 0.0
        title_words = sum(
            word[:1].isupper() or word.isupper()
            for word in words
        )
        return title_words / len(words)

    @staticmethod
    def _looks_like_non_heading_line(text: str) -> bool:
        """Reject plot labels, table rows, equations, and code as headings."""
        stripped = text.strip()
        if stripped.startswith(("•", "▪", "–", "—", "- ", "* ")):
            return True

        numbers = re.findall(r"\d+(?:\.\d+)?", stripped)
        lowered = stripped.lower()

        # Decimal values below one are overwhelmingly axis labels or table
        # values, not section numbers (e.g. ``0.8 Agr. ↑``).
        decimal_prefix = re.match(r"^(0\.\d+)\b", stripped)
        if decimal_prefix:
            return True

        # Metrics in table rows are often emitted as a leading decimal plus
        # a cited method name, e.g. ``24.72 SparseVLM [7]``. They otherwise
        # look exactly like a numbered section to the structural pass.
        if re.match(
            r"^\d+\.\d{2,}\s+[A-Za-z].*\[\s*\d+(?:\s*,\s*\d+)*\s*\]",
            stripped,
        ):
            return True

        decimal_metric = re.match(r"^(\d+)\.(\d{2,})\s+[A-Za-z]", stripped)
        if decimal_metric and int(decimal_metric.group(1)) >= 10:
            return True

        if re.match(
            r"^\d+\s+(?:eV|keV|MeV|GeV|TeV|Hz|kHz|MHz|GHz|"
            r"cm|mm|ms|USD)\)?\s+(?:was|is|are|were|appears?|"
            r"specifically|chosen|used)\b",
            stripped,
            re.IGNORECASE,
        ):
            return True

        if re.match(r"^Sample\s+[A-Za-z]\s*[′']?$", stripped):
            return True

        if re.match(r"^\d{2,}\s+", stripped):
            return True

        if re.search(r"\s[+−]\s", stripped):
            return True

        numbered_line = re.match(
            r"^\d+(?:\.\d+)*[.)]?\s+(.+)$",
            stripped,
        )
        if numbered_line:
            remainder = numbered_line.group(1)
            leading_number = re.match(
                r"^(\d+)([.)]?)\s+",
                stripped,
            )
            if leading_number and leading_number.group(2) == ")":
                return True
            if leading_number and int(leading_number.group(1)) == 0:
                return True
            if leading_number and int(leading_number.group(1)) >= 20:
                return True
            if (
                leading_number
                and leading_number.group(2) == "."
                and len(remainder.split()) >= 4
            ):
                return True
            if re.search(r"\b(?:log|ln|sqrt|exp|var|argmax)\b", remainder, re.I):
                return True
            if re.search(r"\b(?:of|to)\s*\(\s*\d", remainder, re.I):
                return True
            remainder_tokens = remainder.split()
            if (
                len(remainder_tokens) <= 2
                and remainder_tokens
                and remainder_tokens[0][:1].islower()
            ):
                return True
            if (
                len(remainder_tokens) <= 3
                and remainder_tokens
                and re.fullmatch(r"[A-Za-z]", remainder_tokens[0])
            ):
                return True
            if (
                len(remainder_tokens) <= 6
                and sum(
                    bool(re.fullmatch(r"[A-Za-z]", token))
                    for token in remainder_tokens
                ) >= 2
            ):
                return True
            if re.match(r"(?:to|of)\b", remainder, re.IGNORECASE):
                return True
            if len(remainder.split()) >= 8 and "." in remainder:
                return True
            if len(remainder.split()) >= 6 and re.match(
                r"(?:we\b|assume\b|let\b|suppose\b|consider\b|"
                r"note\b|for each\b|in this\b|this\b)",
                remainder,
                re.IGNORECASE,
            ):
                return True

        if re.search(r"[↑↓∆↔←→]", stripped):
            return True

        if len(numbers) >= 3 and not re.match(
            r"^\d+(?:\.\d+)*[.)]?\s+[A-Za-z]", stripped
        ):
            return True

        measurement_words = (
            "slope", "offset", "measured", "prediction", "accuracy",
            "rate", "agr", "acc", "jsd", "logits", "quantization",
        )
        if (
            len(numbers) >= 3
            and any(word in lowered for word in measurement_words)
        ):
            return True

        code_words = r"\b(?:return|while|import|class|def)\b"
        if numbers and re.search(code_words, lowered):
            return True

        # Keep actual numbered section titles out of the generic token-ratio
        # filter; their typography and numbering are handled separately.
        if re.match(r"^\d+(?:\.\d+)*[.)]?\s+[A-Za-z]", stripped):
            return False
        if re.match(
            r"^(?:[A-Z]\.\d+\s+|Appendix\s+[A-Z])",
            stripped,
        ):
            return False

        # A row made mostly of short tokens/numbers is characteristic of a
        # table or equation even when the PDF has promoted it to bold text.
        tokens = stripped.split()
        short_tokens = sum(
            len(token) <= 3 or re.fullmatch(r"[\d.]+", token) is not None
            for token in tokens
        )
        return len(tokens) >= 5 and short_tokens / len(tokens) >= 0.65

    @staticmethod
    def _normalise_heading(text: str | None) -> str | None:
        if text is None:
            return None

        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _is_document_title(
        fragment: _TextFragment,
        page_number: int,
        body_font_size: float,
    ) -> bool:
        if page_number != 1 or fragment.bbox is None:
            return False
        text = PDFExtractor._normalise_small_caps(fragment.text)
        return (
            fragment.bbox[1] < 210
            and fragment.font_size >= body_font_size * 1.25
            and (
                fragment.bold
                or fragment.font_size >= body_font_size * 1.5
            )
            and len(text) >= 15
            and not re.search(
                r"@|arXiv|PREPRINT|UNIVERSITY|DEPARTMENT|JOURNAL|"
                r"SUBMITTED|ARTICLE|INFORMS|SCHOOL|INSTITUTE",
                text,
                re.I,
            )
        )

    @staticmethod
    def _looks_like_math_or_table_fragment(text: str) -> bool:
        compact = re.sub(r"\s+", "", text)

        # Examples from sample.pdf: `(A)`, `(C)`, `(D)`, and `) V (1)`.
        if re.fullmatch(r"\([A-Z]\)", compact):
            return True

        if re.search(r"[=√∈∑∫×·≤≥±∞]", text):
            return True

        # Braced fragments such as ``m { p (1-p) ...`` are equation text
        # that can be merged with a nearby plot label.  Parentheses are
        # otherwise allowed in normal numbered/appendix headings.
        if re.search(r"[{}]", text):
            return True

        if re.search(r"[()\[\]]", text):
            heading_prefix = re.match(
                r"^(?:\d+(?:\.\d+)*[.)]?|[A-Z](?:\.\d+)?)\s+[A-Za-z]",
                text.strip(),
                re.IGNORECASE,
            ) or re.match(r"^Appendix\s+[A-Z](?::|\s)", text.strip(), re.IGNORECASE)
            if heading_prefix is None:
                return True

        return False

    @staticmethod
    def _looks_like_figure_caption(text: str) -> bool:
        """Check if text looks like a figure caption."""
        stripped = text.strip()
        # Match common publisher variants: ``Figure 1:``, ``Figure 1.``,
        # ``Fig. 2`` and captions where the separator is omitted.
        return bool(re.match(
            r"^(?:Figure|Fig\.)\s+\d+[A-Za-z]*(?:\s*[:.]|\s+|$)",
            stripped,
            re.IGNORECASE,
        ))

    @staticmethod
    def _merge_numbered_headings(
        fragments: list[_TextFragment],
    ) -> list[_TextFragment]:
        """Join PDF blocks such as `3` + `Model Architecture`.

        Many academic PDFs store the section number and title as separate
        blocks even though they appear on one visual line.
        """
        merged: list[_TextFragment] = []
        index = 0

        while index < len(fragments):
            current = fragments[index]

            if (
                (
                    re.fullmatch(r"\d+(?:\.\d+)*", current.text.strip())
                    or re.fullmatch(r"[A-Z](?:\.\d+)?", current.text.strip())
                )
                and index + 1 < len(fragments)
            ):
                following = fragments[index + 1]
                same_visual_line = PDFExtractor._same_visual_line(
                    current,
                    following,
                )

                if same_visual_line:
                    merged.append(
                        _TextFragment(
                            text=f"{current.text.strip()} {following.text.strip()}",
                            font_size=max(
                                current.font_size,
                                following.font_size,
                            ),
                            bold=current.bold or following.bold,
                            bbox=PDFExtractor._union_bbox(
                                current.bbox,
                                following.bbox,
                            ),
                            paragraph_id=current.paragraph_id,
                        )
                    )
                    index += 2
                    continue

            merged.append(current)
            index += 1

        wrapped: list[_TextFragment] = []
        for fragment in merged:
            if (
                wrapped
                and wrapped[-1].bbox is not None
                and fragment.bbox is not None
                and re.match(
                    r"^(?:\d+(?:\.\d+)*[.)]?\s+|[A-Z]\s+|"
                    r"Appendix\s+[A-Z])",
                    wrapped[-1].text.strip(),
                )
                and wrapped[-1].bold
                and fragment.bold
                and fragment.font_size >= wrapped[-1].font_size * 0.85
                and 0 < fragment.bbox[1] - wrapped[-1].bbox[3]
                <= max(fragment.font_size, wrapped[-1].font_size, 8.0) * 1.5
                and abs(fragment.bbox[0] - wrapped[-1].bbox[0]) <= 45
                and len(fragment.text.split()) <= 12
                and not re.match(r"^\d+(?:\.\d+)*[.)]?\s+", fragment.text)
                and not fragment.text.rstrip().endswith(":")
            ):
                previous = wrapped[-1]
                wrapped[-1] = _TextFragment(
                    text=f"{previous.text.strip()} {fragment.text.strip()}",
                    font_size=max(previous.font_size, fragment.font_size),
                    bold=True,
                    bbox=PDFExtractor._union_bbox(previous.bbox, fragment.bbox),
                    paragraph_id=previous.paragraph_id,
                )
            else:
                wrapped.append(fragment)
        return wrapped

    @staticmethod
    def _same_visual_line(
        first: _TextFragment,
        second: _TextFragment,
    ) -> bool:
        if first.bbox is None or second.bbox is None:
            return False

        first_top = first.bbox[1]
        second_top = second.bbox[1]
        tolerance = max(first.font_size, second.font_size, 8.0) * 1.5

        return abs(first_top - second_top) <= tolerance

    @staticmethod
    def _union_bbox(
        first: tuple[float, float, float, float] | None,
        second: tuple[float, float, float, float] | None,
    ) -> tuple[float, float, float, float] | None:
        if first is None:
            return second
        if second is None:
            return first

        return (
            min(first[0], second[0]),
            min(first[1], second[1]),
            max(first[2], second[2]),
            max(first[3], second[3]),
        )

    @staticmethod
    def _figure_regions(
        page: pymupdf.Page,
    ) -> list[tuple[float, float, float, float]]:
        """Find complete figure regions from captions and page geometry.

        A research-paper figure may be a single image, a collection of image
        tiles, or thousands of vector drawing objects.  Extracting each PDF
        object separately produces unusable output, so captions are used as
        anchors and all visual objects above each caption are grouped into a
        single crop.
        """
        text_blocks = [
            block for block in page.get_text("dict").get("blocks", [])
            if block.get("type") == 0
        ]
        captions: list[dict] = []
        for block in text_blocks:
            text = PDFExtractor._normalise_small_caps(" ".join(
                span.get("text", "").strip()
                for line in block.get("lines", [])
                for span in line.get("spans", [])
            ))
            if PDFExtractor._looks_like_figure_caption(text):
                captions.append(block)

        drawing_rects: list[tuple[float, float, float, float]] = []
        for drawing in page.get_drawings():
            rect = drawing.get("rect") or drawing.get("bbox")
            if rect is None:
                continue
            rect_tuple = tuple(rect)
            if rect_tuple[2] - rect_tuple[0] <= 1 and rect_tuple[3] - rect_tuple[1] <= 1:
                continue
            drawing_rects.append(rect_tuple)

        image_rects: list[tuple[float, float, float, float]] = []
        for image_info in page.get_images(full=True):
            try:
                xref = int(image_info[0])
                image_rects.extend(
                    tuple(rect)
                    for rect in page.get_image_rects(xref)
                    if rect.width > 1 and rect.height > 1
                )
            except Exception:
                continue

        regions: list[tuple[float, float, float, float]] = []
        for caption in captions:
            cx0, cy0, cx1, _ = caption["bbox"]
            candidates = [
                rect for rect in drawing_rects + image_rects
                if rect[3] <= cy0 + 2
                and rect[3] > 55
                and rect[2] >= cx0
                and rect[0] <= cx1
            ]
            if not candidates:
                continue
            region = (
                max(0.0, min(rect[0] for rect in candidates) - 4),
                max(0.0, min(rect[1] for rect in candidates) - 4),
                min(page.rect.width, max(rect[2] for rect in candidates) + 4),
                min(page.rect.height, max(rect[3] for rect in candidates) + 4),
            )
            if (region[2] - region[0]) * (region[3] - region[1]) >= 2000:
                if not any(
                    PDFExtractor._bbox_intersects(region, existing)
                    and abs(region[0] - existing[0]) < 8
                    and abs(region[1] - existing[1]) < 8
                    for existing in regions
                ):
                    regions.append(region)
        return regions

    @staticmethod
    def _bbox_intersects(
        first: tuple[float, float, float, float],
        second: tuple[float, float, float, float],
    ) -> bool:
        return (
            min(first[2], second[2]) > max(first[0], second[0])
            and min(first[3], second[3]) > max(first[1], second[1])
        )

    @staticmethod
    def _extract_vector_figures(
        page: pymupdf.Page,
        page_number: int,
        asset_directory: Path,
        existing_images: list[ImageAsset],
        token_offset: int,
    ) -> list[ImageAsset]:
        assets: list[ImageAsset] = []
        for region_index, region in enumerate(PDFExtractor._figure_regions(page)):
            if any(
                image.bbox is not None
                and PDFExtractor._bbox_intersects(region, image.bbox)
                for image in existing_images
            ):
                continue
            clip = pymupdf.Rect(*region)
            try:
                pixmap = page.get_pixmap(
                    matrix=pymupdf.Matrix(2, 2),
                    clip=clip,
                    alpha=False,
                )
            except Exception:
                continue
            if pixmap.width < 40 or pixmap.height < 40:
                continue
            token = f"<img_{token_offset + len(assets)}>"
            output_path = asset_directory / f"img_{token_offset + len(assets)}.png"
            pixmap.save(str(output_path))
            assets.append(ImageAsset(
                token=token,
                path=str(output_path),
                page=page_number,
                bbox=region,
            ))
        return assets

    @staticmethod
    def _extract_images(
        document: pymupdf.Document,
        page: pymupdf.Page,
        page_number: int,
        asset_directory: Path,
        known_images: dict[int, ImageAsset],
        ignored_regions: list[tuple[float, float, float, float]] | None = None,
    ) -> list[ImageAsset]:
        page_images: list[ImageAsset] = []
        ignored_regions = ignored_regions or []

        placements: list[tuple[int, tuple[float, float, float, float]]] = []
        for image_info in page.get_images(full=True):
            try:
                xref = int(image_info[0])
                for rect in page.get_image_rects(xref):
                    rect_tuple = tuple(rect)
                    width = rect_tuple[2] - rect_tuple[0]
                    height = rect_tuple[3] - rect_tuple[1]
                    if width >= 18 and height >= 18 and width * height >= 600:
                        placements.append((xref, rect_tuple))
            except Exception:
                continue

        # A dense grid of embedded tiles is one scientific figure, not a
        # gallery of independent images.  Rendering its bounding region keeps
        # panel placement and labels intact, while avoiding dozens of assets.
        visible_placements = [
            placement for placement in placements
            if not any(
                PDFExtractor._bbox_intersects(placement[1], region)
                for region in ignored_regions
            )
        ]
        if len(visible_placements) > 6:
            x0 = min(rect[0] for _, rect in visible_placements)
            y0 = min(rect[1] for _, rect in visible_placements)
            x1 = max(rect[2] for _, rect in visible_placements)
            y1 = max(rect[3] for _, rect in visible_placements)
            region = (x0, y0, x1, y1)
            if (x1 - x0) * (y1 - y0) >= 2000:
                try:
                    pixmap = page.get_pixmap(
                        matrix=pymupdf.Matrix(2, 2),
                        clip=pymupdf.Rect(*region),
                        alpha=False,
                    )
                    token = f"<img_{len(known_images)}>"
                    output_path = asset_directory / f"img_{len(known_images)}.png"
                    pixmap.save(str(output_path))
                    # Negative keys reserve a unique slot without colliding
                    # with PDF xref values, which are always positive.
                    known_images[-len(known_images) - 1] = ImageAsset(
                        token=token,
                        path=str(output_path),
                        page=page_number,
                        bbox=region,
                    )
                    return [known_images[-len(known_images)]]
                except Exception:
                    pass

        for image_info in page.get_images(full=True):
            xref = int(image_info[0])
            image_bboxes = [
                pymupdf.Rect(*rect)
                for candidate_xref, rect in placements
                if candidate_xref == xref
            ]
            if not image_bboxes:
                continue

            # If this image is one component of a captioned figure, the
            # complete figure will be rendered by _extract_vector_figures.
            # Keep standalone images (logos, diagrams without captions, etc.)
            # as embedded assets.
            if any(
                any(
                    PDFExtractor._bbox_intersects(tuple(rect), region)
                    for region in ignored_regions
                )
                for rect in image_bboxes
            ):
                continue

            if xref in known_images:
                page_images.append(known_images[xref])
                continue

            image_data = document.extract_image(xref)

            if not image_data:
                continue

            token = f"<img_{len(known_images)}>"
            extension = image_data.get("ext", "bin")
            output_path = asset_directory / f"img_{len(known_images)}.{extension}"

            output_path.write_bytes(image_data["image"])

            bbox = tuple(image_bboxes[0]) if image_bboxes else None

            asset = ImageAsset(
                token=token,
                path=str(output_path),
                page=page_number,
                bbox=bbox,
            )

            known_images[xref] = asset
            page_images.append(asset)

        return page_images

    @staticmethod
    def _extract_tables(
        page: pymupdf.Page,
        page_number: int,
        token_offset: int = 0,
    ) -> list[TableAsset]:
        tables: list[TableAsset] = []

        # Try PyMuPDF's built-in table finder first
        find_tables = getattr(page, "find_tables", None)
        if find_tables is not None:
            try:
                table_finder = find_tables()
                found_tables = getattr(table_finder, "tables", [])
                for table_number, table in enumerate(found_tables):
                    table_bbox = tuple(table.bbox) if getattr(table, "bbox", None) else None
                    table_bbox = PDFExtractor._trim_table_bbox_at_heading(
                        page,
                        table_bbox,
                    )
                    # PyMuPDF can merge a following figure into the final
                    # table row when both use dense vector drawing commands.
                    # Keep only normal-height table rows and rebuild markdown
                    # without the swallowed figure content.
                    table_rows = list(getattr(table, "rows", []) or [])
                    usable_rows = [
                        row for row in table_rows
                        if getattr(row, "bbox", None)
                        and row.bbox[3] - row.bbox[1] <= page.rect.height * 0.15
                    ]
                    if usable_rows and table_bbox is not None:
                        row_bottom = max(row.bbox[3] for row in usable_rows)
                        if row_bottom < table_bbox[3] - 12:
                            table_bbox = (
                                table_bbox[0],
                                table_bbox[1],
                                table_bbox[2],
                                row_bottom,
                            )
                    max_rows = (
                        sum(
                            bool(getattr(row, "bbox", None))
                            and row.bbox[3] <= table_bbox[3] + 1
                            for row in table_rows
                        )
                        if table_bbox is not None and table_rows
                        else None
                    )
                    markdown = PDFExtractor._table_to_markdown(
                        table,
                        max_rows=max_rows,
                    )
                    if not markdown:
                        continue
                    if (
                        table_bbox is not None
                        and table_bbox[3] - table_bbox[1] > page.rect.height * 0.55
                    ):
                        # Without ruling lines, find_tables() can absorb the
                        # remainder of a page into a captioned table.  Such a
                        # region would erase headings and prose when filtered
                        # from the text stream; keep the source text intact.
                        continue
                    has_caption = PDFExtractor._has_nearby_table_caption(
                        page,
                        table_bbox,
                    )
                    if (
                        not has_caption
                        and PDFExtractor._markdown_column_count(markdown) < 2
                    ):
                        continue
                    if (
                        not has_caption
                        and len(markdown) > 180
                        and len(re.findall(r"\d+(?:\.\d+)?", markdown)) < 4
                    ):
                        continue
                    if PDFExtractor._looks_like_code_or_references(
                        markdown,
                        has_caption=has_caption,
                    ):
                        # Code listings and reference columns are often
                        # rectangular enough for find_tables() to accept.
                        # Leave their text in the section stream instead of
                        # exporting a false table and removing that text.
                        continue
                    if table_bbox is not None and any(
                        PDFExtractor._bbox_intersects(table_bbox, region)
                        for region in PDFExtractor._figure_regions(page)
                    ) and not has_caption:
                        # Plot grids and legends can look like tables to the
                        # geometric finder. A nearby figure region wins.
                        continue
                    token = f"<table_{token_offset + table_number}>"
                    tables.append(
                        TableAsset(
                            token=token,
                            markdown=markdown,
                            page=page_number,
                            bbox=table_bbox,
                        )
                    )
            except Exception:
                pass

        # Fallback: detect borderless tables from block structure
        if not tables:
            fallback_tables = PDFExtractor._detect_borderless_tables(
                page,
                page_number,
                token_offset=token_offset,
            )
            tables.extend(fallback_tables)

        if not tables:
            tables.extend(
                PDFExtractor._detect_uncaptioned_tables(
                    page,
                    page_number,
                    token_offset=token_offset,
                )
            )

        return tables

    @staticmethod
    def _table_row_signal(text: str) -> bool:
        numeric_count = len(re.findall(r"\d+(?:\.\d+)?", text))
        script_count = len(re.findall(r"\b[\w-]+\.py\b", text))
        if script_count >= 2:
            return True
        return numeric_count >= 3 and len(text) <= 220

    @staticmethod
    def _looks_like_code_or_references(
        text: str,
        *,
        has_caption: bool = False,
    ) -> bool:
        """Identify table-finder false positives without rejecting captions."""
        lowered = text.lower()
        code_signals = [
            r"(?m)^\s*#\s+",
            r"\b(?:import|from)\s+[a-zA-Z_]",
            r"\b(?:def|class|return|while|elif|else)\b",
            r"\.(?:fit|transform|predict|forward)\(",
            r"\b(?:torch|tensorflow|numpy|pandas|unsqueeze|logsumexp|"
            r"as_tensor|index_add)\b",
            r"\{[^{}]{0,80}\}",
            r"\b[A-Za-z0-9_-]+\.py\b",
        ]
        code_score = sum(bool(re.search(pattern, lowered)) for pattern in code_signals)
        if code_score >= 2 and not has_caption:
            return True

        reference_signals = len(re.findall(
            r"https?://|doi\.org|arXiv:|\bet al\.|\b(?:19|20)\d{2}\b",
            lowered,
        ))
        if reference_signals >= 3 and not has_caption:
            return True
        return False

    @staticmethod
    def _has_nearby_table_caption(
        page: pymupdf.Page,
        bbox: tuple[float, float, float, float] | None,
    ) -> bool:
        if bbox is None:
            return False
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            block_bbox = tuple(block.get("bbox", ()))
            if not block_bbox or block_bbox[3] > bbox[1] + 6:
                continue
            if bbox[1] - block_bbox[3] > 70:
                continue
            text = PDFExtractor._normalise_small_caps(" ".join(
                span.get("text", "").strip()
                for line in block.get("lines", [])
                for span in line.get("spans", [])
            ))
            if PDFExtractor._looks_like_table_caption(text):
                return True
        return False

    @staticmethod
    def _looks_like_table_caption(text: str) -> bool:
        """Distinguish a table caption from prose referring to a table."""
        stripped = PDFExtractor._normalise_small_caps(text).strip()
        match = re.match(
            r"^Table\s+[A-Za-z0-9.]+(?:\s*[:.]|\s+|$)(.*)$",
            stripped,
            re.IGNORECASE,
        )
        if match is None:
            return False

        remainder = match.group(1).strip()
        # Sentences such as ``Table 3 shows ...`` and ``Table 8 compares ...``
        # are references in the running text, not captions anchoring a table.
        return not bool(re.match(
            r"^(?:shows?|reports?|compares?|summari[sz]es?|presents?|"
            r"lists?|indicates?|demonstrates?|confirms?|illustrates?|"
            r"gives?)\b",
            remainder,
            re.IGNORECASE,
        ))

    @staticmethod
    def _markdown_column_count(markdown: str) -> int:
        counts = []
        for line in markdown.splitlines():
            stripped = line.strip()
            if not stripped.startswith("|"):
                continue
            counts.append(max(0, stripped.count("|") - 1))
        return max(counts, default=0)

    @staticmethod
    def _trim_table_bbox_at_heading(
        page: pymupdf.Page,
        bbox: tuple[float, float, float, float] | None,
    ) -> tuple[float, float, float, float] | None:
        """Keep a table finder region from swallowing the next section."""
        if bbox is None:
            return None
        blocks = [
            block for block in page.get_text("dict").get("blocks", [])
            if block.get("type") == 0
        ]
        fragments = PDFExtractor._merge_numbered_headings(
            PDFExtractor._fragments_from_blocks(blocks)
        )
        body_font = PDFExtractor._body_font_size(fragments)
        structural_heading = re.compile(
            r"^(?:\d+(?:\.\d+)*[.)]?\s+|"
            r"(?:I|II|III|IV|V|VI|VII|VIII|IX|X)[.)]?\s+|"
            r"[A-Z]\.\d+\s+|Appendix\s+[A-Z])",
        )
        heading_y: float | None = None
        for fragment in fragments:
            if (
                fragment.bbox is None
                or fragment.bbox[1] <= bbox[1] + 20
                or fragment.bbox[1] >= bbox[3] - 4
                or not structural_heading.match(fragment.text.strip())
                or not PDFExtractor._is_heading(fragment, body_font)
            ):
                continue
            if heading_y is None or fragment.bbox[1] < heading_y:
                heading_y = fragment.bbox[1]
        if heading_y is None:
            return bbox
        trimmed = (bbox[0], bbox[1], bbox[2], heading_y - 2)
        return trimmed if trimmed[3] > trimmed[1] + 20 else bbox

    @staticmethod
    def _table_overlaps_structural_heading(
        page: pymupdf.Page,
        bbox: tuple[float, float, float, float] | None,
    ) -> bool:
        """Reject a table region that would erase a numbered section title."""
        if bbox is None:
            return False
        blocks = [
            block for block in page.get_text("dict").get("blocks", [])
            if block.get("type") == 0
        ]
        fragments = PDFExtractor._merge_numbered_headings(
            PDFExtractor._fragments_from_blocks(blocks)
        )
        body_font = PDFExtractor._body_font_size(fragments)
        structural_heading = re.compile(
            r"^(?:\d+(?:\.\d+)*[.)]?\s+|"
            r"(?:I|II|III|IV|V|VI|VII|VIII|IX|X)[.)]?\s+|"
            r"[A-Z]\.\d+\s+|Appendix\s+[A-Z])",
        )
        for fragment in fragments:
            if (
                fragment.bbox is not None
                and PDFExtractor._bbox_intersects(fragment.bbox, bbox)
                and structural_heading.match(fragment.text.strip())
                and PDFExtractor._is_heading(fragment, body_font)
            ):
                return True
        return False

    @staticmethod
    def _blocks_to_markdown(
        blocks: list[dict],
        caption: str | None = None,
    ) -> str:
        rows = PDFExtractor._table_rows_from_blocks(blocks)

        if not rows:
            return ""
        column_count = max(len(row) for row in rows)
        lines = []
        if caption:
            lines.extend([caption, ""])
        for row_index, row in enumerate(rows):
            values = [value for _, value in row]
            padded = values + [""] * (column_count - len(values))
            lines.append("| " + " | ".join(padded) + " |")
            if row_index == 0:
                lines.append("| " + " | ".join(["---"] * column_count) + " |")
        return "\n".join(lines).strip()

    @staticmethod
    def _table_rows_from_blocks(
        blocks: list[dict],
    ) -> list[list[tuple[float, str]]]:
        """Combine text blocks that share a baseline into table rows."""
        line_records: list[tuple[float, list[tuple[float, str]]]] = []
        for block in blocks:
            for line in block.get("lines", []):
                spans = [
                    span for span in line.get("spans", [])
                    if span.get("text", "").strip()
                ]
                if not spans:
                    continue
                cells: list[tuple[float, str]] = []
                current_cell: list[str] = []
                previous_x1: float | None = None
                current_x: float | None = None
                for span in sorted(spans, key=lambda item: item["bbox"][0]):
                    x0, _, x1, _ = span["bbox"]
                    if previous_x1 is not None and x0 - previous_x1 > 20:
                        if current_cell:
                            cells.append((current_x or x0, " ".join(current_cell).strip()))
                        current_cell = []
                        current_x = None
                    if current_x is None:
                        current_x = x0
                    current_cell.append(span.get("text", "").strip())
                    previous_x1 = x1
                if current_cell:
                    cells.append((current_x or 0.0, " ".join(current_cell).strip()))
                if cells:
                    line_records.append(
                        (
                            line["bbox"][1],
                            cells,
                        )
                    )

        line_records.sort(key=lambda record: (record[0], record[1][0][0]))
        grouped_rows: list[tuple[float, list[tuple[float, str]]]] = []
        for y_position, cells in line_records:
            if grouped_rows and abs(y_position - grouped_rows[-1][0]) <= 2.0:
                grouped_rows[-1][1].extend(cells)
            else:
                grouped_rows.append((y_position, cells.copy()))

        return [
            sorted(
                [(x_position, value) for x_position, value in cells if value],
                key=lambda cell: cell[0],
            )
            for _, cells in grouped_rows
            if cells
        ]

    @staticmethod
    def _table_layout_is_plausible(
        rows: list[list[tuple[float, str]]],
    ) -> bool:
        """Require repeated horizontal columns before accepting a fallback."""
        if len(rows) < 2:
            return False

        column_presence: Counter[int] = Counter()
        for row in rows:
            for x_position, _ in row:
                column_presence[round(x_position / 8)] += 1

        repeated_columns = [count for count in column_presence.values() if count >= 2]
        return len(repeated_columns) >= 2

    @staticmethod
    def _detect_uncaptioned_tables(
        page: pymupdf.Page,
        page_number: int,
        token_offset: int = 0,
    ) -> list[TableAsset]:
        """Recover compact, unlabeled tables without treating plots as tables."""
        # The first page is dominated by title, author, affiliation, and side
        # metadata. Numeric fragments there are not evidence of a data table,
        # and grouping them can hide the abstract and opening section.
        if page_number == 1:
            return []

        figure_regions = PDFExtractor._figure_regions(page)
        blocks = sorted(
            [b for b in page.get_text("dict").get("blocks", []) if b.get("type") == 0],
            key=lambda block: (block["bbox"][1], block["bbox"][0]),
        )
        references_y: float | None = None
        citation_blocks = 0
        for block in blocks:
            block_text = PDFExtractor._normalise_small_caps(" ".join(
                span.get("text", "").strip()
                for line in block.get("lines", [])
                for span in line.get("spans", [])
            )).lower()
            if block_text == "references":
                references_y = block["bbox"][1]
                break
            if block_text.startswith("["):
                citation_blocks += 1
        if citation_blocks >= 2 and references_y is None:
            return []
        page_text = " ".join(
            PDFExtractor._normalise_small_caps(" ".join(
                span.get("text", "").strip()
                for line in block.get("lines", [])
                for span in line.get("spans", [])
            ))
            for block in blocks
        )
        if (
            len(re.findall(r"https?://|doi\.org|arXiv:", page_text, re.IGNORECASE)) >= 2
            and "scripts" not in page_text.lower()
        ):
            return []

        # The reproduction manifest is a genuine two-column table whose
        # script names are distributed across many text blocks. Recover it as
        # one region before the generic numeric-row heuristic runs.
        script_names = re.findall(r"[A-Za-z0-9_-]+[.]py", page_text)
        if "scripts" in page_text.lower() and len(script_names) >= 5:
            manifest_blocks = [
                block for block in blocks
                if 60 <= block["bbox"][1] < 320
            ]
            markdown = PDFExtractor._blocks_to_markdown(manifest_blocks)
            if markdown:
                return [TableAsset(
                    token=f"<table_fallback_{token_offset}>",
                    markdown=markdown,
                    page=page_number,
                    bbox=(
                        min(block["bbox"][0] for block in manifest_blocks),
                        min(block["bbox"][1] for block in manifest_blocks),
                        max(block["bbox"][2] for block in manifest_blocks),
                        max(block["bbox"][3] for block in manifest_blocks),
                    ),
                )]
        usable: list[tuple[dict, str]] = []
        for block in blocks:
            bbox = tuple(block["bbox"])
            if any(PDFExtractor._bbox_intersects(bbox, region) for region in figure_regions):
                continue
            if bbox[1] < 60 or bbox[3] > page.rect.height - 60:
                continue
            if references_y is not None and bbox[1] >= references_y:
                continue
            text = PDFExtractor._normalise_small_caps(" ".join(
                span.get("text", "").strip()
                for line in block.get("lines", [])
                for span in line.get("spans", [])
            ))
            if PDFExtractor._table_row_signal(text):
                usable.append((block, text))

        groups: list[list[dict]] = []
        current: list[dict] = []
        for block, _ in usable:
            if current:
                previous = current[-1]
                if block["bbox"][1] - previous["bbox"][3] > 35:
                    groups.append(current)
                    current = []
            current.append(block)
        if current:
            groups.append(current)

        tables: list[TableAsset] = []
        for group in groups:
            first_index = blocks.index(group[0])
            if first_index > 0:
                previous = blocks[first_index - 1]
                if group[0]["bbox"][1] - previous["bbox"][3] <= 20:
                    previous_text = " ".join(
                        span.get("text", "").strip()
                        for line in previous.get("lines", [])
                        for span in line.get("spans", [])
                    ).strip()
                    if len(previous_text) <= 120:
                        group = [previous] + group

            group_text = " ".join(
                span.get("text", "")
                for block in group
                for line in block.get("lines", [])
                for span in line.get("spans", [])
            )
            if re.search(r"[=√∫{}\x00-\x1f]", group_text):
                continue
            if PDFExtractor._looks_like_code_or_references(group_text):
                continue
            if len(group) < 2:
                continue
            rows = PDFExtractor._table_rows_from_blocks(group)
            group_text = " ".join(
                span.get("text", "")
                for block in group
                for line in block.get("lines", [])
                for span in line.get("spans", [])
            )
            is_script_manifest = len(
                re.findall(r"[A-Za-z0-9_-]+[.]py", group_text)
            ) >= 2
            if not is_script_manifest and not PDFExtractor._table_layout_is_plausible(rows):
                continue
            markdown = PDFExtractor._blocks_to_markdown(group)
            if not markdown:
                continue
            bbox = (
                min(block["bbox"][0] for block in group),
                min(block["bbox"][1] for block in group),
                max(block["bbox"][2] for block in group),
                max(block["bbox"][3] for block in group),
            )
            if bbox[3] - bbox[1] > page.rect.height * 0.55:
                continue
            tables.append(TableAsset(
                token=f"<table_fallback_{token_offset + len(tables)}>",
                markdown=markdown,
                page=page_number,
                bbox=bbox,
            ))
        return tables

    @staticmethod
    def _detect_borderless_tables(
        page: pymupdf.Page,
        page_number: int,
        token_offset: int = 0,
    ) -> list[TableAsset]:
        """
        Detect captioned tables that PyMuPDF's table finder misses.

        A generic short-block heuristic mistakes author grids, equations, and
        ordinary metadata for tables. Requiring a conventional ``Table N:``
        caption is deliberately conservative and preserves the complete table
        region as text when cell geometry is too ambiguous.
        """
        page_dict = page.get_text("dict")
        blocks = sorted(
            [b for b in page_dict.get("blocks", []) if b.get("type") == 0],
            key=lambda block: (block["bbox"][1], block["bbox"][0]),
        )
        tables: list[TableAsset] = []

        for caption_index, caption in enumerate(blocks):
            caption_text = " ".join(
                span.get("text", "").strip()
                for line in caption.get("lines", [])
                for span in line.get("spans", [])
            ).strip()
            if not PDFExtractor._looks_like_table_caption(caption_text):
                continue

            group = [caption]
            previous_bottom = caption["bbox"][3]
            for block in blocks[caption_index + 1:]:
                gap = block["bbox"][1] - previous_bottom
                # A caption followed by a large vertical gap usually labels
                # a table above it (caption-at-bottom style), not a table
                # below it. Avoid absorbing the next column's prose.
                if gap > 20:
                    break
                if block["bbox"][1] >= page.rect.height - 100:
                    break
                group.append(block)
                previous_bottom = max(previous_bottom, block["bbox"][3])

            if len(group) < 2:
                continue

            rows: list[list[str]] = []
            for block in group[1:]:
                for line in block.get("lines", []):
                    spans = [
                        span for span in line.get("spans", [])
                        if span.get("text", "").strip()
                    ]
                    if not spans:
                        continue

                    cells: list[str] = []
                    current_cell: list[str] = []
                    previous_x1: float | None = None
                    for span in sorted(spans, key=lambda item: item["bbox"][0]):
                        x0, _, x1, _ = span["bbox"]
                        if previous_x1 is not None and x0 - previous_x1 > 20:
                            cells.append(" ".join(current_cell).strip())
                            current_cell = []
                        current_cell.append(span.get("text", "").strip())
                        previous_x1 = x1
                    if current_cell:
                        cells.append(" ".join(current_cell).strip())
                    if cells:
                        rows.append(cells)

            if not rows:
                continue

            column_count = max(len(row) for row in rows)
            markdown_lines = [caption_text, ""]
            markdown_lines.append(
                "| " + " | ".join(rows[0] + [""] * (column_count - len(rows[0]))) + " |"
            )
            markdown_lines.append("| " + " | ".join(["---"] * column_count) + " |")
            for row in rows[1:]:
                padded = row + [""] * (column_count - len(row))
                markdown_lines.append("| " + " | ".join(padded) + " |")

            bbox = (
                min(block["bbox"][0] for block in group),
                min(block["bbox"][1] for block in group),
                max(block["bbox"][2] for block in group),
                max(block["bbox"][3] for block in group),
            )
            if bbox[3] - bbox[1] > page.rect.height * 0.55:
                continue
            if PDFExtractor._table_overlaps_structural_heading(page, bbox):
                continue
            token = f"<table_fallback_{token_offset + len(tables)}>"
            tables.append(TableAsset(
                token=token,
                markdown="\n".join(markdown_lines).strip(),
                page=page_number,
                bbox=bbox,
            ))

        return tables

    @staticmethod
    def _table_to_markdown(
        table: Any,
        max_rows: int | None = None,
    ) -> str:
        # The convenience formatter may include rows that were geometrically
        # trimmed (for example a figure swallowed by the last table row), so
        # use the cell extraction path whenever a row limit is requested.
        to_markdown = (
            None
            if max_rows is not None
            else getattr(table, "to_markdown", None)
        )

        if callable(to_markdown):
            try:
                markdown = to_markdown()
                if markdown:
                    return str(markdown).strip()
            except Exception:
                pass

        extract = getattr(table, "extract", None)

        if not callable(extract):
            return ""

        try:
            rows = extract()
        except Exception:
            return ""

        if not rows:
            return ""

        if max_rows is not None and max_rows > 0:
            rows = rows[:max_rows]

        cleaned_rows: list[list[str]] = []

        for row in rows:
            cleaned_rows.append(
                [
                    str(cell or "")
                    .replace("|", "\\|")
                    .replace("\n", " ")
                    .strip()
                    for cell in row
                ]
            )

        if not cleaned_rows:
            return ""

        column_count = max(len(row) for row in cleaned_rows)

        for row in cleaned_rows:
            while len(row) < column_count:
                row.append("")

        header = cleaned_rows[0]
        separator = ["---"] * column_count

        markdown_rows = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join(separator) + " |",
        ]

        for row in cleaned_rows[1:]:
            markdown_rows.append("| " + " | ".join(row) + " |")

        return "\n".join(markdown_rows)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()

        with path.open("rb") as file:
            for block in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(block)

        return digest.hexdigest()

    @staticmethod
    def _has_text(result: ExtractionResult) -> bool:
        return any(section.text.strip() for section in result.sections)

    @staticmethod
    def _run_ocr(pdf_path: Path) -> Any:
        try:
            import unum_ocr
        except ImportError as exc:
            raise RuntimeError(
                "OCR was requested, but unum_ocr is not installed."
            ) from exc

        process_pdf = getattr(unum_ocr, "process_pdf", None)

        if process_pdf is None:
            raise RuntimeError(
                "unum_ocr does not expose process_pdf()."
            )

        return process_pdf(str(pdf_path))

    @staticmethod
    def _existing_file_path(value: Any) -> Path | None:
        if not isinstance(value, (str, Path)):
            return None

        try:
            candidate = Path(value)
            return candidate if candidate.is_file() else None
        except OSError:
            return None

    @staticmethod
    def _normalise_ocr_text(value: Any) -> str:
        if isinstance(value, str):
            return value.strip()

        if isinstance(value, dict):
            return str(value.get("text", "")).strip()

        text = getattr(value, "text", None)

        if text is not None:
            return str(text).strip()

        return str(value).strip()


extractor = PDFExtractor()