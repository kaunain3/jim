"""Topic -> candidate papers -> user picks -> ingest.

Two-step by design: GET /discover just returns candidates (nothing is
downloaded or stored yet). POST /discover/ingest downloads and runs the one
paper the user actually chose through the existing ingest_paper pipeline —
same dedup/embedding behavior as a manual upload.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from config import settings
from db.engine import get_db
from schema import DiscoveredPaperOut, IngestArxivRequest, PaperOut
from services.discovery import ArxivClient, download_pdf
from services.extractor import PDFExtractor
from services.ingest import ingest_paper

router = APIRouter(prefix="/discover", tags=["discovery"])
_arxiv_client = ArxivClient()
_extractor = PDFExtractor()


@router.get("", response_model=list[DiscoveredPaperOut])
async def discover(topic: str, max_results: int = 10):
    """Search arXiv for a topic. Returns candidates only — nothing is ingested yet."""
    results = await _arxiv_client.search(topic, max_results=max_results)
    return [
        DiscoveredPaperOut(
            arxiv_id=r.arxiv_id,
            title=r.title,
            authors=r.authors,
            abstract=r.abstract,
            year=r.year,
            pdf_url=r.pdf_url,
        )
        for r in results
    ]


@router.post("/ingest", response_model=PaperOut)
async def ingest_discovered(request: IngestArxivRequest, db: Session = Depends(get_db)):
    """Download and ingest one paper the user selected from /discover results."""
    dest_path = settings.library_dir / f"{request.arxiv_id}.pdf"

    try:
        await download_pdf(request.pdf_url, dest_path)
    except Exception as exc:  # network/HTTP error from the PDF host
        raise HTTPException(status_code=502, detail=f"Failed to download PDF: {exc}") from exc

    try:
        paper = await ingest_paper(
            db,
            dest_path,
            _extractor,
            title=request.title,
            authors=", ".join(request.authors) if request.authors else None,
            year=request.year,
            arxiv_id=request.arxiv_id,
            abstract=request.abstract,
        )
    except ValueError as exc:
        dest_path.unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return paper
