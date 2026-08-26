"""Job management API: poll and stream progress via SSE."""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from schema import JobOut
from workers.job_runner import JobStatus, job_runner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])

# Emit an SSE comment every this-many-seconds while a job is running so
# proxies/load balancers don't kill idle connections mid-job.
_KEEPALIVE_SECONDS = 15.0


@router.get("/stream/{job_id}")
async def stream_progress(job_id: str):
    """SSE endpoint that streams progress events for a job.

    Correctness notes (each fixes a previously-confirmed bug):

    1. The event is cleared before every wait, so a set event wakes the
       generator exactly once. Without this, an already-set event makes the
       loop spin at full CPU replaying the same payload (busy-loop flood).
    2. Current state is replayed on every wake, so a subscriber that joins
       *after* the job already emitted events (including after completion)
       still receives the latest event and the terminal "end" instead of
       hanging forever.
    3. Terminal status is checked *before* waiting, so completed/failed jobs
       close the stream immediately rather than waiting for a notify that
       already happened.
    4. A keepalive comment is emitted every ``_KEEPALIVE_SECONDS`` while the
       job is running so idle connections aren't closed by intermediaries.
    5. The subscriber is removed when the generator exits (client disconnect
       or terminal state) so events don't leak on the Job.
    """
    job = job_runner.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    event = job_runner.subscribe(job_id)

    async def _sse_stream():
        sent: dict | None = None
        try:
            while True:
                event.clear()

                job = job_runner.get_job(job_id)
                if job is None:
                    yield 'data: {"type":"error","message":"Job not found"}\n\n'
                    break

                # Replay the latest event only when it actually changed, so
                # keepalive pings don't re-send an identical progress update.
                last = getattr(job, "_last_event", None)
                if last is not None and last is not sent:
                    sent = last
                    yield f"data: {json.dumps(last)}\n\n"

                if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                    yield 'data: {"type":"end"}\n\n'
                    break

                try:
                    await asyncio.wait_for(event.wait(), timeout=_KEEPALIVE_SECONDS)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            raise
        finally:
            job_runner.unsubscribe(job_id, event)

    return StreamingResponse(_sse_stream(), media_type="text/event-stream")


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: str):
    """Poll the current status of a job."""
    job = job_runner.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return JobOut(
        id=job.id,
        status=job.status.value,
        progress=job.progress,
        error=job.error,
        result=job.result,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )
