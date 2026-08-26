"""Async background job runner with SSE progress broadcasting.

Jobs are submitted via ``submit()``, processed by a pool of worker tasks,
and progress is broadcast to any SSE subscribers via ``notify()``.
"""
from __future__ import annotations

import json
import logging
import uuid
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Job:
    id: str
    job_type: str
    kwargs: dict[str, Any]
    status: JobStatus = JobStatus.PENDING
    progress: float = 0.0
    error: str | None = None
    result: dict | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    subscribers: list[asyncio.Event] = field(default_factory=list)
    on_change: Callable[["Job"], None] | None = field(
        default=None, repr=False, compare=False
    )

    def notify(self, progress: float, event: str | None = None, extra: dict | None = None) -> None:
        """Broadcast a progress/event update to all SSE subscribers."""
        self.progress = progress
        payload: dict[str, Any] = {
            "type": event or "progress",
            "job_id": self.id,
            "percent": progress,
        }
        if extra:
            payload.update(extra)
        for subscriber in list(self.subscribers):
            subscriber.set()
        self._last_event = payload
        if self.on_change is not None:
            self.on_change(self)

    def unsubscribe(self, event: asyncio.Event) -> None:
        """Remove a subscriber event so it no longer receives notifications."""
        if event in self.subscribers:
            self.subscribers.remove(event)

    def complete(self, result: dict | None = None) -> None:
        self.status = JobStatus.COMPLETED
        self.progress = 100.0
        self.result = result
        self.completed_at = datetime.now(timezone.utc)
        self.notify(100.0, event="result", extra={"result": result})
        self._cleanup_subscribers()

    def fail(self, error: str) -> None:
        self.status = JobStatus.FAILED
        self.error = error
        self.completed_at = datetime.now(timezone.utc)
        self.notify(0.0, event="error", extra={"message": error})
        self._cleanup_subscribers()

    def _cleanup_subscribers(self) -> None:
        alive = [s for s in self.subscribers if s.is_set()]
        self.subscribers = alive

    def add_subscriber(self) -> asyncio.Event:
        event = asyncio.Event()
        self.subscribers.append(event)
        return event


