from fastapi import FastAPI
from db.engine import engine, Base
from db import models
from api import papers, chat, discovery

app = FastAPI(title="JIM-Your personal PHD assistent")

app.include_router(papers.router)
app.include_router(chat.router)
app.include_router(discovery.router)

@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)

@app.get("/")
def read_root():
    return {"message": "Welcome to JIM-Your personal PHD assistent"}