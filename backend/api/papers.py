from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from config import settings
from db.engine import get_db
from db.models import PapersModel
from schema import PaperOut
from services.extractor import PDFExtractor
from services.ingest import ingest_paper

router = APIRouter(prefix="/papers", tags=["papers"])
_extractor = PDFExtractor()


@router.post("", response_model=PaperOut)
async def upload_paper(file: UploadFile, db: Session = Depends(get_db)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    dest_path = settings.library_dir / file.filename
    with dest_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        paper = await ingest_paper(
            db,
            dest_path,
            _extractor,
            title=Path(file.filename).stem,
        )
    except ValueError as exc:
        # Duplicate (sha256 already ingested) — clean up the copy we just made.
        dest_path.unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return paper


@router.get("", response_model=list[PaperOut])
def list_papers(db: Session = Depends(get_db)):
    return db.query(PapersModel).order_by(PapersModel.created_at.desc()).all()


@router.get("/{paper_id}", response_model=PaperOut)
def get_paper(paper_id: int, db: Session = Depends(get_db)):
    paper = db.query(PapersModel).get(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper
