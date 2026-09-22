"""Private S3 originals; PostgreSQL stores metadata and local data holds admin credentials."""

import os
import base64
import hashlib
import hmac
import io
import mimetypes
from datetime import timedelta
from urllib.parse import unquote, urlsplit
import shutil
import tempfile
from pathlib import Path

import boto3
import httpx
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from ..core.config import MAX_FILE_SIZE


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
    def __init__(self, bucket, prefix="originals", client=None, *, ensure_bucket=False):
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.client = client
        if ensure_bucket:
            self._ensure_bucket_exists()

    @classmethod
    def from_env(cls):
        bucket = os.getenv("S3_BUCKET_NAME", "").strip() or os.getenv("S3_BUCKET", "").strip()
        if not bucket:
            raise RuntimeError("Задайте S3_BUCKET_NAME или S3_BUCKET в .env: исходные файлы сохраняются в S3.")
        access_key = os.getenv("S3_ACCESS_KEY_ID")
        secret_key = os.getenv("S3_SECRET_ACCESS_KEY")
        credentials = {}
        if access_key or secret_key:
            if not access_key or not secret_key:
                raise RuntimeError("Задайте обе переменные S3_ACCESS_KEY_ID и S3_SECRET_ACCESS_KEY.")
            credentials = {"aws_access_key_id": access_key, "aws_secret_access_key": secret_key}
            if os.getenv("AWS_SESSION_TOKEN"):
                credentials["aws_session_token"] = os.environ["AWS_SESSION_TOKEN"]
        style = os.getenv("S3_ADDRESSING_STYLE", "auto").strip()
        if style not in {"auto", "path", "virtual"}:
            raise RuntimeError("S3_ADDRESSING_STYLE должен быть auto, path или virtual.")
        client = boto3.client(
            "s3",
            **credentials,
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
        self.upload_file(key, content, mime)
        return "s3:" + key

    def delete(self, original_key):
        self.delete_file(original_key)

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

    @property
    def bucket_name(self):
        return self.bucket

    @staticmethod
    def _key(object_key):
        key = str(object_key).removeprefix("s3:")
        if not key:
            raise ValueError("Укажите ключ объекта")
        return key

    def _call(self, operation, **kwargs):
        try:
            return getattr(self.client, operation)(Bucket=self.bucket, **kwargs)
        except ClientError as error:
            if error.response["Error"]["Code"] in {"NoSuchKey", "NotFound", "404"}:
                raise OriginalNotFound("Файл не найден в S3") from error
            raise StorageError("Ошибка операции с S3") from error
        except BotoCoreError as error:
            raise StorageError("Ошибка соединения с S3") from error

    def _ensure_bucket_exists(self):
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as error:
            if error.response["Error"]["Code"] not in {"NoSuchBucket", "NotFound", "404"}:
                raise StorageError("Не удалось проверить S3 bucket") from error
            region = self.client.meta.region_name
            options = {"CreateBucketConfiguration": {"LocationConstraint": region}} if region and region != "us-east-1" else {}
            try:
                self._call("create_bucket", **options)
            except StorageError as creation_error:
                cause = creation_error.__cause__
                if not isinstance(cause, ClientError) or cause.response["Error"]["Code"] != "BucketAlreadyOwnedByYou":
                    raise
        except BotoCoreError as error:
            raise StorageError("Не удалось проверить S3 bucket") from error

    def generate_object_key(self, user_id, job_id, file_type, filename):
        segments = [str(value) for value in (file_type, user_id, job_id, filename)]
        if any(not value or value in {".", ".."} or "/" in value or "\\" in value for value in segments):
            raise ValueError("Компоненты ключа должны быть непустыми именами без разделителей пути")
        return "/".join(segments)

    @staticmethod
    def _expiry(expires):
        seconds = 3600 if expires is None else expires.total_seconds() if isinstance(expires, timedelta) else expires
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not 1 <= seconds <= 604800 or seconds != int(seconds):
            raise ValueError("Срок действия ссылки должен быть от 1 до 604800 секунд")
        return int(seconds)

    def _presign(self, operation, object_key, expires=None, **params):
        expiry = self._expiry(expires)
        try:
            return self.client.generate_presigned_url(operation, Params={"Bucket": self.bucket, "Key": self._key(object_key), **params}, ExpiresIn=expiry)
        except (BotoCoreError, ClientError) as error:
            raise StorageError("Не удалось создать временную ссылку S3") from error

    def generate_presigned_put_url(self, object_key, expires=None):
        return self._presign("put_object", object_key, expires)

    def generate_presigned_get_url(self, object_key, expires=None):
        return self._presign("get_object", object_key, expires)

    def initiate_multipart_upload(self, object_key, content_type="application/octet-stream"):
        return self._call("create_multipart_upload", Key=self._key(object_key), ContentType=content_type)["UploadId"]

    def generate_multipart_presigned_urls(self, object_key, upload_id, num_parts, expires=None):
        if type(num_parts) is not int or not 1 <= num_parts <= 10000:
            raise ValueError("Число частей должно быть от 1 до 10000")
        if not upload_id:
            raise ValueError("Укажите UploadId")
        return [{"part_number": number, "url": self._presign("upload_part", object_key, expires, UploadId=upload_id, PartNumber=number)} for number in range(1, num_parts + 1)]

    def complete_multipart_upload(self, object_key, upload_id, parts):
        if not upload_id or not parts or len(parts) > 10000:
            raise ValueError("Укажите UploadId и список частей")
        normalized = [{"PartNumber": part["PartNumber"], "ETag": part["ETag"]} for part in parts]
        numbers = [part["PartNumber"] for part in normalized]
        if any(type(number) is not int or not 1 <= number <= 10000 for number in numbers) or len(set(numbers)) != len(numbers) or any(not isinstance(part["ETag"], str) or not part["ETag"] for part in normalized):
            raise ValueError("Некорректные номера частей или ETag")
        return self._call("complete_multipart_upload", Key=self._key(object_key), UploadId=upload_id, MultipartUpload={"Parts": sorted(normalized, key=lambda part: part["PartNumber"])})

    def abort_multipart_upload(self, object_key, upload_id):
        if not upload_id:
            raise ValueError("Укажите UploadId")
        self._call("abort_multipart_upload", Key=self._key(object_key), UploadId=upload_id)

    def upload_file(self, object_key, data, content_type="application/octet-stream"):
        self._call("put_object", Key=self._key(object_key), Body=data, ContentType=content_type)
        return True

    def download_file(self, object_key):
        body = self._call("get_object", Key=self._key(object_key))["Body"]
        try:
            return body.read()
        except (BotoCoreError, OSError) as error:
            raise StorageError("Не удалось прочитать файл из S3") from error
        finally:
            body.close()

    def delete_file(self, object_key):
        self._call("delete_object", Key=self._key(object_key))
        return True

    def delete_folder(self, prefix):
        key = self._key(prefix).strip("/")
        if not key:
            raise ValueError("Укажите непустую папку")
        folder = key + "/"
        count = 0
        token = None
        while True:
            page = self._call("list_objects_v2", Prefix=folder, **({"ContinuationToken": token} if token else {}))
            for item in page.get("Contents", []):
                self.delete_file(item["Key"])
                count += 1
            if not page.get("IsTruncated"):
                return count
            token = page["NextContinuationToken"]

    def file_exists(self, object_key):
        try:
            self._call("head_object", Key=self._key(object_key))
            return True
        except OriginalNotFound:
            return False

    def get_file_size(self, object_key):
        try:
            return self._call("head_object", Key=self._key(object_key))["ContentLength"]
        except OriginalNotFound:
            return None

    def verify_file_integrity(self, object_key, expected_md5=None, expected_size=None):
        try:
            stat = self._call("head_object", Key=self._key(object_key))
            if expected_size is not None and stat["ContentLength"] != expected_size:
                return False
            if expected_md5 is None:
                return True
            try:
                expected = bytes.fromhex(expected_md5) if len(expected_md5) == 32 else base64.b64decode(expected_md5, validate=True)
            except (ValueError, TypeError):
                return False
            if len(expected) != 16:
                return False
            digest = hashlib.md5(usedforsecurity=False)
            body = self._call("get_object", Key=self._key(object_key))["Body"]
            try:
                for chunk in iter(lambda: body.read(1024 * 1024), b""):
                    digest.update(chunk)
            finally:
                body.close()
            return hmac.compare_digest(digest.digest(), expected)
        except OriginalNotFound:
            return False
        except (BotoCoreError, OSError) as error:
            raise StorageError("Не удалось проверить файл из S3") from error

    def download_external(self, file_url, content_type, *, client=None):
        parsed = urlsplit(file_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Укажите HTTP(S) URL без учётных данных")
        mime = (content_type or "application/octet-stream").split(";", 1)[0].strip().lower()
        filename = unquote(parsed.path.rsplit("/", 1)[-1]).replace("\\", "/").rsplit("/", 1)[-1]
        filename = "".join(char for char in filename if char.isprintable())
        if filename in {"", ".", ".."}:
            filename = "uploaded_file"
        if not Path(filename).suffix:
            filename += {"image/tif": ".tiff", "image/jpg": ".jpg"}.get(mime) or mimetypes.guess_extension(mime) or ""
        owned_client = client is None
        client = client or httpx.Client(timeout=httpx.Timeout(60, connect=15), follow_redirects=False)
        try:
            with client.stream("GET", file_url, follow_redirects=False) as response:
                response.raise_for_status()
                content = io.BytesIO()
                for chunk in response.iter_bytes(chunk_size=65536):
                    if content.tell() + len(chunk) > MAX_FILE_SIZE:
                        raise StorageError("Максимальный размер файла — 20 МБ")
                    content.write(chunk)
                content.seek(0)
                return {"file": (filename, content, mime)}
        except httpx.HTTPError as error:
            raise StorageError("Не удалось скачать внешний файл") from error
        finally:
            if owned_client:
                client.close()

    def close(self):
        self.client.close()
