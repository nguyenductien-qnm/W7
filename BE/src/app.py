import base64
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser

import boto3
from boto3.dynamodb.conditions import Attr, Key


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
    kwargs = {"region_name": AWS_REGION}
    if DDB_ENDPOINT_URL:
        # Keep local override behavior consistent when custom credentials are injected.
        kwargs["aws_access_key_id"] = os.environ.get("AWS_ACCESS_KEY_ID", "dummy")
        kwargs["aws_secret_access_key"] = os.environ.get("AWS_SECRET_ACCESS_KEY", "dummy")
    return boto3.client("s3", **kwargs)


S3 = _s3_client()
BEDROCK_AGENT = boto3.client("bedrock-agent", region_name=AWS_REGION)


def now_epoch():
    return int(time.time())


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cors_headers():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type,Authorization,X-User-Id",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    }


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json", **cors_headers()},
        "body": json.dumps(body),
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
        return title, user_id

    raw_bytes = base64.b64decode(body) if event.get("isBase64Encoded") else body.encode("utf-8")
    parser_input = f"Content-Type: {content_type}\nMIME-Version: 1.0\n\n".encode("utf-8") + raw_bytes
    message = BytesParser(policy=policy.default).parsebytes(parser_input)

    title = "uploaded.pdf"
    user_id = DEMO_USER_ID

    for part in message.iter_parts():
        content_disposition = part.get("Content-Disposition", "")
        if "form-data" not in content_disposition:
            continue
        name = part.get_param("name", header="Content-Disposition")
        if name == "file":
            title = part.get_filename() or title
        elif name == "user_id":
            user_id = (part.get_content() or "").strip() or DEMO_USER_ID

    return title, user_id


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


def safe_filename(name):
    cleaned = re.sub(r"[^a-zA-Z0-9._-]", "_", (name or "").strip())
    return cleaned or "uploaded.pdf"


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

        updated_doc = {
            **doc_item,
            "ingestion_status": ingestion_status,
            "kb_status": kb_status,
            "ingestion_updated_at": now_iso(),
        }
        TABLE.put_item(Item=updated_doc)

        if kb_status == "READY":
            concepts = updated_doc.get("concepts") or concepts_for(updated_doc.get("title", "uploaded.pdf"))
            upsert_summary_item(
                user_id=updated_doc.get("PK", "").replace("USER#", "") or DEMO_USER_ID,
                doc_id=updated_doc.get("doc_id"),
                summary=summary_text_for(updated_doc.get("title", "uploaded.pdf")),
                testable_concepts=testable_concepts_for(concepts),
            )

        return updated_doc
    except Exception:
        return doc_item


def pk_user(user_id):
    return f"USER#{user_id}"


def sk_profile():
    return "PROFILE"


def sk_doc(doc_id):
    return f"DOC#{doc_id}"


def sk_summary(doc_id):
    return f"DOC#{doc_id}#SUMMARY"


def sk_quiz(doc_id):
    return f"DOC#{doc_id}#QUIZ"


def sk_question(created_at_iso):
    return f"QUESTION#{created_at_iso}"


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
    profile = TABLE.get_item(Key={"PK": pk_user(user_id), "SK": sk_profile()}).get("Item")
    if profile:
        return profile

    item = {
        "PK": pk_user(user_id),
        "SK": sk_profile(),
        "user_id": user_id,
        "email": email,
        "created_at": now_iso(),
    }
    TABLE.put_item(Item=item)
    return item


def find_profile_by_email(email):
    if not email:
        return None

    response_data = TABLE.scan(
        FilterExpression=Attr("SK").eq(sk_profile()) & Attr("email").eq(email)
    )
    items = response_data.get("Items", [])

    while response_data.get("LastEvaluatedKey"):
        response_data = TABLE.scan(
            FilterExpression=Attr("SK").eq(sk_profile()) & Attr("email").eq(email),
            ExclusiveStartKey=response_data["LastEvaluatedKey"],
        )
        items.extend(response_data.get("Items", []))

    return items[0] if items else None


def get_doc(user_id, doc_id):
    return TABLE.get_item(Key={"PK": pk_user(user_id), "SK": sk_doc(doc_id)}).get("Item")


