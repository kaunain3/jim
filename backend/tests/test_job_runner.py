"""Tests for the background job runner and SSE progress streaming."""
from __future__ import annotations

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch

from workers.job_runner import JobRunner, Job, JobStatus


@pytest.fixture
def runner():
    r = JobRunner(max_workers=2)
    yield r
    r.stop()


@pytest.mark.asyncio
async def test_submit_returns_job_id(runner):
    job_id = runner.submit("ingest", pdf_path="/tmp/test.pdf")
    assert isinstance(job_id, str)
    assert len(job_id) > 0

    job = runner.get_job(job_id)
    assert job is not None
    assert job.status == JobStatus.PENDING
    assert job.progress == 0.0


@pytest.mark.asyncio
async def test_job_status_transitions(runner):
    job_id = runner.submit("ingest", pdf_path="/tmp/test.pdf")
    job = runner.get_job(job_id)
    assert job.status == JobStatus.PENDING

    # Simulate running -> completed
    job.status = JobStatus.RUNNING
    job.notify(50.0, event="progress", extra={"stage": "extracting"})
    assert job.status == JobStatus.RUNNING
    assert job.progress == 50.0

    job.complete({"paper_id": 42})
    assert job.status == JobStatus.COMPLETED
    assert job.progress == 100.0
    assert job.result == {"paper_id": 42}


@pytest.mark.asyncio
async def test_job_failure_emits_error(runner):
    job_id = runner.submit("ingest", pdf_path="/tmp/test.pdf")
    job = runner.get_job(job_id)

    job.fail("PDF not found")
    assert job.status == JobStatus.FAILED
    assert job.error == "PDF not found"
    assert job.completed_at is not None


@pytest.mark.asyncio
async def test_multiple_concurrent_jobs(runner):
    id1 = runner.submit("ingest", pdf_path="/tmp/a.pdf")
    id2 = runner.submit("ingest", pdf_path="/tmp/b.pdf")

    job1 = runner.get_job(id1)
    job2 = runner.get_job(id2)

    assert job1 is not None
    assert job2 is not None
    assert job1.id != job2.id


@pytest.mark.asyncio
async def test_sse_stream_emits_progress():
    """Verify that stream_events yields SSE-formatted dicts."""
    runner = JobRunner(max_workers=1)
    job_id = runner.submit("ingest", pdf_path="/tmp/test.pdf")
    job = runner.get_job(job_id)

    # Start the generator first (it will wait on the event), then notify
    gen = runner.stream_events(job_id)
    await asyncio.sleep(0.05)  # let generator reach the wait point
    job.notify(30.0, event="progress", extra={"stage": "extracting"})

    chunks = []
    try:
        async with asyncio.timeout(2):
            async for chunk in gen:
                chunks.append(chunk)
                if "end" in chunk:
                    break
    except asyncio.TimeoutError:
        pass

    combined = "".join(chunks)
    assert "progress" in combined, f"Expected progress in output, got: {combined!r}"

    runner.stop()


@pytest.mark.asyncio
async def test_get_job_returns_status(runner):
    job_id = runner.submit("ingest", pdf_path="/tmp/test.pdf")
    job = runner.get_job(job_id)

    from schema import JobOut
    result = JobOut(
        id=job.id,
        status=job.status.value,
        progress=job.progress,
        error=job.error,
        result=job.result,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )
    assert result.status == JobStatus.PENDING.value
    assert result.progress == 0.0
    assert result.error is None


@pytest.mark.asyncio
async def test_notify_updates_progress():
    job = Job(id="test-1", job_type="ingest", kwargs={})
    assert job.progress == 0.0
    assert job.status == JobStatus.PENDING

    job.notify(25.0, event="progress", extra={"stage": "starting"})
    assert job.progress == 25.0
    assert job._last_event["type"] == "progress"
    assert job._last_event["percent"] == 25.0
    assert job._last_event["stage"] == "starting"


@pytest.mark.asyncio
async def test_complete_sets_final_state():
    job = Job(id="test-2", job_type="ingest", kwargs={})
    job.status = JobStatus.RUNNING
    job.notify(80.0)

    job.complete({"paper_id": 7})
    assert job.status == JobStatus.COMPLETED
    assert job.progress == 100.0
    assert job.result == {"paper_id": 7}
    assert job.completed_at is not None


@pytest.mark.asyncio
async def test_fail_sets_error():
    job = Job(id="test-3", job_type="ingest", kwargs={})
    job.status = JobStatus.RUNNING
    job.notify(50.0)

    job.fail("Disk full")
    assert job.status == JobStatus.FAILED
    assert job.error == "Disk full"
    assert job.completed_at is not None


@pytest.mark.asyncio
async def test_get_job_missing_returns_none(runner):
    result = runner.get_job("nonexistent-id")
    assert result is None
