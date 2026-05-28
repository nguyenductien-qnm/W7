import re

import uuid

from core import (
    TABLE,
    cors_headers,
    doc_id_from_sk,
    doc_in_session,
    ensure_profile,
    ensure_session,
    get_user_id,
    list_sessions,
    list_user_items,
    now_iso,
    parse_json_body,
    pk_user,
    public_session,
    response,
    sk_session,
)


def _session_id_from_event(event):
    params = event.get("pathParameters") or {}
    if params.get("session_id"):
        return params.get("session_id")
    raw_path = event.get("rawPath") or event.get("path") or ""
    match = re.match(r"^/session/([^/]+)$", raw_path)
    if match:
        return match.group(1)
    return ""


def handle_session_create(event):
    payload = parse_json_body(event)
    user_id = get_user_id(event, payload)
    session_id = str(payload.get("session_id") or f"session_{uuid.uuid4().hex[:10]}")
    session_name = str(payload.get("session_name") or payload.get("name") or "New Session").strip()
    ensure_profile(user_id, f"{user_id}@studybot.com")
    item = ensure_session(user_id, session_id, session_name)
    if item.get("session_name") != session_name:
        item = {**item, "session_name": session_name, "updated_at": now_iso()}
        TABLE.put_item(Item=item)
    return response(200, {"session": public_session(item)})


def handle_session_list(event):
    user_id = get_user_id(event)
    return response(200, {"sessions": [public_session(item) for item in list_sessions(user_id)]})


def handle_session_delete(event, session_id):
    user_id = get_user_id(event)
    if session_id == "default":
        return response(400, {"message": "The default session cannot be deleted"})

    items = list_user_items(user_id)
    doc_ids = {
        item.get("doc_id")
        for item in items
        if doc_id_from_sk(item.get("SK", "")) and doc_in_session(item, session_id)
    }
    with TABLE.batch_writer() as batch:
        batch.delete_item(Key={"PK": pk_user(user_id), "SK": sk_session(session_id)})
        for item in items:
            sk = item.get("SK", "")
            if item.get("session_id") == session_id or item.get("doc_id") in doc_ids:
                batch.delete_item(Key={"PK": pk_user(user_id), "SK": sk})

    return response(200, {"deleted": True, "session_id": session_id})


def route_request(event):
    request_context = event.get("requestContext", {})
    http_info = request_context.get("http", {})
    method = http_info.get("method") or event.get("httpMethod", "")
    path = event.get("rawPath") or event.get("path", "")

    if method == "OPTIONS":
        return {"statusCode": 204, "headers": cors_headers(), "body": ""}

    if method == "POST" and path == "/session/create":
        return handle_session_create(event)
    if method == "GET" and path == "/session/list":
        return handle_session_list(event)
    if method == "DELETE" and (path.startswith("/session/") or (event.get("pathParameters") or {}).get("session_id")):
        session_id = _session_id_from_event(event)
        if not session_id:
            return response(400, {"message": "session_id is required"})
        return handle_session_delete(event, session_id)

    return response(404, {"message": f"Route not found: {method} {path}"})


def lambda_handler(event, _context):
    try:
        return route_request(event)
    except Exception as exc:
        return response(500, {"message": "Internal server error", "error": str(exc)})
