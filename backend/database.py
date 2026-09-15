import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

from .models import Base, Document, ProcessingJob, SavedPipeline, APIKey, AdminSession

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def configured_database_url():
    value = os.getenv("DATABASE_URL", "").strip()
    if value:
        url = make_url(value)
        if url.drivername == "postgres":
            url = url.set(drivername="postgresql")
        if url.get_backend_name() != "postgresql":
            raise RuntimeError("DATABASE_URL должен указывать на PostgreSQL.")
        return url
    password = os.getenv("POSTGRES_PASSWORD", "")
    if not password:
        raise RuntimeError("Задайте POSTGRES_PASSWORD или DATABASE_URL для PostgreSQL в .env.")
    return URL.create(
        "postgresql+psycopg",
        username=os.getenv("POSTGRES_USER") or "ocr",
        password=password,
        host=os.getenv("POSTGRES_HOST") or "127.0.0.1",
        port=int(os.getenv("POSTGRES_PORT") or 5432),
        database=os.getenv("POSTGRES_DB") or "ocr",
    )


def open_database(database_url):
    url = make_url(database_url)
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")
    # SQLite is retained only for explicit isolated test databases.
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        Path(url.database).resolve().parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, pool_pre_ping=True, connect_args={"check_same_thread": False, "timeout": 30} if url.get_backend_name() == "sqlite" else {"connect_timeout": 10})
    return engine, sessionmaker(engine, expire_on_commit=False)
