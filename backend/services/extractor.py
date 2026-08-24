from __future__ import annotations

import hashlib
import re
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


@dataclass
class TableAsset:
    token: str
    markdown: str
    page: int


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
                }
                for image in self.images
            ],
            "tables": [
                {
                    "token": table.token,
                    "markdown": table.markdown,
                    "page": table.page,
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


class PDFExtractor:
    async def extract(
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
            result = self._extract_sync(
                source_path,
                Path(output_root),
                multi_column=True,
            )
        elif triage.has_text_layer:
            # Single-column: standard ordering
            result = self._extract_sync(
                source_path,
                Path(output_root),
                multi_column=False,
            )
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
                    multi_column=False,
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

        For single-column documents, this is just top-to-bottom sort.
        For multi-column documents, left column blocks come before right
        column blocks, preserving vertical order within each column.
        """
        if not blocks:
            return blocks

        mid_x = page_width / 2
        left = sorted(
            [b for b in blocks if b["bbox"][0] < mid_x],
            key=lambda b: b["bbox"][1],
        )
        right = sorted(
            [b for b in blocks if b["bbox"][0] >= mid_x],
            key=lambda b: b["bbox"][1],
        )

        # Interleave left and right columns for proper reading order
        result: list[dict] = []
        li, ri = 0, 0
        while li < len(left) and ri < len(right):
            # Pick the block that appears higher on the page
            if left[li]["bbox"][1] <= right[ri]["bbox"][1]:
                result.append(left[li])
                li += 1
            else:
                result.append(right[ri])
                ri += 1

        result.extend(left[li:])
        result.extend(right[ri:])
        return result

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
            text = fragment.text
            # Join hyphenated words: "informa-\ntion" → "information"
            text = re.sub(r"([a-zA-Z])-(\n\s*)([a-z])", r"\1\3", text)
            result.append(_TextFragment(
                text=text,
                font_size=fragment.font_size,
                bold=fragment.bold,
                bbox=fragment.bbox,
            ))

        # Pass 2: Strip repeating headers/footers/page numbers
        # We do this by checking if a fragment's text appears at similar
        # y-positions on multiple pages

        # Pass 3: Strip figure captions and standalone page numbers
        filtered: list[_TextFragment] = []
        for fragment in result:
            text = fragment.text.strip()
            # Skip figure captions: "Figure 1: ...", "Fig. 2: ...",
            # "Figure 3a: ...", etc.
            if re.match(r'^Figure \d+[a-zA-Z]*:\s*', text, re.IGNORECASE):
                continue
            if re.match(r'^Fig\.\s+\d+[a-zA-Z]*:\s*', text, re.IGNORECASE):
                continue
            # Skip standalone page numbers (single digit or small number)
            if re.fullmatch(r'\d+', text) and len(text) <= 3:
                continue
            filtered.append(fragment)

        return filtered

    @staticmethod
    def _strip_headers_footers(
        fragments: list[_TextFragment],
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
            bottom_threshold = 100  # pixels from bottom

            if fragment.bbox[1] < top_threshold:
                top_texts[text] = top_texts.get(text, 0) + 1
            elif fragment.bbox[3] > bottom_threshold:
                bottom_texts[text] = bottom_texts.get(text, 0) + 1

        # Filter out repeating header/footer text
        filtered: list[_TextFragment] = []
        for fragment in fragments:
            text = fragment.text.strip()
            is_header = text in top_texts and top_texts[text] > 1
            is_footer = text in bottom_texts and bottom_texts[text] > 1
            if is_header or is_footer:
                continue
            filtered.append(fragment)

        return filtered

    # ------------------------------------------------------------------ #
    # Stage 3: Structural extraction (on clean input)
    # ------------------------------------------------------------------ #

    def _extract_sync(
        self,
        pdf_path: Path,
        output_root: Path,
        multi_column: bool = False,
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
        current_parts: list[str] = []
        current_image_refs: list[str] = []
        current_table_refs: list[str] = []

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
                for part in current_parts
                if part.strip()
            ).strip()

            # A parent heading such as "6 Results" can be immediately
            # followed by "6.1 Machine Translation". Do not create an
            # empty database chunk for that parent heading.
            if not text and not current_image_refs and not current_table_refs:
                current_heading = None
                current_parts = []
                current_image_refs = []
                current_table_refs = []
                return

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
                # Stage 1: Get raw fragments
                raw_fragments = self._page_fragments(page)

                # Stage 1: Apply layout-correct ordering
                page_width = page.rect.width
                if multi_column:
                    page_dict = page.get_text("dict")
                    blocks = [
                        b for b in page_dict.get("blocks", [])
                        if b.get("type") == 0
                    ]
                    ordered_blocks = self._order_blocks(blocks, page_width)
                    # Rebuild fragments from ordered blocks
                    fragments: list[_TextFragment] = []
                    for block in ordered_blocks:
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
                            fragments.append(_TextFragment(
                                text=text,
                                font_size=max(font_sizes, default=0),
                                bold=is_bold,
                                bbox=tuple(block.get("bbox", ())) or None,
                            ))
                else:
                    fragments = raw_fragments

                # Stage 2: Noise removal
                fragments = self._remove_noise(fragments)
                fragments = self._strip_headers_footers(fragments)

                fragments = self._merge_numbered_headings(fragments)
                body_font_size = self._body_font_size(fragments)

                page_images = self._extract_images(
                    document=document,
                    page=page,
                    page_number=page_number,
                    asset_directory=asset_directory,
                    known_images=known_images,
                )

                for image in page_images:
                    if image.token not in {
                        existing.token for existing in images
                    }:
                        images.append(image)

                page_tables = self._extract_tables(page, page_number)
                tables.extend(page_tables)

                image_refs = [image.token for image in page_images]
                table_refs = [table.token for table in page_tables]

                table_markdown = [
                    f"{table.token}\n{table.markdown}"
                    for table in page_tables
                ]

                leading_parts: list[str] = []
                has_heading = False

                for fragment in fragments:
                    if self._is_heading(fragment, body_font_size):
                        flush_current_section()

                        if leading_parts:
                            sections.append(
                                Section(
                                    heading=None,
                                    page=page_number,
                                    text="\n\n".join(leading_parts),
                                    order=len(sections),
                                )
                            )
                            leading_parts = []

                        current_heading = self._normalise_heading(fragment.text)
                        current_page = page_number
                        has_heading = True
                    else:
                        # Skip figure captions in leading parts (they belong to
                        # the previous section's images, not as text content)
                        if current_heading is None:
                            if self._looks_like_figure_caption(fragment.text):
                                continue
                            leading_parts.append(fragment.text)
                        else:
                            current_parts.append(fragment.text)

                if has_heading:
                    current_image_refs.extend(image_refs)
                    current_table_refs.extend(table_refs)
                    current_parts.extend(table_markdown)

                elif current_heading is not None:
                    current_image_refs.extend(image_refs)
                    current_table_refs.extend(table_refs)
                    current_parts.extend(table_markdown)

                else:
                    page_parts = list(leading_parts)
                    page_parts.extend(table_markdown)
                    page_parts.extend(image_refs)

                    page_text = "\n\n".join(
                        part.strip()
                        for part in page_parts
                        if part.strip()
                    ).strip()

                    if page_text:
                        sections.append(
                            Section(
                                heading=None,
                                page=page_number,
                                text=page_text,
                                order=len(sections),
                                image_refs=image_refs,
                                table_refs=table_refs,
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
            title_text = title_section.text.strip()
            if len(title_text) > 400:
                # Suspiciously long "title" — column splitting may have failed
                needs_review = True
        elif section_count == 0:
            needs_review = True

        # Check abstract
        if not abstract_found and section_count > 1:
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

        if not text or len(text) > 120:
            return False

        if len(text.splitlines()) > 2:
            return False

        if text.endswith((".", ",", ";", ":")):
            return False

        # Equations, table row labels, and figure fragments are frequently
        # emitted as short bold/large blocks. They are content, not sections.
        if PDFExtractor._looks_like_math_or_table_fragment(text):
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

        common_headings = {
            "abstract",
            "introduction",
            "background",
            "literature review",
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
        }

        if normalized in common_headings or without_number in common_headings:
            return True

        if re.match(r"^\d+(?:\.\d+)*[.)]?\s+\S+", text):
            return True

        word_count = len(text.split())

        # All-uppercase short lines are usually section headings.
        if (
            text.isupper()
            and any(character.isalpha() for character in text)
            and word_count <= 8
        ):
            return True

        # Reject contact/project metadata lines.
        if any(symbol in text for symbol in ["@", "|", "+91", "http://", "https://"]):
            return False

        font_is_larger = fragment.font_size >= body_font_size * 1.25

        bold_short_line = (
            fragment.bold
            and word_count <= 5
            and fragment.font_size >= body_font_size * 1.10
        )

        return font_is_larger or bold_short_line

    @staticmethod
    def _normalise_heading(text: str | None) -> str | None:
        if text is None:
            return None

        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _looks_like_math_or_table_fragment(text: str) -> bool:
        compact = re.sub(r"\s+", "", text)

        # Examples from sample.pdf: `(A)`, `(C)`, `(D)`, and `) V (1)`.
        if re.fullmatch(r"\([A-Z]\)", compact):
            return True

        if re.search(r"[=√∈∑∫×·≤≥±∞]", text):
            return True

        if re.search(r"[()\[\]{}]", text) and not re.match(
            r"^\d+(?:\.\d+)*[.)]?\s+[A-Za-z]",
            text.strip(),
        ):
            return True

        return False

    @staticmethod
    def _looks_like_figure_caption(text: str) -> bool:
        """Check if text looks like a figure caption."""
        stripped = text.strip()
        # Match "Figure 1: ...", "Fig. 2: ...", "Figure 3a: ..."
        if re.match(r'^Figure \d+[a-zA-Z]*:\s*', stripped, re.IGNORECASE):
            return True
        if re.match(r'^Fig\.\s+\d+[a-zA-Z]*:\s*', stripped, re.IGNORECASE):
            return True
        return False

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
                re.fullmatch(r"\d+(?:\.\d+)*", current.text.strip())
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
                        )
                    )
                    index += 2
                    continue

            merged.append(current)
            index += 1

        return merged

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
    def _extract_images(
        document: pymupdf.Document,
        page: pymupdf.Page,
        page_number: int,
        asset_directory: Path,
        known_images: dict[int, ImageAsset],
    ) -> list[ImageAsset]:
        page_images: list[ImageAsset] = []

        for image_info in page.get_images(full=True):
            xref = int(image_info[0])

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

            asset = ImageAsset(
                token=token,
                path=str(output_path),
                page=page_number,
            )

            known_images[xref] = asset
            page_images.append(asset)

        return page_images

    @staticmethod
    def _extract_tables(
        page: pymupdf.Page,
        page_number: int,
    ) -> list[TableAsset]:
        find_tables = getattr(page, "find_tables", None)

        if find_tables is None:
            return []

        try:
            table_finder = find_tables()
            found_tables = getattr(table_finder, "tables", [])
        except Exception:
            return []

        tables: list[TableAsset] = []

        for table_number, table in enumerate(found_tables):
            markdown = PDFExtractor._table_to_markdown(table)

            if not markdown:
                continue

            token = f"<table_{table_number}>"

            tables.append(
                TableAsset(
                    token=token,
                    markdown=markdown,
                    page=page_number,
                )
            )

        return tables

    @staticmethod
    def _table_to_markdown(table: Any) -> str:
        to_markdown = getattr(table, "to_markdown", None)

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
