"""Regression test for the PaperOut response schema — it broke in practice
because created_at was declared as `str` while SQLAlchemy returns a real
datetime, and Pydantic v2 doesn't silently coerce datetime -> str."""
from datetime import datetime

from schema import PaperOut


def test_paper_out_accepts_datetime_created_at():
    paper = PaperOut(
        id=1,
        title="Test Paper",
        authors="Someone",
        year=2024,
        abstract=None,
        arxiv_id=None,
        created_at=datetime(2026, 8, 25, 9, 33, 25),
    )
    assert paper.model_dump()["created_at"] == datetime(2026, 8, 25, 9, 33, 25)


def test_paper_out_serializes_to_iso_string_json():
    paper = PaperOut(id=1, title="Test Paper", created_at=datetime(2026, 8, 25, 9, 33, 25))
    assert "2026-08-25T09:33:25" in paper.model_dump_json()


def test_paper_out_from_orm_like_object():
    """Simulates what FastAPI does with from_attributes=True on a real ORM row."""

    class _FakePaperRow:
        id = 1
        title = "ORM Paper"
        authors = None
        year = None
        abstract = None
        arxiv_id = None
        created_at = datetime(2026, 8, 25, 9, 33, 25)

    paper = PaperOut.model_validate(_FakePaperRow())
    assert paper.title == "ORM Paper"
