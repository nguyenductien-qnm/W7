import base64
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from email import policy
from email.parser import BytesParser

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.config import Config
from tool_contract import is_tool_event, tool_name_from_event, tool_payload, tool_response


DEMO_USER_ID = "demo"
READY_AFTER_SECONDS = 4

TABLE_NAME = os.environ.get("DOCUMENTS_TABLE", "StudyBotDocuments")
AWS_REGION = os.environ.get("AWS_REGION", "ap-southeast-1")
DDB_ENDPOINT_URL = os.environ.get("DDB_ENDPOINT_URL")
UPLOADS_BUCKET_NAME = os.environ.get("UPLOADS_BUCKET_NAME", "")
BEDROCK_KNOWLEDGE_BASE_ID = os.environ.get("BEDROCK_KNOWLEDGE_BASE_ID", "")
BEDROCK_DATA_SOURCE_ID = os.environ.get("BEDROCK_DATA_SOURCE_ID", "")
VECTOR_INDEX_ARN = os.environ.get("VECTOR_INDEX_ARN", "")
INGESTION_MODE = os.environ.get("INGESTION_MODE", "mock").lower()


def _dynamodb_resource():
    kwargs = {"region_name": AWS_REGION}
    if DDB_ENDPOINT_URL:
        kwargs["endpoint_url"] = DDB_ENDPOINT_URL
        kwargs["aws_access_key_id"] = os.environ.get("AWS_ACCESS_KEY_ID", "dummy")
        kwargs["aws_secret_access_key"] = os.environ.get("AWS_SECRET_ACCESS_KEY", "dummy")
    return boto3.resource("dynamodb", **kwargs)


TABLE = _dynamodb_resource().Table(TABLE_NAME)


def _s3_client():
    kwargs = {
        "region_name": AWS_REGION,
        "config": Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
    }
    if DDB_ENDPOINT_URL:
        # Keep local override behavior consistent when custom credentials are injected.
        kwargs["aws_access_key_id"] = os.environ.get("AWS_ACCESS_KEY_ID", "dummy")
        kwargs["aws_secret_access_key"] = os.environ.get("AWS_SECRET_ACCESS_KEY", "dummy")
    else:
        kwargs["endpoint_url"] = f"https://s3.{AWS_REGION}.amazonaws.com"
    return boto3.client("s3", **kwargs)


S3 = _s3_client()
BEDROCK_AGENT = boto3.client("bedrock-agent", region_name=AWS_REGION)


def now_epoch():
    return int(time.time())


def now_iso():
    # Millisecond precision reduces SK collision risk for timestamp-derived keys.
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def cors_headers():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type,Authorization,X-User-Id,X-Session-Id",
        "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
    }


def _json_default(value):
    if isinstance(value, Decimal):
        if value % 1 == 0:
            return int(value)
        return float(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json", **cors_headers()},
        "body": json.dumps(body, default=_json_default),
    }


def parse_json_body(event):
    raw_body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw_body = base64.b64decode(raw_body).decode("utf-8")
    try:
        return json.loads(raw_body)
    except json.JSONDecodeError:
        return {}


def parse_upload_body(event):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    content_type = headers.get("content-type", "")
    body = event.get("body", "")

    if "multipart/form-data" not in content_type:
        data = parse_json_body(event)
        title = data.get("title") or data.get("file_name") or "uploaded.pdf"
        user_id = data.get("user_id") or DEMO_USER_ID
        session_id = data.get("session_id") or data.get("active_session_id") or "default"
        return title, user_id, str(session_id)

    raw_bytes = base64.b64decode(body) if event.get("isBase64Encoded") else body.encode("utf-8")
    parser_input = f"Content-Type: {content_type}\nMIME-Version: 1.0\n\n".encode("utf-8") + raw_bytes
    message = BytesParser(policy=policy.default).parsebytes(parser_input)

    title = "uploaded.pdf"
    user_id = DEMO_USER_ID
    session_id = "default"

    for part in message.iter_parts():
        content_disposition = part.get("Content-Disposition", "")
        if "form-data" not in content_disposition:
            continue
        name = part.get_param("name", header="Content-Disposition")
        if name == "file":
            title = part.get_filename() or title
        elif name == "user_id":
            user_id = (part.get_content() or "").strip() or DEMO_USER_ID
        elif name == "session_id":
            session_id = (part.get_content() or "").strip() or "default"

    return title, user_id, session_id


