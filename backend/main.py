from contextlib import asynccontextmanager

from fastapi import FastAPI

from db.engine import Base, engine
from db import models
from api import papers, chat, discovery, jobs
from workers.job_runner import job_runner


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    job_runner.start()
    try:
        yield
    finally:
        await job_runner.shutdown()


app = FastAPI(title="JIM-Your personal PHD assistent", lifespan=lifespan)

app.include_router(papers.router)
app.include_router(chat.router)
app.include_router(discovery.router)
app.include_router(jobs.router)


@app.get("/")
def read_root():
    return {"message": "Welcome to JIM-Your personal PHD assistent"}


@app.get("/health")
def health():
    return {"status": "ok"}