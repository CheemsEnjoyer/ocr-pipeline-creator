from pathlib import Path

from sqlalchemy import JSON, Index, Integer, String, Text, create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (Index("idx_documents_created_at", "created_at", "id"), Index("idx_documents_api_key", "api_key_id", "created_at", "id"))

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
    # Источник обработки: по api_key_id ключ интеграции видит только свои документы. У старых записей пусто.
    pipeline_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    api_key_id: Mapped[str | None] = mapped_column(String(36), nullable=True)



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


def upgrade_schema(engine):
    # create_all не меняет существующие таблицы, поэтому новые столбцы и индексы документов добавляем сами.
    existing = {column["name"] for column in inspect(engine).get_columns("documents")}
    with engine.begin() as connection:
        for name in ("pipeline_id", "api_key_id"):
            if name not in existing:
                column_type = Document.__table__.c[name].type.compile(dialect=engine.dialect)
                connection.execute(text(f"ALTER TABLE documents ADD COLUMN {name} {column_type}"))
        for index in Document.__table__.indexes:
            index.create(connection, checkfirst=True)


def open_database(database_url: str):
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        Path(url.database).resolve().parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30} if url.get_backend_name() == "sqlite" else {})
    return engine, sessionmaker(engine, expire_on_commit=False)
