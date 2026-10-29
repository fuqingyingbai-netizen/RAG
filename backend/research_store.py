import os
import shutil
from pathlib import Path


class ResearchObjectStore:
    """Stores research artifacts in MinIO when configured, otherwise on local disk."""

    def __init__(self):
        self.mode = os.getenv("RESEARCH_OBJECT_STORE", "local").strip().lower()
        self.bucket = os.getenv("MINIO_BUCKET", "research")
        self.local_root = Path(os.getenv("RESEARCH_LOCAL_STORE", "data/research_store")).resolve()
        self._minio_client = None

    @staticmethod
    def validate_key(key: str) -> str:
        # Object keys are identifiers, never filesystem paths supplied by a client.
        if (not isinstance(key, str) or not key or any(ord(c) < 32 for c in key)
                or "\\" in key or ":" in key
                or any(part in {"", ".", ".."} for part in key.split("/"))):
            raise ValueError("Invalid storage key")
        return key

    @classmethod
    def project_key(cls, key: str, project_id: int) -> str:
        key = cls.validate_key(key)
        if not key.startswith(f"projects/{int(project_id)}/"):
            raise ValueError("Storage key does not belong to this project")
        return key

    def _local_path(self, key: str) -> Path:
        root = self.local_root.resolve()
        path = (root / self.validate_key(key)).resolve()
        if root not in path.parents:
            raise ValueError("Invalid storage path")
        return path

    def _client(self):
        if self.mode != "minio":
            return None
        if self._minio_client is None:
            try:
                from minio import Minio
            except ImportError as exc:
                raise RuntimeError("minio package is required when RESEARCH_OBJECT_STORE=minio") from exc
            endpoint = os.getenv("MINIO_ENDPOINT", "127.0.0.1:9000")
            access_key = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
            secret_key = os.getenv("MINIO_SECRET_KEY", "minioadmin")
            secure = os.getenv("MINIO_SECURE", "false").lower() == "true"
            self._minio_client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
            if not self._minio_client.bucket_exists(self.bucket):
                self._minio_client.make_bucket(self.bucket)
        return self._minio_client

    def put_text(self, key: str, content: str, content_type: str = "text/plain; charset=utf-8") -> str:
        return self.put_bytes(key, content.encode("utf-8"), content_type)

    def put_bytes(self, key: str, payload: bytes, content_type: str = "application/octet-stream") -> str:
        safe_key = self.validate_key(key)
        if self.mode == "minio":
            from io import BytesIO

            self._client().put_object(
                self.bucket,
                safe_key,
                BytesIO(payload),
                length=len(payload),
                content_type=content_type,
            )
            return safe_key

        path = self._local_path(safe_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return safe_key

    def get_bytes(self, key: str) -> bytes:
        safe_key = self.validate_key(key)
        if self.mode == "minio":
            response = self._client().get_object(self.bucket, safe_key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()
        return self._local_path(safe_key).read_bytes()

    def get_text(self, key: str) -> str:
        return self.get_bytes(key).decode("utf-8")

    def delete_object(self, key: str | None) -> None:
        if not key:
            return
        safe_key = self.validate_key(key)
        if self.mode == "minio":
            self._client().remove_object(self.bucket, safe_key)
            return
        path = self._local_path(safe_key)
        if path.is_file():
            path.unlink(missing_ok=True)

    def delete_prefix(self, prefix: str) -> None:
        if not prefix:
            return
        safe_prefix = self.validate_key(prefix)
        if self.mode == "minio":
            client = self._client()
            for item in client.list_objects(self.bucket, prefix=safe_prefix + "/", recursive=True):
                client.remove_object(self.bucket, item.object_name)
            return
        path = self._local_path(safe_prefix)
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)


research_store = ResearchObjectStore()
