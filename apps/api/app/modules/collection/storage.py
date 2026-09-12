"""Raw object store for archived content.

Two backends behind one interface:
- filesystem: local directory (default; used on-prem without MinIO and in tests).
- minio: S3-compatible object store (compose/production).

Storage is content-addressed by hash, so identical content never duplicates on
disk and each distinct version lands at its own key.
"""
from __future__ import annotations

import os
from pathlib import Path

from app.core.config import get_settings


class RawStore:
    def key_for(self, source_id: str, content_hash: str) -> str:
        return f"{source_id}/{content_hash[:2]}/{content_hash}.raw"

    def put(self, key: str, data: bytes, content_type: str | None = None) -> str:
        raise NotImplementedError

    def get(self, key: str) -> bytes:
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        raise NotImplementedError


class FilesystemRawStore(RawStore):
    def __init__(self, root: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / key

    def put(self, key: str, data: bytes, content_type: str | None = None) -> str:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        # Content-addressed: if it already exists with same content, keep it.
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, p)
        return key

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


class MinioRawStore(RawStore):
    def __init__(self):
        from minio import Minio

        s = get_settings()
        self._bucket = s.minio_bucket_raw
        self._client = Minio(
            s.minio_endpoint,
            access_key=s.minio_access_key,
            secret_key=s.minio_secret_key,
            secure=s.minio_secure,
        )
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)

    def put(self, key: str, data: bytes, content_type: str | None = None) -> str:
        import io

        self._client.put_object(
            self._bucket,
            key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type or "application/octet-stream",
        )
        return key

    def get(self, key: str) -> bytes:
        resp = self._client.get_object(self._bucket, key)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    def exists(self, key: str) -> bool:
        from minio.error import S3Error

        try:
            self._client.stat_object(self._bucket, key)
            return True
        except S3Error:
            return False


_store: RawStore | None = None


def get_store() -> RawStore:
    global _store
    if _store is None:
        s = get_settings()
        _store = (
            MinioRawStore() if s.raw_store_backend == "minio"
            else FilesystemRawStore(s.raw_store_fs_path)
        )
    return _store


def reset_store() -> None:
    global _store
    _store = None
