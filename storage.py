from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..settings import get_settings


class ObjectStorage:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = None
        try:
            import boto3

            options: dict[str, Any] = {"region_name": self.settings.s3_region}
            if self.settings.s3_endpoint_url:
                options["endpoint_url"] = self.settings.s3_endpoint_url
            if self.settings.s3_access_key and self.settings.s3_secret_key:
                options["aws_access_key_id"] = self.settings.s3_access_key
                options["aws_secret_access_key"] = self.settings.s3_secret_key
            self._client = boto3.client("s3", **options)
        except Exception:
            self._client = None

    def put_bytes(self, key: str, body: bytes, content_type: str = "application/octet-stream") -> str:
        if self._client is not None:
            try:
                self._client.put_object(Bucket=self.settings.s3_bucket, Key=key, Body=body, ContentType=content_type)
                return f"s3://{self.settings.s3_bucket}/{key}"
            except Exception:
                self._client = None
        target = Path("artifacts/object-storage") / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        return str(target)

    def put_json(self, key: str, value: Any) -> str:
        return self.put_bytes(key, json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"), "application/json")

