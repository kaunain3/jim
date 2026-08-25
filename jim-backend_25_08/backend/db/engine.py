from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker,declarative_base

SQLALCHEMY_DATABASE_URL = "sqlite:///./Jim_db.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False}  # Required for FastAPI + SQLite
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()