from core import (
    collect_session_documents,
    cors_headers,
    ensure_session,
    get_session_id,
    get_user_id,
    response,
)


def handle_documents_list(event):
    user_id = get_user_id(event)
    session_id = get_session_id(event) or "default"
    ensure_session(user_id, session_id)
    docs = collect_session_documents(user_id, session_id)
    return response(200, {"documents": docs, "docs": docs})


def route_request(event):
    request_context = event.get("requestContext", {})
    http_info = request_context.get("http", {})
    method = http_info.get("method") or event.get("httpMethod", "")
    path = event.get("rawPath") or event.get("path", "")

    if method == "OPTIONS":
        return {"statusCode": 204, "headers": cors_headers(), "body": ""}

    if method == "GET" and path == "/docs/list":
        return handle_documents_list(event)

    return response(404, {"message": f"Route not found: {method} {path}"})


def lambda_handler(event, _context):
    try:
        return route_request(event)
    except Exception as exc:
        return response(500, {"message": "Internal server error", "error": str(exc)})
