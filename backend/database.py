from pathlib import Path

from sqlalchemy import JSON, Index, Integer, String, Text, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (Index("idx_documents_created_at", "created_at", "id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    filename: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(Integer)
    pipeline_name: Mapped[str] = mapped_column(Text)
    original_key: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    result: Mapped[str] = mapped_column(Text)
    fields: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))
    revision: Mapped[int] = mapped_column(Integer, default=0)



class SavedPipeline(Base):
    __tablename__ = "pipelines"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    config: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))
    deleted: Mapped[int] = mapped_column(Integer, default=0)



class APIKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    prefix: Mapped[str] = mapped_column(String(20))
    pipeline_ids: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(32))
    revoked_at: Mapped[str | None] = mapped_column(String(32), nullable=True)


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    admin_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[int] = mapped_column(Integer)


def open_database(database_url: str):
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        Path(url.database).resolve().parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30} if url.get_backend_name() == "sqlite" else {})
    return engine, sessionmaker(engine, expire_on_commit=False)
