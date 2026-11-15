"""Blob storage behind one small interface: Amazon S3 in real use, an in-memory store in tests.
Blobs are private (no public access, no shareable links): files are only ever served through the API, to their owner."""
import asyncio
import io
import logging
from typing import AsyncIterator, Dict, Optional

import config
from auth.store import Unavailable

log = logging.getLogger("sahaj.storage")
CHUNK = 256 * 1024
MULTIPART_AT = 8 * 1024 * 1024   # S3 multipart uploads start above this size, in parts of this size


class MemoryBlobStore:
    """For tests and for trying the API without S3. Everything is lost when the process ends."""

    def __init__(self):
        self.blobs: Dict[str, tuple] = {}

    async def put(self, name: str, data: bytes, content_type: str) -> None:
        if name in self.blobs:
            raise FileExistsError(name)
        self.blobs[name] = (data, content_type)

    async def stream(self, name: str) -> AsyncIterator[bytes]:
        data, _ = self.blobs[name]
        for i in range(0, len(data), CHUNK):
            yield data[i:i + CHUNK]

    async def delete(self, name: str) -> None:
        self.blobs.pop(name, None)

    async def delete_prefix(self, prefix: str) -> int:
        names = [n for n in self.blobs if n.startswith(prefix)]
        for n in names:
            del self.blobs[n]
        return len(names)

    async def ready(self) -> bool:
        return True

    async def close(self) -> None:
        pass


class S3BlobStore:
    """Amazon S3. Credentials come from the standard AWS chain (environment variables, ~/.aws profile or SSO, or an IAM
    role on the server), never from this code. boto3 is blocking, so each call runs in a worker thread.

    Objects are encrypted at rest (SSE-S3), never overwritten, and erased for good: deleting removes every version and
    delete marker, so a bucket with versioning on cannot keep a withdrawn person's file behind."""

    def __init__(self, client, bucket: str):
        self._s3 = client
        self._bucket = bucket

    @classmethod
    def from_config(cls) -> "S3BlobStore":
        if not config.AWS_S3_BUCKET:
            raise Unavailable("File storage is disabled: set AWS_S3_BUCKET (and AWS credentials).")
        import boto3
        from botocore.config import Config
        keys = ({"aws_access_key_id": config.S3_ACCESS_KEY, "aws_secret_access_key": config.S3_SECRET_KEY}
                if config.S3_ACCESS_KEY and config.S3_SECRET_KEY else {})
        session = boto3.session.Session(profile_name=None if keys else (config.AWS_PROFILE or None),
                                        region_name=config.AWS_REGION, **keys)
        client = session.client("s3", endpoint_url=config.AWS_ENDPOINT_URL or None,
                                config=Config(retries={"max_attempts": 5, "mode": "standard"},
                                              s3={"addressing_style": "path" if config.AWS_ENDPOINT_URL else "auto"}))
        return cls(client, config.AWS_S3_BUCKET)

    async def put(self, name: str, data: bytes, content_type: str) -> None:
        """One request for small files; an S3 multipart upload (parallel 8 MB parts, finished or aborted as a whole) for
        anything larger. Either way the object is encrypted and an existing key is never overwritten."""
        from botocore.exceptions import ClientError

        def call():
            try:
                if len(data) <= MULTIPART_AT:
                    self._s3.put_object(Bucket=self._bucket, Key=name, Body=data, ContentType=content_type,
                                        ServerSideEncryption="AES256", IfNoneMatch="*")   # IfNoneMatch: never overwrite
                    return
                try:
                    self._s3.head_object(Bucket=self._bucket, Key=name)
                    raise FileExistsError(name)
                except ClientError as e:
                    if e.response["Error"]["Code"] not in ("404", "NoSuchKey", "NotFound"):
                        raise
                from boto3.s3.transfer import TransferConfig
                self._s3.upload_fileobj(
                    io.BytesIO(data), self._bucket, name,
                    ExtraArgs={"ContentType": content_type, "ServerSideEncryption": "AES256"},
                    Config=TransferConfig(multipart_threshold=MULTIPART_AT, multipart_chunksize=MULTIPART_AT, max_concurrency=4))
            except ClientError as e:
                if e.response["Error"]["Code"] in ("PreconditionFailed", "ConditionalRequestConflict"):
                    raise FileExistsError(name) from e
                raise
        await asyncio.to_thread(call)

    async def stream(self, name: str) -> AsyncIterator[bytes]:
        body = (await asyncio.to_thread(self._s3.get_object, Bucket=self._bucket, Key=name))["Body"]
        chunks = body.iter_chunks(CHUNK)
        try:
            while (chunk := await asyncio.to_thread(next, chunks, None)) is not None:
                yield chunk
        finally:
            await asyncio.to_thread(body.close)

    def _versions(self, prefix: str, exact: bool):
        """Every version and delete marker under a prefix, as {"Key", "VersionId"} (a bucket without versioning
        reports each object once with VersionId "null")."""
        for page in self._s3.get_paginator("list_object_versions").paginate(Bucket=self._bucket, Prefix=prefix):
            for item in [*page.get("Versions", []), *page.get("DeleteMarkers", [])]:
                if not exact or item["Key"] == prefix:
                    yield {"Key": item["Key"], "VersionId": item["VersionId"]}

    def _remove(self, prefix: str, exact: bool) -> int:
        # List everything BEFORE deleting: deleting while paging through a listing can make the pages skip objects.
        items = list(self._versions(prefix, exact))
        for i in range(0, len(items), 1000):   # S3 deletes at most 1000 keys per request
            result = self._s3.delete_objects(Bucket=self._bucket, Delete={"Objects": items[i:i + 1000], "Quiet": True})
            if result.get("Errors"):
                raise OSError(f"S3 could not delete {len(result['Errors'])} object(s): {result['Errors'][0].get('Message')}")
        return len({item["Key"] for item in items})

    async def delete(self, name: str) -> None:
        await asyncio.to_thread(self._remove, name, True)

    async def delete_prefix(self, prefix: str) -> int:
        return await asyncio.to_thread(self._remove, prefix, False)

    async def ready(self) -> bool:
        try:
            await asyncio.to_thread(self._s3.head_bucket, Bucket=self._bucket)
            return True
        except Exception as e:
            log.warning("Blob storage not ready: %s", e)
            return False

    async def close(self) -> None:
        self._s3.close()

_store = None


def get():
    """The configured store. Raises Unavailable (a 503) when storage is not set up."""
    global _store
    if _store is None:
        _store = S3BlobStore.from_config()
    return _store


def use(store: Optional[object]) -> None:
    """Replace the store (tests, or code that wants its own)."""
    global _store
    _store = store


async def close() -> None:
    global _store
    if _store is not None:
        await _store.close()
        _store = None