def get_summary(user_id, doc_id):
    return TABLE.get_item(Key={"PK": pk_user(user_id), "SK": sk_summary(doc_id)}).get("Item")


def get_quiz(user_id, doc_id):
    return TABLE.get_item(Key={"PK": pk_user(user_id), "SK": sk_quiz(doc_id)}).get("Item")


def list_user_items(user_id):
    result = TABLE.query(KeyConditionExpression=Key("PK").eq(pk_user(user_id)))
    return result.get("Items", [])


def list_documents(user_id):
    items = list_user_items(user_id)
    docs = []
    for item in items:
        doc_id = doc_id_from_sk(item.get("SK", ""))
        if doc_id:
            docs.append(item)
    docs.sort(key=lambda x: x.get("uploaded_at", ""), reverse=True)
    return docs


def upsert_summary_item(user_id, doc_id, summary, testable_concepts):
    TABLE.put_item(
        Item={
            "PK": pk_user(user_id),
            "SK": sk_summary(doc_id),
            "doc_id": doc_id,
            "summary": summary,
            "testable_concepts": testable_concepts,
            "generated_at": now_iso(),
        }
    )


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

    upsert_summary_item(
        user_id=user_id,
        doc_id=doc_id,
        summary=summary_text_for(doc_item.get("title", "uploaded.pdf")),
        testable_concepts=testable_concepts_for(concepts),
    )

    return updated_doc


def handle_login(event):
    payload = parse_json_body(event)
    email = payload.get("email", "")
    profile = find_profile_by_email(email)
    if not profile:
        return response(401, {"message": "Invalid email"})

    user_id = profile.get("user_id") or str(profile.get("PK", "")).replace("USER#", "")
    if not user_id:
        user_id = DEMO_USER_ID

    return response(
        200,
        {
            "user_id": user_id,
            "token": "demo-token",
            "message": "Login success",
        },
    )


def handle_upload(event):
    title, user_id = parse_upload_body(event)
    ensure_profile(user_id, f"{user_id}@studybot.com")

    doc_id = f"doc_{str(now_epoch())[-6:]}"
    uploaded_at = now_iso()

    doc_item = {
        "PK": pk_user(user_id),
        "SK": sk_doc(doc_id),
        "doc_id": doc_id,
        "title": title,
        "s3_key": f"users/{user_id}/docs/{doc_id}.pdf",
        "kb_status": "PROCESSING",
        "uploaded_at": uploaded_at,
        "page_count": 40,
        "concepts": concepts_for(title),
        "processing_started_at_epoch": now_epoch(),
    }
    TABLE.put_item(Item=doc_item)

    return response(200, {"doc_id": doc_id, "status": "PROCESSING", "kb_status": "PROCESSING"})


def handle_upload_url(event):
    if not UPLOADS_BUCKET_NAME:
        return response(500, {"message": "UPLOADS_BUCKET_NAME is not configured"})

    payload = parse_json_body(event)
    user_id = get_user_id(event, payload)
    filename = safe_filename(payload.get("filename") or payload.get("title") or "uploaded.pdf")
    content_type = payload.get("content_type") or "application/octet-stream"
    doc_id = payload.get("doc_id") or f"doc_{uuid.uuid4().hex[:10]}"
    s3_key = payload.get("s3_key") or f"documents/{user_id}/{doc_id}/{filename}"

    ensure_profile(user_id, f"{user_id}@studybot.com")

    doc_item = {
        "PK": pk_user(user_id),
        "SK": sk_doc(doc_id),
        "doc_id": doc_id,
        "title": filename,
        "s3_key": s3_key,
        "kb_status": "UPLOADING",
        "uploaded_at": now_iso(),
        "page_count": 0,
        "concepts": concepts_for(filename),
    }
    TABLE.put_item(Item=doc_item)

    upload_url = S3.generate_presigned_url(
        ClientMethod="put_object",
        Params={
            "Bucket": UPLOADS_BUCKET_NAME,
            "Key": s3_key,
            "ContentType": content_type,
        },
        ExpiresIn=900,
        HttpMethod="PUT",
    )

    return response(
        200,
        {
            "doc_id": doc_id,
            "s3_key": s3_key,
            "upload_url": upload_url,
            "upload_method": "PUT",
            "headers": {"Content-Type": content_type},
            "complete_path": f"/documents/{doc_id}/complete",
        },
    )


