from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from config import settings
from db.engine import get_db
from schema import AskRequest, AskResponse, SourceOut
from services.llm_client import build_llm_client
from services.qa import ask as ask_qa

router = APIRouter(tags=["chat"])


@router.post("/ask", response_model=AskResponse)
async def ask(request: AskRequest, db: Session = Depends(get_db)):
    llm = build_llm_client(settings.llm_base_url)
    answer = await ask_qa(
        db,
        request.question,
        llm,
        top_k=request.top_k,
        paper_id=request.paper_id,
        model=settings.llm_model,
    )
    return AskResponse(
        answer=answer.text,
        sources=[
            SourceOut(
                chunk_id=source.chunk_id,
                paper_id=source.paper_id,
                page=source.page,
                title=source.title,
                score=source.score,
                excerpt=source.content[:300],
            )
            for source in answer.sources
        ],
    )
