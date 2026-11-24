from __future__ import annotations

import logging
from pathlib import PurePosixPath
from urllib.parse import unquote_plus

from boto3.dynamodb.conditions import Attr

from backend.app.aws_store import get_store
from backend.app.main import extract_document

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _process_object(bucket: str, key: str) -> None:
    parts = PurePosixPath(key).parts
    if len(parts) != 4 or parts[0] != "uploads":
        logger.warning("Ignoring object outside the expected upload key layout")
        return
    _, user_id, lecture_id, extension = parts
    store = get_store()
    item = store.get_lecture_item(user_id, lecture_id, allow_demo=False)
    if not item:
        logger.warning("Ignoring upload without a matching lecture record")
        return
    if item.get("status") == "READY":
        return

    key_values = {"PK": store.user_pk(user_id), "SK": store.lecture_sk(lecture_id)}
    try:
        store.table.update_item(
            Key=key_values,
            UpdateExpression="SET #status = :processing",
            ConditionExpression=Attr("status").is_in(["UPLOADED", "FAILED"]),
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":processing": "PROCESSING"},
        )
    except store.dynamodb_client.exceptions.ConditionalCheckFailedException:
        return

    try:
        response = store.s3.get_object(Bucket=bucket, Key=key)
        with response["Body"] as body:
            contents = body.read()
        filename = f"upload.{extension}"
        text, units, chunks = extract_document(filename, contents)
        if not text.strip():
            raise ValueError("No readable text was found in the uploaded document")

        content_key = store.extracted_key(user_id, lecture_id)
        store.put_content(content_key, {"text": text, "source_chunks": chunks})
        store.table.update_item(
            Key=key_values,
            UpdateExpression="SET #status = :ready, pages = :pages, word_count = :words, content_key = :content_key",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":ready": "READY",
                ":pages": units,
                ":words": len(text.split()),
                ":content_key": content_key,
            },
        )
    except Exception as error:
        message = str(error).strip()[:240] or "Document processing failed"
        store.table.update_item(
            Key=key_values,
            UpdateExpression="SET #status = :failed, error_message = :message",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":failed": "FAILED", ":message": message},
        )
        logger.exception("Document processing failed for lecture %s", lecture_id)
        raise


def handler(event: dict, _context: object) -> dict[str, int]:
    processed = 0
    for record in event.get("Records", []):
        bucket = record.get("s3", {}).get("bucket", {}).get("name")
        key = unquote_plus(record.get("s3", {}).get("object", {}).get("key", ""))
        if bucket and key:
            _process_object(bucket, key)
            processed += 1
    return {"processed": processed}
