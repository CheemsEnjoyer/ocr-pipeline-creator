"""Private S3 originals; PostgreSQL stores metadata and local data holds admin credentials."""

import os
import shutil
import tempfile
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool


class StorageError(Exception):
    pass


class OriginalNotFound(StorageError):
    pass


class TemporaryFileResponse(FileResponse):
    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            await run_in_threadpool(Path(self.path).unlink, missing_ok=True)


class S3Storage:
    def __init__(self, bucket, prefix="originals", client=None):
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.client = client

    @classmethod
    def from_env(cls):
        bucket = os.getenv("S3_BUCKET", "").strip()
        if not bucket:
            raise RuntimeError("Задайте S3_BUCKET в .env: исходные файлы сохраняются в S3.")
        style = os.getenv("S3_ADDRESSING_STYLE", "auto").strip()
        if style not in {"auto", "path", "virtual"}:
            raise RuntimeError("S3_ADDRESSING_STYLE должен быть auto, path или virtual.")
        client = boto3.client(
            "s3",
            endpoint_url=os.getenv("S3_ENDPOINT_URL") or None,
            region_name=os.getenv("S3_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1",
            config=Config(
                s3={"addressing_style": style},
                connect_timeout=10,
                read_timeout=60,
                retries={"mode": "standard", "total_max_attempts": 3},
                # Compatible with providers that do not support optional AWS checksums.
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )
        return cls(bucket, os.getenv("S3_PREFIX", "originals"), client)

    def put(self, document_id, content, mime):
        key = f"{self.prefix}/{document_id}" if self.prefix else document_id
        try:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=content, ContentType=mime)
        except (BotoCoreError, ClientError) as error:
            raise StorageError("Не удалось сохранить исходный файл в S3") from error
        return "s3:" + key

    def delete(self, original_key):
        try:
            self.client.delete_object(Bucket=self.bucket, Key=original_key.removeprefix("s3:"))
        except (BotoCoreError, ClientError) as error:
            raise StorageError("Не удалось удалить исходный файл из S3") from error

    def download(self, original_key):
        """Temporary copy allows FileResponse to preserve PDF range and If-Range semantics."""
        path = None
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=original_key.removeprefix("s3:"))
            body = response["Body"]
            try:
                with tempfile.NamedTemporaryFile(prefix="ocr-original-", delete=False) as output:
                    path = Path(output.name)
                    shutil.copyfileobj(body, output)
            finally:
                body.close()
            return path
        except Exception as error:
            if path is not None:
                path.unlink(missing_ok=True)
            if isinstance(error, ClientError) and error.response["Error"]["Code"] in {"NoSuchKey", "NotFound", "404"}:
                raise OriginalNotFound("Исходный файл не найден в S3") from error
            if isinstance(error, (BotoCoreError, ClientError)):
                raise StorageError("Не удалось прочитать исходный файл из S3") from error
            raise

    def close(self):
        self.client.close()
