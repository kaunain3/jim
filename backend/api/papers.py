from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session
from uuid import uuid4
from config import settings
from db.engine import get_db
from db.models import PapersModel
from schema import JobOut, PaperOut, StatsOut, SearchResultOut

router = APIRouter(prefix="/papers", tags=["papers"])


@router.post("", response_model=JobOut)
async def upload_paper(
    file: UploadFile = None,
    use_ocr: bool = False,
    db: Session = Depends(get_db),
):
    """Upload a PDF and start a background ingestion job. Returns job_id."""
    if not file or not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    safe_name = f"{uuid4().hex}.pdf"
    dest_path = settings.library_dir / safe_name
    with dest_path.open("wb") as buffer:
        while chunk := await file.read(1024 * 1024):
            buffer.write(chunk)
    from workers.job_runner import job_runner
    job_id = job_runner.submit(
        "ingest",
        pdf_path=str(dest_path),
        title=Path(file.filename).stem,
        use_ocr=use_ocr,
    )
    return JobOut(id=job_id, status="pending", progress=0.0)


@router.get("", response_model=list[PaperOut])
def list_papers(db: Session = Depends(get_db)):
    return db.query(PapersModel).order_by(PapersModel.created_at.desc()).all()


@router.get("/stats", response_model=StatsOut)
def get_stats(db: Session = Depends(get_db)):
    """Aggregate counts for the dashboard."""
    total_papers = db.query(PapersModel).count()
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    recent_additions = (
        db.query(PapersModel)
        .filter(PapersModel.created_at >= cutoff)
        .count()
    )
    return StatsOut(
        total_papers=total_papers,
        total_ingested=total_papers,  # every row in `papers` is a fully ingested paper
        recent_additions=recent_additions,
        active_sessions=0,
    )


@router.get("/search", response_model=list[SearchResultOut])
def search_papers(q: str, limit: int = 20, db: Session = Depends(get_db)):
    """Simple keyword search over title/authors/abstract.

    This is a basic LIKE-based search, not semantic. A future version could
    use the EmbeddingsModel table for vector similarity instead.
    """
    like_pattern = f"%{q}%"
    matches = (
        db.query(PapersModel)
        .filter(
            or_(
                PapersModel.title.ilike(like_pattern),
                PapersModel.authors.ilike(like_pattern),
                PapersModel.abstract.ilike(like_pattern),
            )
        )
        .order_by(PapersModel.created_at.desc())
        .limit(limit)
        .all()
    )
    # Naive scoring: title matches rank higher than abstract-only matches.
    results = []
    for paper in matches:
        score = 1.0 if q.lower() in (paper.title or "").lower() else 0.5
        results.append(SearchResultOut(paper=PaperOut.model_validate(paper), score=score))
    return results


@router.get("/{paper_id}", response_model=PaperOut)
def get_paper(paper_id: int, db: Session = Depends(get_db)):
    paper = db.get(PapersModel, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper


@router.delete("/{paper_id}")
def delete_paper(paper_id: int, db: Session = Depends(get_db)):
    paper = db.get(PapersModel, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    db.delete(paper)  # cascades to chunks, graph_nodes, memories per model relationships
    db.commit()
    return {"success": True, "message": f"Paper {paper_id} deleted"}