def get_user_id(event, payload=None):
    payload = payload or {}
    if payload.get("user_id"):
        return payload.get("user_id")

    query = event.get("queryStringParameters") or {}
    if query.get("user_id"):
        return query.get("user_id")

    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    if headers.get("x-user-id"):
        return headers.get("x-user-id")

    return DEMO_USER_ID


def get_session_id(event, payload=None):
    payload = payload or {}
    session_id = payload.get("session_id") or payload.get("active_session_id")
    if session_id:
        return str(session_id)

    query = event.get("queryStringParameters") or {}
    if query.get("session_id"):
        return str(query.get("session_id"))

    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    if headers.get("x-session-id"):
        return str(headers.get("x-session-id"))

    return ""


def doc_in_session(doc_item, session_id):
    if not session_id:
        return True
    doc_session_id = str(doc_item.get("session_id") or "default")
    if session_id == "default":
        return doc_session_id in ("", "default")
    return doc_session_id == session_id


def safe_filename(name):
    cleaned = re.sub(r"[^a-zA-Z0-9._-]", "_", (name or "").strip())
    return cleaned or "uploaded.pdf"


def raw_document_key(user_id, session_id, doc_id, filename):
    return f"raw/{user_id}/{session_id or 'default'}/{doc_id}/{safe_filename(filename)}"


def use_bedrock_ingestion():
    return (
        INGESTION_MODE == "bedrock"
        and bool(BEDROCK_KNOWLEDGE_BASE_ID)
        and bool(BEDROCK_DATA_SOURCE_ID)
    )


def start_kb_ingestion():
    response_data = BEDROCK_AGENT.start_ingestion_job(
        knowledgeBaseId=BEDROCK_KNOWLEDGE_BASE_ID,
        dataSourceId=BEDROCK_DATA_SOURCE_ID,
        clientToken=str(uuid.uuid4()),
        description="StudyBot document ingestion trigger",
    )
    return response_data.get("ingestionJob", {})


def map_ingestion_status_to_kb(status):
    status_map = {
        "STARTING": "PROCESSING",
        "IN_PROGRESS": "PROCESSING",
        "COMPLETE": "READY",
        "FAILED": "FAILED",
        "STOPPING": "PROCESSING",
        "STOPPED": "FAILED",
    }
    return status_map.get(str(status or "").upper(), "PROCESSING")


def refresh_doc_status_from_ingestion(doc_item):
    if not doc_item:
        return None
    ingestion_job_id = doc_item.get("ingestion_job_id")
    if not ingestion_job_id:
        return doc_item

    if not use_bedrock_ingestion():
        return doc_item

    try:
        response_data = BEDROCK_AGENT.get_ingestion_job(
            knowledgeBaseId=BEDROCK_KNOWLEDGE_BASE_ID,
            dataSourceId=BEDROCK_DATA_SOURCE_ID,
            ingestionJobId=ingestion_job_id,
        )
        ingestion_job = response_data.get("ingestionJob", {})
        ingestion_status = str(ingestion_job.get("status", "IN_PROGRESS")).upper()
        kb_status = map_ingestion_status_to_kb(ingestion_status)
        processed_key = str(doc_item.get("processed_text_s3_key") or doc_item.get("processed_s3_key") or "")
        failure_reasons = ingestion_job.get("failureReasons") or []
        failure_text = "\n".join(str(reason) for reason in failure_reasons)
        if ingestion_status == "COMPLETE" and processed_key and processed_key in failure_text:
            kb_status = "FAILED"

        updated_doc = {
            **doc_item,
            "ingestion_status": ingestion_status,
            "kb_status": kb_status,
            "ingestion_updated_at": now_iso(),
        }
        if kb_status == "FAILED" and failure_text:
            updated_doc["failure_reason"] = failure_text[:1000]
        TABLE.put_item(Item=updated_doc)

        return updated_doc
    except Exception:
        return doc_item