def handle_upload_complete(event, doc_id):
    payload = parse_json_body(event)
    user_id = get_user_id(event, payload)
    doc_item = get_doc(user_id, doc_id)
    if not doc_item:
        return response(404, {"message": "Document not found"})

    updated = {
        **doc_item,
        "kb_status": "PROCESSING",
        "processing_started_at_epoch": now_epoch(),
    }

    ingestion_job_id = f"ing_{uuid.uuid4().hex[:10]}"
    ingestion_status = "IN_PROGRESS"
    if use_bedrock_ingestion():
        try:
            ingestion_job = start_kb_ingestion()
            ingestion_job_id = ingestion_job.get("ingestionJobId", ingestion_job_id)
            ingestion_status = str(ingestion_job.get("status", "STARTING")).upper()
        except Exception as exc:
            return response(500, {"message": "Failed to start Bedrock ingestion", "error": str(exc)})

    updated["ingestion_job_id"] = ingestion_job_id
    updated["ingestion_status"] = ingestion_status
    updated["ingestion_started_at"] = now_iso()
    TABLE.put_item(Item=updated)

    return response(
        200,
        {
            "doc_id": doc_id,
            "ingestion_job_id": ingestion_job_id,
            "ingestion_status": ingestion_status,
            "status": "PROCESSING",
            "kb_status": "PROCESSING",
        },
    )


def handle_documents_list(event):
    user_id = get_user_id(event)

    docs = []
    for doc in list_documents(user_id):
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
        }
        for item in docs
    ]

    return response(200, {"documents": docs, "docs": docs})


def handle_document_detail(event, doc_id):
    user_id = get_user_id(event)

    doc_item = ensure_document_ready(user_id, doc_id)
    if not doc_item:
        return response(404, {"message": "Document not found"})

    summary_item = get_summary(user_id, doc_id)

    return response(
        200,
        {
            "doc_id": doc_id,
            "name": doc_item.get("title", "uploaded.pdf"),
            "title": doc_item.get("title", "uploaded.pdf"),
            "status": doc_item.get("kb_status", "PROCESSING"),
            "kb_status": doc_item.get("kb_status", "PROCESSING"),
            "summary": (summary_item or {}).get("summary", "No summary available yet."),
            "testable_concepts": (summary_item or {}).get("testable_concepts", []),
        },
    )


def handle_document_status(event, doc_id):
    user_id = get_user_id(event)

    doc_item = ensure_document_ready(user_id, doc_id)
    if not doc_item:
        return response(404, {"message": "Document not found"})

    status = doc_item.get("kb_status", "PROCESSING")
    normalized = "COMPLETE" if status == "READY" else status
    return response(
        200,
        {
            "doc_id": doc_id,
            "status": normalized,
            "kb_status": status,
            "document": {
                "doc_id": doc_id,
                "filename": doc_item.get("title", "uploaded.pdf"),
                "status": normalized,
                "kb_status": status,
            },
        },
    )


def handle_ask(event):
    payload = parse_json_body(event)
    user_id = payload.get("user_id") or DEMO_USER_ID
    doc_id = payload.get("doc_id")
    question = (payload.get("question") or "").strip()

    if not doc_id or not question:
        return response(400, {"message": "doc_id and question are required"})

    doc_item = ensure_document_ready(user_id, doc_id)
    if not doc_item:
        return response(404, {"message": "Document not found"})

    created_at = now_iso()
    topic = (doc_item.get("concepts") or ["General"])[0]
    answer = (
        "CAP theorem says that under network partition, a distributed system must trade between "
        "consistency and availability."
    )
    citations = [
        {
            "document": doc_item.get("title", "uploaded.pdf"),
            "slide": 12,
            "chunk_id": "chunk_034",
        }
    ]

    TABLE.put_item(
        Item={
            "PK": pk_user(user_id),
            "SK": sk_question(created_at),
            "doc_id": doc_id,
            "question": question,
            "answer": answer,
            "citations": citations,
            "topic": topic,
            "created_at": created_at,
        }
    )

    return response(
        200,
        {
            "doc_id": doc_id,
            "question": question,
            "answer": answer,
            "citation": citations,
            "citations": citations,
        },
    )


