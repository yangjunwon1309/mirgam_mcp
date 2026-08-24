"""S3 JSON persistence for a single user's conversation history."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from uuid import uuid4

import boto3
from botocore.exceptions import ClientError, EndpointConnectionError

from ..config import Settings
from ..schemas import Message, Thread, ThreadDocument


class ThreadStore:
    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
        )

    def ensure_bucket(self) -> None:
        """Wait briefly for SeaweedFS during a fresh Compose startup."""
        for attempt in range(20):
            try:
                self.client.head_bucket(Bucket=self.bucket)
                return
            except ClientError:
                try:
                    self.client.create_bucket(Bucket=self.bucket)
                    return
                except EndpointConnectionError:
                    pass
            except EndpointConnectionError:
                pass
            if attempt == 19:
                raise RuntimeError("SeaweedFS S3 is not reachable after 20 seconds")
            time.sleep(1)

    @staticmethod
    def _key(thread_id: str) -> str:
        return f"threads/{thread_id}.json"

    def load(self, thread_id: str) -> ThreadDocument:
        try:
            result = self.client.get_object(Bucket=self.bucket, Key=self._key(thread_id))
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
                raise KeyError(thread_id) from exc
            raise
        return ThreadDocument.model_validate_json(result["Body"].read())

    def create(self, first_message: str) -> ThreadDocument:
        now = datetime.now(UTC)
        return ThreadDocument(
            thread_id=str(uuid4()),
            title=first_message.strip().replace("\n", " ")[:60] or "새 대화",
            created_at=now,
            updated_at=now,
        )

    def save(self, document: ThreadDocument) -> None:
        document.updated_at = datetime.now(UTC)
        self.client.put_object(
            Bucket=self.bucket,
            Key=self._key(document.thread_id),
            Body=document.model_dump_json().encode(),
            ContentType="application/json",
        )

    def list(self) -> list[Thread]:
        objects = self.client.list_objects_v2(Bucket=self.bucket, Prefix="threads/").get(
            "Contents", []
        )
        threads: list[Thread] = []
        for item in objects:
            try:
                document = self.load(item["Key"].removeprefix("threads/").removesuffix(".json"))
                threads.append(
                    Thread(
                        thread_id=document.thread_id,
                        title=document.title,
                        updated_at=document.updated_at,
                    )
                )
            except (KeyError, ValueError):
                continue
        return sorted(threads, key=lambda thread: thread.updated_at, reverse=True)

    def delete(self, thread_id: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._key(thread_id))