def pk_user(user_id):
    return f"USER#{user_id}"


def pk_email(email):
    return f"EMAIL#{str(email or '').strip().lower()}"


def sk_profile():
    return "PROFILE"


def sk_profile_email():
    return "PROFILE_EMAIL"


def sk_doc(doc_id):
    return f"DOC#{doc_id}"


def sk_session(session_id):
    return f"SESSION#{session_id}"


def sk_summary(doc_id):
    return f"DOC#{doc_id}#SUMMARY#LATEST"


def sk_quiz(doc_id):
    return f"DOC#{doc_id}#QUIZ#LATEST"


def _event_suffix(event_id=None):
    return str(event_id or uuid.uuid4().hex[:10])


def sk_question(created_at_iso, event_id=None):
    return f"QUESTION#{created_at_iso}#{_event_suffix(event_id)}"


def sk_summary_history(doc_id, created_at_iso, event_id=None):
    return f"DOC#{doc_id}#SUMMARY#TS#{created_at_iso}#{_event_suffix(event_id)}"


def sk_quiz_history(doc_id, created_at_iso, event_id=None):
    return f"DOC#{doc_id}#QUIZ#TS#{created_at_iso}#{_event_suffix(event_id)}"


def doc_id_from_sk(sk_value):
    match = re.match(r"^DOC#([^#]+)$", sk_value or "")
    return match.group(1) if match else ""


def concepts_for(title):
    seed = (title or "").lower()
    if "distributed" in seed or "cap" in seed:
        return [
            "CAP theorem",
            "Replication",
            "Consistency model",
            "Quorum",
            "Partition tolerance",
        ]
    return ["Core idea", "Trade-offs", "Architecture", "Reliability", "Performance"]


def testable_concepts_for(concepts):
    if not concepts:
        return [
            "CAP theorem",
            "Leader-based replication",
            "Eventual consistency",
            "Quorum read/write",
            "Failure recovery",
        ]

    mapping = {
        "Replication": "Leader-based replication",
        "Consistency model": "Eventual consistency",
        "Quorum": "Quorum read/write",
        "Partition tolerance": "Failure recovery",
    }
    out = []
    for concept in concepts:
        out.append(mapping.get(concept, concept))
    return out[:5]


def summary_text_for(title):
    return (
        f"{title} explains distributed systems foundations including consistency, replication, and failure handling. "
        "It emphasizes practical trade-offs for real-world system design."
    )


def ensure_profile(user_id, email):
    normalized_email = str(email or "").strip().lower()
    profile = TABLE.get_item(Key={"PK": pk_user(user_id), "SK": sk_profile()}).get("Item")
    if profile:
        if normalized_email:
            TABLE.put_item(
                Item={
                    "PK": pk_email(normalized_email),
                    "SK": sk_profile_email(),
                    "user_id": user_id,
                    "email": normalized_email,
                    "updated_at": now_iso(),
                }
            )
        return profile

    item = {
        "PK": pk_user(user_id),
        "SK": sk_profile(),
        "user_id": user_id,
        "email": normalized_email or email,
        "created_at": now_iso(),
    }
    TABLE.put_item(Item=item)
    if normalized_email:
        TABLE.put_item(
            Item={
                "PK": pk_email(normalized_email),
                "SK": sk_profile_email(),
                "user_id": user_id,
                "email": normalized_email,
                "created_at": item["created_at"],
                "updated_at": item["created_at"],
            }
        )
    return item


def find_profile_by_email(email):
    normalized_email = str(email or "").strip().lower()
    if not normalized_email:
        return None

    email_index = TABLE.get_item(
        Key={
            "PK": pk_email(normalized_email),
            "SK": sk_profile_email(),
        }
    ).get("Item")
    if email_index and email_index.get("user_id"):
        user_id = str(email_index["user_id"])
        profile = TABLE.get_item(Key={"PK": pk_user(user_id), "SK": sk_profile()}).get("Item")
        if profile:
            return profile

    response_data = TABLE.scan(
        FilterExpression=Attr("SK").eq(sk_profile()) & Attr("email").eq(normalized_email)
    )
    items = response_data.get("Items", [])

    while response_data.get("LastEvaluatedKey"):
        response_data = TABLE.scan(
            FilterExpression=Attr("SK").eq(sk_profile()) & Attr("email").eq(normalized_email),
            ExclusiveStartKey=response_data["LastEvaluatedKey"],
        )
        items.extend(response_data.get("Items", []))

    return items[0] if items else None


def get_doc(user_id, doc_id):
    return TABLE.get_item(Key={"PK": pk_user(user_id), "SK": sk_doc(doc_id)}).get("Item")


def get_session(user_id, session_id):
    return TABLE.get_item(Key={"PK": pk_user(user_id), "SK": sk_session(session_id)}).get("Item")


def get_summary(user_id, doc_id):
    return TABLE.get_item(Key={"PK": pk_user(user_id), "SK": sk_summary(doc_id)}).get("Item")


def get_quiz(user_id, doc_id):
    return TABLE.get_item(Key={"PK": pk_user(user_id), "SK": sk_quiz(doc_id)}).get("Item")


def list_user_items(user_id):
    result = TABLE.query(KeyConditionExpression=Key("PK").eq(pk_user(user_id)))
    items = result.get("Items", [])
    while result.get("LastEvaluatedKey"):
        result = TABLE.query(
            KeyConditionExpression=Key("PK").eq(pk_user(user_id)),
            ExclusiveStartKey=result["LastEvaluatedKey"],
        )
        items.extend(result.get("Items", []))
    return items


def public_session(item):
    session_id = item.get("session_id", "default")
    session_name = item.get("session_name", "Study Session")
    return {
        "session_id": session_id,
        "id": session_id,
        "session_name": session_name,
        "name": session_name,
        "created_at": item.get("created_at", ""),
        "updated_at": item.get("updated_at", ""),
    }


def ensure_session(user_id, session_id="default", session_name=None):
    session_id = str(session_id or "default")
    existing = get_session(user_id, session_id)
    if existing:
        return existing

    created_at = now_iso()
    item = {
        "PK": pk_user(user_id),
        "SK": sk_session(session_id),
        "session_id": session_id,
        "session_name": session_name or ("Default Session" if session_id == "default" else "New Session"),
        "created_at": created_at,
        "updated_at": created_at,
    }
    TABLE.put_item(Item=item)
    return item


def list_sessions(user_id):
    ensure_session(user_id, "default", "Default Session")
    items = [
        item for item in list_user_items(user_id)
        if str(item.get("SK", "")).startswith("SESSION#")
    ]
    items.sort(key=lambda x: x.get("updated_at") or x.get("created_at", ""), reverse=True)
    return items


def list_documents(user_id):
    items = list_user_items(user_id)
    docs = []
    for item in items:
        doc_id = doc_id_from_sk(item.get("SK", ""))
        if doc_id:
            docs.append(item)
    docs.sort(key=lambda x: x.get("uploaded_at", ""), reverse=True)
    return docs


