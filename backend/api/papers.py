from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session
from uuid import uuid4

from config import settings
from db.engine import get_db
from db.models import PapersModel
from schema import JobOut, PaperOut

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

    # Never use the client filename as a filesystem path. A generated name
    # also prevents concurrent uploads with the same name from overwriting
    # each other's input before their jobs run.
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


@router.get("/{paper_id}", response_model=PaperOut)
def get_paper(paper_id: int, db: Session = Depends(get_db)):
    paper = db.get(PapersModel, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper
