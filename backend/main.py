from fastapi import FastAPI

app = FastAPI(title="JIM-Your personal PHD assistent")

@app.get("/")
def read_root():
    return {"message": "Welcome to JIM-Your personal PHD assistent"}