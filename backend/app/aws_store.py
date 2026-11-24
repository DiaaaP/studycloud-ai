"""AWS persistence primitives for StudyCloud's serverless deployment.

Local development continues to use SQLite. In AWS mode, account and learning
records live in one DynamoDB table and private source material lives in S3.
"""

from __future__ import annotations

import hashlib
import json
import os
from functools import cached_property
from typing import Any
from urllib.parse import quote

import boto3
from boto3.dynamodb.conditions import Attr


def enabled() -> bool:
    return os.getenv("STUDYCLOUD_STORAGE_BACKEND", "sqlite").strip().lower() == "aws"


def _normalized(value: str) -> str:
    return value.strip().casefold()


def _lookup_key(kind: str, value: str) -> dict[str, str]:
    digest = hashlib.sha256(_normalized(value).encode("utf-8")).hexdigest()
    return {"PK": f"LOGIN#{kind}#{digest}", "SK": "OWNER"}


class AwsStore:
    def __init__(self) -> None:
        self.region = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "ap-southeast-2"))
        self.table_name = os.environ["STUDYCLOUD_TABLE_NAME"]
        self.bucket = os.environ["STUDYCLOUD_DOCUMENTS_BUCKET"]
        session = boto3.session.Session(region_name=self.region)
        self.dynamodb = session.resource("dynamodb")
        self.table = self.dynamodb.Table(self.table_name)
        self.s3 = session.client("s3")

    @cached_property
    def dynamodb_client(self):
        # The resource client retains boto3's native Python type marshalling.
        return self.table.meta.client

    @staticmethod
    def user_pk(user_id: str) -> str:
        return f"USER#{user_id}"

    @staticmethod
    def lecture_sk(lecture_id: str) -> str:
        return f"LECTURE#{lecture_id}"

    @staticmethod
    def _to_native(item: dict[str, Any]) -> dict[str, Any]:
        """Convert response values that JSON does not support (e.g. Decimal)."""
        from decimal import Decimal

        def convert(value: Any) -> Any:
            if isinstance(value, Decimal):
                return int(value) if value % 1 == 0 else float(value)
            if isinstance(value, dict):
                return {key: convert(child) for key, child in value.items()}
            if isinstance(value, list):
                return [convert(child) for child in value]
            return value

        return convert(item)

    def get_item(self, pk: str, sk: str) -> dict[str, Any] | None:
        return self.table.get_item(Key={"PK": pk, "SK": sk}, ConsistentRead=True).get("Item")

    def query_user(self, user_id: str, sort_prefix: str | None = None) -> list[dict[str, Any]]:
        partition = self.user_pk(user_id)
        paginator = self.dynamodb_client.get_paginator("query")
        expression = "PK = :pk"
        values = {":pk": partition}
        if sort_prefix:
            expression += " AND begins_with(SK, :prefix)"
            values[":prefix"] = sort_prefix
        pages = paginator.paginate(
            TableName=self.table_name,
            KeyConditionExpression=expression,
            ExpressionAttributeValues=values,
            ConsistentRead=True,
        )
        return [self._to_native(item) for item in pages.search("Items[]")]

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        item = self.get_item(self.user_pk(user_id), "PROFILE")
        return self._to_native(item) if item else None

    def get_user_by_login(self, username_or_email: str) -> dict[str, Any] | None:
        value = username_or_email.strip()
        kind = "EMAIL" if "@" in value else "USERNAME"
        lookup_key = _lookup_key(kind, value)
        lookup = self.get_item(lookup_key["PK"], lookup_key["SK"])
        if not lookup:
            return None
        return self.get_user(lookup["user_id"])

    def create_user(self, user: dict[str, Any]) -> None:
        user_id = str(user["id"])
        profile = {
            **user,
            "PK": self.user_pk(user_id),
            "SK": "PROFILE",
            "record_type": "USER",
        }
        username_lookup = {**_lookup_key("USERNAME", user["username"]), "user_id": user_id, "record_type": "LOGIN"}
        email_lookup = {**_lookup_key("EMAIL", user["email"]), "user_id": user_id, "record_type": "LOGIN"}
        try:
            self.dynamodb_client.transact_write_items(
                TransactItems=[
                    {
                        "Put": {
                            "TableName": self.table_name,
                            "Item": item,
                            "ConditionExpression": "attribute_not_exists(PK)",
                        }
                    }
                    for item in (profile, username_lookup, email_lookup)
                ]
            )
        except self.dynamodb_client.exceptions.TransactionCanceledException as error:
            if self.get_item(username_lookup["PK"], username_lookup["SK"]):
                raise DuplicateAccountValue("username") from error
            if self.get_item(email_lookup["PK"], email_lookup["SK"]):
                raise DuplicateAccountValue("email") from error
            raise

    def get_lecture_item(self, user_id: str, lecture_id: str, allow_demo: bool = True) -> dict[str, Any] | None:
        item = self.get_item(self.user_pk(user_id), self.lecture_sk(lecture_id))
        if item is None and allow_demo and lecture_id == "demo-raft":
            item = self.get_item("DEMO", self.lecture_sk("demo-raft"))
        return self._to_native(item) if item else None

    def list_lectures(self, user_id: str) -> list[dict[str, Any]]:
        items = self.query_user(user_id, "LECTURE#")
        demo = self.get_item("DEMO", self.lecture_sk("demo-raft"))
        if demo:
            items.append(self._to_native(demo))
        return sorted(items, key=lambda item: item.get("created_at", ""), reverse=True)

    def save_lecture(self, item: dict[str, Any]) -> None:
        lecture = dict(item)
        user_id = str(lecture["owner_id"])
        lecture_id = str(lecture["id"])
        lecture["PK"] = self.user_pk(user_id)
        lecture["SK"] = self.lecture_sk(lecture_id)
        lecture["record_type"] = "LECTURE"
        self.table.put_item(Item=lecture)

    def update_lecture(self, user_id: str, lecture_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
        current = self.get_lecture_item(user_id, lecture_id, allow_demo=False)
        if not current:
            return None
        current.update(values)
        self.table.put_item(
            Item={**current, "PK": self.user_pk(user_id), "SK": self.lecture_sk(lecture_id), "record_type": "LECTURE"}
        )
        return self.get_lecture_item(user_id, lecture_id, allow_demo=False)

    def get_content(self, key: str) -> dict[str, Any]:
        response = self.s3.get_object(Bucket=self.bucket, Key=key)
        with response["Body"] as body:
            return json.loads(body.read().decode("utf-8"))

    def put_content(self, key: str, content: dict[str, Any]) -> None:
        body = json.dumps(content, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType="application/json; charset=utf-8",
            ServerSideEncryption="AES256",
        )

    def original_key(self, user_id: str, lecture_id: str, extension: str) -> str:
        return f"uploads/{user_id}/{lecture_id}/{extension.lstrip('.').lower()}"

    def extracted_key(self, user_id: str, lecture_id: str) -> str:
        return f"extracted/{user_id}/{lecture_id}/content.json"

    def create_upload_form(
        self,
        key: str,
        content_type: str,
        max_bytes: int,
        expires_seconds: int = 600,
    ) -> dict[str, Any]:
        return self.s3.generate_presigned_post(
            Bucket=self.bucket,
            Key=key,
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type},
                ["content-length-range", 1, max_bytes],
            ],
            ExpiresIn=expires_seconds,
        )

    def create_download_url(self, key: str, filename: str, expires_seconds: int = 300) -> str:
        return self.s3.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ResponseContentDisposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}",
            },
            ExpiresIn=expires_seconds,
        )

    def put_record(self, item: dict[str, Any]) -> None:
        self.table.put_item(Item=item)

    def list_records(self, user_id: str, prefix: str) -> list[dict[str, Any]]:
        return self.query_user(user_id, prefix)

    def delete_user_records(self, user_id: str, prefix: str) -> None:
        for item in self.list_records(user_id, prefix):
            self.delete_record(item["PK"], item["SK"])

    @staticmethod
    def gap_id(lecture_id: str, concept: str) -> str:
        value = f"{lecture_id}\0{concept}".encode("utf-8")
        return hashlib.sha256(value).hexdigest()[:20]

    def get_gap(self, user_id: str, gap_id: str) -> dict[str, Any] | None:
        return next((item for item in self.list_records(user_id, "GAP#") if item.get("id") == gap_id), None)

    def save_gap(self, user_id: str, lecture_id: str, item: dict[str, Any]) -> None:
        gap_id = self.gap_id(lecture_id, str(item["concept"]))
        self.table.put_item(
            Item={
                **item,
                "PK": self.user_pk(user_id),
                "SK": f"GAP#{lecture_id}#{gap_id}",
                "id": gap_id,
                "user_id": user_id,
                "lecture_id": lecture_id,
                "record_type": "GAP",
            }
        )

    def save_attempt(self, user_id: str, item: dict[str, Any]) -> None:
        created_at = str(item["created_at"])
        attempt_id = str(item["id"])
        self.table.put_item(
            Item={
                **item,
                "PK": self.user_pk(user_id),
                "SK": f"ATTEMPT#{created_at}#{attempt_id}",
                "user_id": user_id,
                "record_type": "ATTEMPT",
            }
        )

    def delete_record(self, pk: str, sk: str) -> None:
        self.table.delete_item(Key={"PK": pk, "SK": sk})

    def delete_objects(self, keys: list[str]) -> None:
        if not keys:
            return
        self.s3.delete_objects(
            Bucket=self.bucket,
            Delete={"Objects": [{"Key": key} for key in keys], "Quiet": True},
        )

    def seed_demo(self, item: dict[str, Any], content: dict[str, Any]) -> None:
        if item.get("content_key"):
            self.put_content(item["content_key"], content)
        try:
            self.table.put_item(
                Item={**item, "PK": "DEMO", "SK": self.lecture_sk("demo-raft"), "record_type": "LECTURE"},
                ConditionExpression=Attr("PK").not_exists(),
            )
        except self.dynamodb_client.exceptions.ConditionalCheckFailedException:
            return


store: AwsStore | None = None


class DuplicateAccountValue(ValueError):
    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field = field


def get_store() -> AwsStore:
    global store
    if store is None:
        store = AwsStore()
    return store

