"""Regression coverage for Phase 1 acceptance-level behavior."""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pymupdf
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import papers
from db.engine import Base
from db.models import JobsModel
from workers.job_runner import JobRunner, JobStatus


def _pdf_bytes(text: str = "A valid PDF document with enough extractable text for triage.") -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Introduction", fontsize=18)
    page.insert_text((72, 110), text, fontsize=11)
    payload = document.tobytes()
    document.close()
    return payload


def test_upload_uses_generated_library_path(monkeypatch, tmp_path: Path):
    captured: dict = {}

    class _Runner:
        def submit(self, job_type, **kwargs):
            captured.update(job_type=job_type, **kwargs)
            return "job-1"

    monkeypatch.setattr("workers.job_runner.job_runner", _Runner())
    monkeypatch.setattr("api.papers.settings.library_dir", tmp_path)
    app = FastAPI()
    app.include_router(papers.router)

    with TestClient(app) as client:
        response = client.post(
            "/papers",
            files={"file": ("../../outside.pdf", _pdf_bytes(), "application/pdf")},
        )

    assert response.status_code == 200
    stored_path = Path(captured["pdf_path"])
    assert stored_path.parent == tmp_path
    assert stored_path.name != "outside.pdf"
    assert stored_path.suffix == ".pdf"
    assert stored_path.is_file()


def test_same_filename_uploads_do_not_overwrite(monkeypatch, tmp_path: Path):
    paths: list[Path] = []

    class _Runner:
        def submit(self, job_type, **kwargs):
            paths.append(Path(kwargs["pdf_path"]))
            return f"job-{len(paths)}"

    monkeypatch.setattr("workers.job_runner.job_runner", _Runner())
    monkeypatch.setattr("api.papers.settings.library_dir", tmp_path)
    app = FastAPI()
    app.include_router(papers.router)

    with TestClient(app) as client:
        for body in (_pdf_bytes("First unique uploaded paper body with enough text."),
                     _pdf_bytes("Second unique uploaded paper body with enough text.")):
            response = client.post(
                "/papers",
                files={"file": ("paper.pdf", body, "application/pdf")},
            )
            assert response.status_code == 200

    assert paths[0] != paths[1]
    assert all(path.is_file() for path in paths)
    assert paths[0].read_bytes() != paths[1].read_bytes()


def test_initial_migration_creates_all_models(tmp_path: Path):
    migration = Path(__file__).parents[1] / "db/migrations/001_initial.sql"
    connection = sqlite3.connect(tmp_path / "migration.db")
    try:
        connection.executescript(migration.read_text())
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        connection.close()

    assert set(Base.metadata.tables) <= tables


@pytest.mark.asyncio
async def test_job_is_persisted_and_reloadable(monkeypatch, tmp_path: Path):
    import db.engine as db_engine

    test_engine = __import__("sqlalchemy").create_engine(
        f"sqlite:///{tmp_path / 'jobs.db'}",
        connect_args={"check_same_thread": False},
    )
    TestSession = __import__("sqlalchemy.orm", fromlist=["sessionmaker"]).sessionmaker(
        bind=test_engine
    )
    monkeypatch.setattr(db_engine, "engine", test_engine)
    monkeypatch.setattr(db_engine, "SessionLocal", TestSession)
    Base.metadata.create_all(test_engine)

    first = JobRunner(max_workers=1)
    job_id = first.submit("unknown")
    job = first.get_job(job_id)
    job.fail("expected")

    second = JobRunner(max_workers=1)
    restored = second.get_job(job_id)
    assert restored is not None
    assert restored.status == JobStatus.FAILED
    assert restored.error == "expected"

    with TestSession() as db:
        assert db.get(JobsModel, job_id) is not None


@pytest.mark.asyncio
async def test_shutdown_clears_worker_tasks(monkeypatch, tmp_path: Path):
    import db.engine as db_engine

    test_engine = __import__("sqlalchemy").create_engine(
        f"sqlite:///{tmp_path / 'shutdown.db'}",
        connect_args={"check_same_thread": False},
    )
    TestSession = __import__("sqlalchemy.orm", fromlist=["sessionmaker"]).sessionmaker(
        bind=test_engine
    )
    monkeypatch.setattr(db_engine, "engine", test_engine)
    monkeypatch.setattr(db_engine, "SessionLocal", TestSession)

    runner = JobRunner(max_workers=2)
    runner.start()
    assert len(runner._worker_tasks) == 2
    await asyncio.sleep(0)
    await runner.shutdown()
    assert runner._running is False
    assert runner._worker_tasks == []