def ensure_document_ready(user_id, doc_id):
    doc_item = get_doc(user_id, doc_id)
    if not doc_item:
        return None

    if use_bedrock_ingestion():
        return refresh_doc_status_from_ingestion(doc_item)

    if doc_item.get("kb_status") == "READY":
        return doc_item

    started_epoch = int(doc_item.get("processing_started_at_epoch", now_epoch()))
    if now_epoch() - started_epoch < READY_AFTER_SECONDS:
        return doc_item

    concepts = doc_item.get("concepts") or concepts_for(doc_item.get("title", "uploaded.pdf"))
    updated_doc = {
        **doc_item,
        "kb_status": "READY",
        "concepts": concepts,
    }
    TABLE.put_item(Item=updated_doc)

    return updated_doc


def collect_session_documents(user_id, session_id):
    docs = []
    for doc in list_documents(user_id):
        if not doc_in_session(doc, session_id):
            continue
        ensured = ensure_document_ready(user_id, doc.get("doc_id"))
        if ensured:
            docs.append(ensured)

    docs = [
        {
            "doc_id": item["doc_id"],
            "filename": item.get("title", "uploaded.pdf"),
            "name": item.get("title", "uploaded.pdf"),
            "title": item.get("title", "uploaded.pdf"),
            "status": "COMPLETE" if item.get("kb_status") == "READY" else item.get("kb_status", "PROCESSING"),
            "kb_status": item.get("kb_status", "PROCESSING"),
            "s3_key": item.get("s3_key", ""),
            "session_id": item.get("session_id", "default"),
        }
        for item in docs
    ]

    return docs


def normalize_doc_ids(payload):
    candidates = []
    if payload.get("doc_id"):
        candidates.append(payload.get("doc_id"))
    if isinstance(payload.get("doc_ids"), list):
        candidates.extend(payload.get("doc_ids"))
    if isinstance(payload.get("selected_doc_ids"), list):
        candidates.extend(payload.get("selected_doc_ids"))

    out = []
    seen = set()
    for item in candidates:
        value = str(item or "").strip()
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def normalize_quiz_count(value):
    try:
        return max(5, min(10, int(value or 5)))
    except (TypeError, ValueError):
        return 5


def get_selected_docs_for_session(user_id, selected_doc_ids, session_id):
    selected_docs = []
    forbidden_doc_ids = []
    missing_doc_ids = []

    for doc_id in selected_doc_ids:
        doc_item = ensure_document_ready(user_id, doc_id)
        if not doc_item:
            missing_doc_ids.append(doc_id)
            continue
        if not doc_in_session(doc_item, session_id):
            forbidden_doc_ids.append(doc_id)
            continue
        selected_docs.append(doc_item)

    if forbidden_doc_ids:
        return None, response(
            403,
            {
                "message": "Selected documents must belong to the active session",
                "forbidden_doc_ids": forbidden_doc_ids,
            },
        )
    if not selected_docs:
        return None, response(404, {"message": "No selected documents were found", "missing_doc_ids": missing_doc_ids})
    return selected_docs, None


def lambda_handler(event, _context):
    try:
        if is_tool_event(event):
            name = tool_name_from_event(event, "")
            payload = tool_payload(event)
            if name == "list_documents":
                user_id = str(payload.get("user_id") or "")
                session_id = str(payload.get("session_id") or "default")
                ensure_session(user_id, session_id)
                docs = collect_session_documents(user_id, session_id)
                return tool_response("list_documents", "success", data={"documents": docs, "docs": docs})
            return tool_response(name or "unknown", "error", errors=[f"Unsupported app tool: {name}"])
        request_context = event.get("requestContext", {})
        http_info = request_context.get("http", {})
        method = http_info.get("method") or event.get("httpMethod", "")
        if method == "OPTIONS":
            return {"statusCode": 204, "headers": cors_headers(), "body": ""}
        return response(404, {"message": "This lambda now serves only AgentCore list_documents tool."})
    except Exception as exc:
        return response(500, {"message": "Internal server error", "error": str(exc)})
