import re

import uuid

from core import (
    S3,
    TABLE,
    UPLOADS_BUCKET_NAME,
    cors_headers,
    ensure_profile,
    ensure_session,
    get_doc,
    get_session_id,
    get_user_id,
    now_epoch,
    now_iso,
    parse_json_body,
    parse_upload_body,
    pk_user,
    raw_document_key,
    response,
    safe_filename,
    sk_doc,
    use_bedrock_ingestion,
    doc_in_session,
    concepts_for,
)


def _doc_id_from_event(event):
    params = event.get("pathParameters") or {}
    if params.get("doc_id"):
        return params.get("doc_id")
    raw_path = event.get("rawPath") or event.get("path") or ""
    match = re.match(r"^/documents/([^/]+)/complete$", raw_path)
    if match:
        return match.group(1)
    return ""


def handle_upload(event):
    title, user_id, session_id = parse_upload_body(event)
    ensure_profile(user_id, f"{user_id}@studybot.com")
    ensure_session(user_id, session_id)

    doc_id = f"doc_{uuid.uuid4().hex[:10]}"
    uploaded_at = now_iso()

    doc_item = {
        "PK": pk_user(user_id),
        "SK": sk_doc(doc_id),
        "doc_id": doc_id,
        "title": title,
        "s3_key": raw_document_key(user_id, session_id, doc_id, title),
        "raw_s3_key": raw_document_key(user_id, session_id, doc_id, title),
        "session_id": session_id,
        "kb_status": "PROCESSING",
        "uploaded_at": uploaded_at,
        "page_count": 40,
        "concepts": concepts_for(title),
        "processing_started_at_epoch": now_epoch(),
    }
    TABLE.put_item(Item=doc_item)

    return response(200, {"doc_id": doc_id, "session_id": session_id, "status": "PROCESSING", "kb_status": "PROCESSING"})


def handle_upload_url(event):
    if not UPLOADS_BUCKET_NAME:
        return response(500, {"message": "UPLOADS_BUCKET_NAME is not configured"})

    payload = parse_json_body(event)
    user_id = get_user_id(event, payload)
    session_id = get_session_id(event, payload) or "default"
    filename = safe_filename(payload.get("filename") or payload.get("title") or "uploaded.pdf")
    content_type = payload.get("content_type") or "application/octet-stream"
    doc_id = payload.get("doc_id") or f"doc_{uuid.uuid4().hex[:10]}"
    s3_key = raw_document_key(user_id, session_id, doc_id, filename)

    ensure_profile(user_id, f"{user_id}@studybot.com")
    ensure_session(user_id, session_id)

    doc_item = {
        "PK": pk_user(user_id),
        "SK": sk_doc(doc_id),
        "doc_id": doc_id,
        "title": filename,
        "s3_key": s3_key,
        "raw_s3_key": s3_key,
        "session_id": session_id,
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
            "session_id": session_id,
        },
    )


def handle_upload_complete(event, doc_id):
    payload = parse_json_body(event)
    user_id = get_user_id(event, payload)
    session_id = get_session_id(event, payload) or "default"
    doc_item = get_doc(user_id, doc_id)
    if not doc_item:
        return response(404, {"message": "Document not found"})
    if not doc_in_session(doc_item, session_id):
        return response(403, {"message": "Document does not belong to the active session"})

    updated = {
        **doc_item,
        "kb_status": "PROCESSING",
        "processing_started_at_epoch": now_epoch(),
    }

    ingestion_job_id = f"ing_{uuid.uuid4().hex[:10]}"
    ingestion_status = "IN_PROGRESS"
    if use_bedrock_ingestion():
        ingestion_job_id = ""
        ingestion_status = "WAITING_FOR_PROCESSOR"

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


def route_request(event):
    request_context = event.get("requestContext", {})
    http_info = request_context.get("http", {})
    method = http_info.get("method") or event.get("httpMethod", "")
    path = event.get("rawPath") or event.get("path", "")

    if method == "OPTIONS":
        return {"statusCode": 204, "headers": cors_headers(), "body": ""}

    if method == "POST" and path in ("/documents/upload-url", "/upload/presign"):
        return handle_upload_url(event)
    if method == "POST" and path == "/upload":
        return handle_upload(event)
    if method == "POST" and (path.endswith("/complete") or (event.get("pathParameters") or {}).get("doc_id")):
        doc_id = _doc_id_from_event(event)
        if not doc_id:
            return response(400, {"message": "doc_id is required"})
        return handle_upload_complete(event, doc_id)

    return response(404, {"message": f"Route not found: {method} {path}"})


def lambda_handler(event, _context):
    try:
        return route_request(event)
    except Exception as exc:
        return response(500, {"message": "Internal server error", "error": str(exc)})