def generate_quiz_questions(concepts):
    out = []
    for concept in concepts[:5]:
        out.append(
            {
                "question": f"What does {concept} mainly relate to in distributed systems?",
                "options": [
                    "A. UI animation",
                    "B. System trade-offs and reliability",
                    "C. CSS layout",
                    "D. Image compression",
                ],
                "answer": "B",
                "explanation": f"{concept} is used to reason about distributed-system behavior.",
            }
        )
    return out


def handle_quiz(event):
    payload = parse_json_body(event)
    user_id = payload.get("user_id") or DEMO_USER_ID
    doc_id = payload.get("doc_id")

    if not doc_id:
        return response(400, {"message": "doc_id is required"})

    doc_item = ensure_document_ready(user_id, doc_id)
    if not doc_item:
        return response(404, {"message": "Document not found"})

    quiz_item = get_quiz(user_id, doc_id)
    if not quiz_item:
        questions = generate_quiz_questions(doc_item.get("concepts") or concepts_for(doc_item.get("title")))
        quiz_item = {
            "PK": pk_user(user_id),
            "SK": sk_quiz(doc_id),
            "doc_id": doc_id,
            "questions": questions,
            "generated_at": now_iso(),
        }
        TABLE.put_item(Item=quiz_item)

    return response(200, {"doc_id": doc_id, "questions": quiz_item.get("questions", [])})


def handle_dashboard(event):
    query = event.get("queryStringParameters") or {}
    user_id = query.get("user_id") or DEMO_USER_ID

    items = list_user_items(user_id)
    documents = [item for item in items if doc_id_from_sk(item.get("SK", ""))]
    questions = [item for item in items if str(item.get("SK", "")).startswith("QUESTION#")]

    topics = []
    for doc in documents:
        for concept in doc.get("concepts", []):
            if concept not in topics:
                topics.append(concept)

    return response(
        200,
        {
            "documents_uploaded": len(documents),
            "questions_asked": len(questions),
            "topics_studied": topics[:3] or ["CAP theorem", "Replication", "Quorum"],
        },
    )


def route_request(event):
    request_context = event.get("requestContext", {})
    http_info = request_context.get("http", {})
    method = http_info.get("method") or event.get("httpMethod", "")
    path = event.get("rawPath") or event.get("path", "")

    if method == "OPTIONS":
        return {"statusCode": 204, "headers": cors_headers(), "body": ""}

    if method == "POST" and path == "/login":
        return handle_login(event)
    if method == "POST" and path == "/documents/upload-url":
        return handle_upload_url(event)
    if method == "POST" and path == "/upload/presign":
        return handle_upload_url(event)
    if method == "POST" and path == "/upload":
        return handle_upload(event)
    if method == "GET" and path == "/documents":
        return handle_documents_list(event)
    if method == "GET" and path == "/docs/list":
        return handle_documents_list(event)
    if method == "POST" and path == "/ask":
        return handle_ask(event)
    if method == "POST" and path == "/quiz":
        return handle_quiz(event)
    if method == "GET" and path == "/dashboard":
        return handle_dashboard(event)

    detail_match = re.match(r"^/documents/([^/]+)$", path)
    if method == "GET" and detail_match:
        return handle_document_detail(event, detail_match.group(1))

    complete_match = re.match(r"^/documents/([^/]+)/complete$", path)
    if method == "POST" and complete_match:
        return handle_upload_complete(event, complete_match.group(1))

    status_match = re.match(r"^/documents/([^/]+)/status$", path)
    if method == "GET" and status_match:
        return handle_document_status(event, status_match.group(1))

    return response(404, {"message": f"Route not found: {method} {path}"})


def lambda_handler(event, _context):
    try:
        return route_request(event)
    except Exception as exc:
        return response(500, {"message": "Internal server error", "error": str(exc)})
