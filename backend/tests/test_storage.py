import base64
import hashlib
import io
import unittest
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import boto3
import httpx
from botocore.config import Config
from botocore.stub import Stubber

from backend.handler.storage import S3Storage, StorageError


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.client = boto3.client("s3", endpoint_url="https://storage.test", region_name="us-east-1", aws_access_key_id="test", aws_secret_access_key="test", config=Config(signature_version="s3v4"))
        self.addCleanup(self.client.close)
        self.storage = S3Storage("bucket", client=self.client)
        self.stub = Stubber(self.client)
        self.stub.activate()
        self.addCleanup(self.stub.deactivate)
        self.addCleanup(self.stub.assert_no_pending_responses)

    def test_multipart_upload_uses_real_upload_id_and_part_parameters(self):
        self.stub.add_response("create_multipart_upload", {"UploadId": "upload-123"}, {"Bucket": "bucket", "Key": "originals/id", "ContentType": "application/pdf"})
        upload_id = self.storage.initiate_multipart_upload("s3:originals/id", "application/pdf")
        urls = self.storage.generate_multipart_presigned_urls("s3:originals/id", upload_id, 2, timedelta(minutes=5))
        for number, part in enumerate(urls, 1):
            parsed = urlsplit(part["url"])
            query = parse_qs(parsed.query)
            self.assertEqual(parsed.path, "/bucket/originals/id")
            self.assertEqual(query["uploadId"], [upload_id])
            self.assertEqual(query["partNumber"], [str(number)])
            self.assertEqual(query["X-Amz-Expires"], ["300"])
        parts = [{"PartNumber": 2, "ETag": "second"}, {"PartNumber": 1, "ETag": "first"}]
        self.stub.add_response("complete_multipart_upload", {}, {"Bucket": "bucket", "Key": "originals/id", "UploadId": upload_id, "MultipartUpload": {"Parts": list(reversed(parts))}})
        self.storage.complete_multipart_upload("originals/id", upload_id, parts)
        self.stub.add_response("abort_multipart_upload", {}, {"Bucket": "bucket", "Key": "originals/id", "UploadId": upload_id})
        self.storage.abort_multipart_upload("originals/id", upload_id)

    def test_presigned_expiry_and_invalid_parts(self):
        for method in (self.storage.generate_presigned_get_url, self.storage.generate_presigned_put_url):
            self.assertEqual(parse_qs(urlsplit(method("s3:key")).query)["X-Amz-Expires"], ["3600"])
            for expiry in (0, 604801, True):
                with self.assertRaises(ValueError):
                    method("key", expiry)
        with self.assertRaises(ValueError):
            self.storage.generate_multipart_presigned_urls("key", "upload", 10001)
        with self.assertRaises(ValueError):
            self.storage.complete_multipart_upload("key", "upload", [{"PartNumber": 1, "ETag": "a"}, {"PartNumber": 1, "ETag": "b"}])

    def test_integrity_hashes_content_instead_of_multipart_etag(self):
        content = b"document"
        digest = hashlib.md5(content, usedforsecurity=False).digest()
        for expected, result in ((base64.b64encode(digest).decode(), True), (digest.hex(), True), ("0" * 32, False)):
            body = io.BytesIO(content)
            self.stub.add_response("head_object", {"ContentLength": len(content), "ETag": '"multipart-2"'}, {"Bucket": "bucket", "Key": "key"})
            self.stub.add_response("get_object", {"Body": body}, {"Bucket": "bucket", "Key": "key"})
            self.assertEqual(self.storage.verify_file_integrity("key", expected, len(content)), result)
            self.assertTrue(body.closed)
        self.stub.add_response("head_object", {"ContentLength": 1}, {"Bucket": "bucket", "Key": "key"})
        self.assertFalse(self.storage.verify_file_integrity("key", expected_size=2))

    def test_missing_file_and_access_denied_are_distinct(self):
        for method, expected in ((self.storage.file_exists, False), (self.storage.get_file_size, None)):
            self.stub.add_client_error("head_object", service_error_code="404", http_status_code=404)
            self.assertEqual(method("key"), expected)
            self.stub.add_client_error("head_object", service_error_code="AccessDenied", http_status_code=403)
            with self.assertRaises(StorageError):
                method("key")

    def test_upload_download_delete_preserve_stored_keys(self):
        self.stub.add_response("put_object", {}, {"Bucket": "bucket", "Key": "originals/id", "Body": b"abc", "ContentType": "text/plain"})
        key = self.storage.put("id", b"abc", "text/plain")
        self.assertEqual(key, "s3:originals/id")
        self.storage.prefix = "changed"
        body = io.BytesIO(b"abc")
        self.stub.add_response("get_object", {"Body": body}, {"Bucket": "bucket", "Key": "originals/id"})
        self.assertEqual(self.storage.download_file(key), b"abc")
        self.assertTrue(body.closed)
        self.stub.add_response("delete_object", {}, {"Bucket": "bucket", "Key": "originals/id"})
        self.storage.delete(key)

    def test_delete_folder_paginates_and_keeps_prefix_boundary(self):
        for prefix in ("", "/", "s3:"):
            with self.assertRaises(ValueError):
                self.storage.delete_folder(prefix)
        self.stub.add_response("list_objects_v2", {"Contents": [{"Key": "jobs/1/a"}], "IsTruncated": True, "NextContinuationToken": "next"}, {"Bucket": "bucket", "Prefix": "jobs/1/"})
        self.stub.add_response("delete_object", {}, {"Bucket": "bucket", "Key": "jobs/1/a"})
        self.stub.add_response("list_objects_v2", {"Contents": [{"Key": "jobs/1/b"}], "IsTruncated": False}, {"Bucket": "bucket", "Prefix": "jobs/1/", "ContinuationToken": "next"})
        self.stub.add_response("delete_object", {}, {"Bucket": "bucket", "Key": "jobs/1/b"})
        self.assertEqual(self.storage.delete_folder("s3:jobs/1"), 2)

    def test_bucket_creation_only_when_missing(self):
        self.stub.add_client_error("head_bucket", service_error_code="404", http_status_code=404)
        self.stub.add_response("create_bucket", {}, {"Bucket": "bucket"})
        S3Storage("bucket", client=self.client, ensure_bucket=True)
        self.stub.add_client_error("head_bucket", service_error_code="AccessDenied", http_status_code=403)
        with self.assertRaises(StorageError):
            S3Storage("bucket", client=self.client, ensure_bucket=True)

    def test_external_download_filename_limit_and_errors(self):
        with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"pdf"))) as client:
            name, stream, mime = self.storage.download_external("https://files.test/download?token=secret", "application/pdf", client=client)["file"]
            self.assertEqual((name, stream.read(), mime), ("download.pdf", b"pdf", "application/pdf"))
            stream.close()
            with patch("backend.handler.storage.MAX_FILE_SIZE", 2), self.assertRaises(StorageError):
                self.storage.download_external("https://files.test/doc", "application/pdf", client=client)
        with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(302, headers={"Location": "https://other.test"}))) as client:
            with self.assertRaises(StorageError):
                self.storage.download_external("https://files.test/doc", "application/pdf", client=client)
        with self.assertRaises(ValueError):
            self.storage.download_external("file:///etc/passwd", "text/plain")
