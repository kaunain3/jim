"""Ties the PDF extractor, embedding service, and DB together.

This is the glue that was missing: `PDFExtractor` produces sections, but
nothing yet turned those into `PapersModel` / `ChunksModel` / `EmbeddingsModel`
rows. `ingest_paper` does that in one transaction, so a paper never ends up
half-ingested (rows added, embeddings missing, or vice versa).
"""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from sqlalchemy.orm import Session

from db.models import ChunksModel, EmbeddingsModel, PapersModel
from services.embedding import EmbeddingService, embedding_service
from services.extractor import ExtractionResult, PDFExtractor


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


async def ingest_paper(
    db: Session,
    pdf_path: str | Path,
    extractor: PDFExtractor,
    embedder: EmbeddingService = embedding_service,
    title: str | None = None,
    authors: str | None = None,
    year: int | None = None,
    arxiv_id: str | None = None,
    abstract: str | None = None,
    use_ocr: bool = False,
    extraction_result: ExtractionResult | None = None,
) -> PapersModel:
    """Extract, persist, and embed a PDF.

    Pass ``extraction_result`` to reuse an already-extracted PDF (the job
    runner extracts once and hands the result here, avoiding double work).

    Raises ValueError if a paper with the same sha256 has already been
    ingested (dedup, matching the `sha256` UNIQUE constraint in the schema).
    """
    source_path = Path(pdf_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"PDF not found: {source_path}")

    sha256 = _sha256(source_path)
    existing = db.query(PapersModel).filter_by(sha256=sha256).first()
    if existing is not None:
        raise ValueError(f"Paper already ingested (id={existing.id}, sha256={sha256})")

    result: ExtractionResult
    if extraction_result is not None:
        result = extraction_result
    else:
        result = await extractor.extract(source_path, use_ocr=use_ocr)

    extractable_sections = [
        section for section in result.sections if section.text.strip()
    ]
    if not extractable_sections:
        message = "No extractable text found in PDF"
        if not use_ocr:
            message += "; enable OCR for scanned documents"
        raise ValueError(message)

    try:
        paper = PapersModel(
            title=title or source_path.stem,
            authors=authors,
            year=year,
            path=str(source_path),
            sha256=sha256,
            arxiv_id=arxiv_id,
            abstract=abstract,
        )
        db.add(paper)
        db.flush()  # assigns paper.id without committing

        chunk_rows: list[ChunksModel] = []
        for section in extractable_sections:
            chunk = ChunksModel(
                paper_id=paper.id,
                title=section.heading,
                page=section.page,
                content=section.text,
                order=section.order,
                image_refs=",".join(section.image_refs) if section.image_refs else None,
                table_refs=",".join(section.table_refs) if section.table_refs else None,
            )
            db.add(chunk)
            chunk_rows.append(chunk)
        db.flush()  # assigns chunk ids

        vectors = await asyncio.to_thread(
            embedder.embed, [chunk.content for chunk in chunk_rows]
        )
        if len(vectors) != len(chunk_rows):
            raise ValueError(
                "Embedding count mismatch: "
                f"expected {len(chunk_rows)}, got {len(vectors)}"
            )

        for chunk, vector in zip(chunk_rows, vectors, strict=True):
            db.add(
                EmbeddingsModel(
                    chunk_id=chunk.id,
                    vector=embedder.serialize(vector),
                    model=embedder.model_name,
                )
            )

        db.commit()
        db.refresh(paper)
        return paper
    except Exception:
        db.rollback()
        raise