class JobRunner:
    """Manages a pool of async workers that drain a shared job queue."""

    def __init__(self, max_workers: int = 2) -> None:
        self._queue: asyncio.Queue = asyncio.Queue()
        self._jobs: dict[str, Job] = {}
        self._max_workers = max_workers
        self._running = False
        self._worker_tasks: list[asyncio.Task] = []

    def start(self) -> None:
        """Restore queued work and start the background worker tasks."""
        if self._running:
            return
        self._restore_jobs()
        self._running = True
        for i in range(self._max_workers):
            task = asyncio.create_task(self._worker(i))
            self._worker_tasks.append(task)
        logger.info("Job runner started with %d workers", self._max_workers)

    def stop(self) -> None:
        """Request cancellation of all worker tasks."""
        self._running = False
        for task in self._worker_tasks:
            task.cancel()
        logger.info("Job runner stopping")

    async def shutdown(self) -> None:
        """Cancel workers and wait until all worker tasks have exited."""
        self.stop()
        tasks = list(self._worker_tasks)
        self._worker_tasks.clear()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Job runner stopped")

    def submit(self, job_type: str, **kwargs: Any) -> str:
        """Submit a job and return its ID."""
        job_id = str(uuid.uuid4())
        job = Job(
            id=job_id,
            job_type=job_type,
            kwargs=kwargs,
            on_change=self._persist_job,
        )
        self._jobs[job_id] = job
        self._persist_job(job)
        self._queue.put_nowait(job_id)
        logger.info("Job submitted: %s (type=%s)", job_id, job_type)
        return job_id

    def get_job(self, job_id: str) -> Job | None:
        job = self._jobs.get(job_id)
        if job is not None:
            return job
        return self._load_job(job_id)

    @staticmethod
    def _persist_job(job: Job) -> None:
        """Write current job state to SQLite for polling and restart recovery."""
        from db.engine import Base, SessionLocal, engine
        from db.models import JobsModel

        Base.metadata.create_all(bind=engine, tables=[JobsModel.__table__])
        db = SessionLocal()
        try:
            row = db.get(JobsModel, job.id)
            if row is None:
                row = JobsModel(id=job.id, job_type=job.job_type)
                db.add(row)
            row.job_type = job.job_type
            row.kwargs_json = json.dumps(job.kwargs)
            row.status = job.status.value
            row.progress = job.progress
            row.error = job.error
            row.result_json = json.dumps(job.result) if job.result is not None else None
            last_event = getattr(job, "_last_event", None)
            row.last_event_json = (
                json.dumps(last_event) if last_event is not None else None
            )
            row.created_at = job.created_at
            row.completed_at = job.completed_at
            db.commit()
        finally:
            db.close()

    def _load_job(self, job_id: str) -> Job | None:
        from db.engine import Base, SessionLocal, engine
        from db.models import JobsModel

        Base.metadata.create_all(bind=engine, tables=[JobsModel.__table__])
        db = SessionLocal()
        try:
            row = db.get(JobsModel, job_id)
            if row is None:
                return None
            job = Job(
                id=row.id,
                job_type=row.job_type,
                kwargs=json.loads(row.kwargs_json or "{}"),
                status=JobStatus(row.status),
                progress=row.progress,
                error=row.error,
                result=json.loads(row.result_json) if row.result_json else None,
                created_at=row.created_at,
                completed_at=row.completed_at,
                on_change=self._persist_job,
            )
            if row.last_event_json:
                job._last_event = json.loads(row.last_event_json)
            self._jobs[job.id] = job
            return job
        finally:
            db.close()

    def _restore_jobs(self) -> None:
        """Reload persisted jobs and requeue work interrupted by a restart."""
        from db.engine import Base, SessionLocal, engine
        from db.models import JobsModel

        Base.metadata.create_all(bind=engine, tables=[JobsModel.__table__])
        db = SessionLocal()
        try:
            ids = [row[0] for row in db.query(JobsModel.id).all()]
        finally:
            db.close()
        for job_id in ids:
            job = self._jobs.get(job_id) or self._load_job(job_id)
            if job is None:
                continue
            if job.status in (JobStatus.PENDING, JobStatus.RUNNING):
                job.status = JobStatus.PENDING
                job.progress = 0.0
                job.error = None
                job.completed_at = None
                self._persist_job(job)
                self._queue.put_nowait(job.id)

    def subscribe(self, job_id: str) -> asyncio.Event:
        """Add a subscriber to a job and return the event to wait on."""
        job = self._jobs.get(job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")
        return job.add_subscriber()

    def unsubscribe(self, job_id: str, event: asyncio.Event) -> None:
        """Remove a subscriber event from a job."""
        job = self._jobs.get(job_id)
        if job is not None:
            job.unsubscribe(event)

    def stream_events(self, job_id: str) -> Any:
        """Return an async generator that yields SSE-formatted event dicts."""
        job = self._jobs.get(job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")

        async def _event_stream():
            while True:
                if job.subscribers:
                    job.subscribers[-1].clear()
                    await job.subscribers[-1].wait()
                else:
                    await asyncio.sleep(0.1)
                last = getattr(job, '_last_event', None)
                if last is not None:
                    yield f"data: {json.dumps(last)}\n\n"
                if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                    yield "data: {\"type\":\"end\"}\n\n"
                    break

        return _event_stream()  # Returns the raw generator for testing

    async def _worker(self, worker_id: int) -> None:
        """Drain the queue and execute jobs."""
        while self._running or not self._queue.empty():
            try:
                job_id = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                if not self._running:
                    break
                continue

            job = self._jobs[job_id]
            job.status = JobStatus.RUNNING
            job.notify(5.0, event="progress", extra={"stage": "started"})

            try:
                result = await self._execute_job(job)
                job.complete(result)
            except Exception as exc:
                logger.exception("Job %s failed: %s", job_id, exc)
                job.fail(str(exc))

    async def _execute_job(self, job: Job) -> dict | None:
        """Dispatch to the appropriate handler based on job_type."""
        if job.job_type == "ingest":
            return await self._run_ingest(job)
        elif job.job_type == "arxiv_ingest":
            return await self._run_arxiv_ingest(job)
        else:
            raise ValueError(f"Unknown job type: {job.job_type}")

    async def _run_ingest(self, job: Job) -> dict:
        """Execute a paper ingestion job with progress reporting."""
        from db.engine import SessionLocal
        from services.extractor import PDFExtractor
        from services.ingest import ingest_paper

        pdf_path = job.kwargs.get("pdf_path")
        use_ocr = job.kwargs.get("use_ocr", False)
        title = job.kwargs.get("title")

        if not pdf_path:
            raise ValueError("pdf_path is required")

        job.notify(10.0, event="progress", extra={"stage": "extracting"})

        extractor = PDFExtractor()
        result = await extractor.extract(pdf_path, use_ocr=use_ocr)
        job.notify(40.0, event="progress", extra={"stage": "extracted", "sections": len(result.sections)})

        db = SessionLocal()
        try:
            paper = await ingest_paper(
                db,
                pdf_path,
                extractor,
                title=title,
                use_ocr=use_ocr,
                extraction_result=result,  # avoid re-extracting the same PDF
            )
            job.notify(95.0, event="progress", extra={"stage": "complete"})
            return {"paper_id": paper.id, "title": paper.title}
        finally:
            db.close()

    async def _run_arxiv_ingest(self, job: Job) -> dict:
        """Execute an arXiv paper ingestion job."""
        from db.engine import SessionLocal
        from services.discovery import ArxivClient

        arxiv_id = job.kwargs.get("arxiv_id")
        if not arxiv_id:
            raise ValueError("arxiv_id is required")

        job.notify(10.0, event="progress", extra={"stage": "downloading"})
        paper = await ArxivClient.download_and_ingest(arxiv_id)
        job.notify(100.0, event="result", extra={"paper_id": paper.id})
        return {"paper_id": paper.id, "arxiv_id": arxiv_id}


# Singleton instance
job_runner = JobRunner()
