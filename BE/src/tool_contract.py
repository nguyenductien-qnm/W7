import json


TOOL_EVENT_KEYS = ("tool_name", "toolName", "name")


def is_tool_event(event):
    if not isinstance(event, dict):
        return False
    if any(event.get(key) for key in TOOL_EVENT_KEYS):
        return True
    return isinstance(event.get("input"), dict) and (
        event.get("user_id") or event.get("session_id") or event.get("selected_doc_ids")
    )


def tool_name_from_event(event, default):
    for key in TOOL_EVENT_KEYS:
        if event.get(key):
            return str(event.get(key))
    return default


def tool_payload(event):
    payload = {}
    if isinstance(event.get("input"), dict):
        payload.update(event.get("input") or {})
    for key in ("user_id", "session_id", "active_session_id", "selected_doc_ids", "doc_id", "doc_ids"):
        if event.get(key) is not None:
            payload[key] = event.get(key)
    if isinstance(event.get("metadata"), dict):
        payload.setdefault("metadata", event.get("metadata"))
    return payload


def event_from_tool_payload(event):
    payload = tool_payload(event)
    headers = {}
    if payload.get("user_id"):
        headers["X-User-Id"] = str(payload.get("user_id"))
    if payload.get("session_id") or payload.get("active_session_id"):
        headers["X-Session-Id"] = str(payload.get("session_id") or payload.get("active_session_id"))
    return {"body": json.dumps(payload), "headers": headers, "requestContext": {"http": {"method": "POST"}}}


def parse_http_response(lambda_response):
    if not isinstance(lambda_response, dict):
        return 200, lambda_response
    status = int(lambda_response.get("statusCode") or 200)
    body = lambda_response.get("body")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            body = {"message": body}
    elif body is None:
        body = {}
    return status, body


def tool_response(tool_name, status, data=None, citations=None, errors=None):
    return {
        "tool_name": tool_name,
        "status": status,
        "data": data or {},
        "citations": citations or [],
        "errors": errors or [],
    }


def run_tool_handler(event, tool_name, http_handler):
    if not is_tool_event(event):
        return http_handler(event)

    status_code, body = parse_http_response(http_handler(event_from_tool_payload(event)))
    if 200 <= status_code < 300:
        return tool_response(
            tool_name_from_event(event, tool_name),
            "success",
            data=body,
            citations=body.get("citations") or body.get("citation") or [],
        )
    return tool_response(
        tool_name_from_event(event, tool_name),
        "error",
        errors=[body.get("message") or body.get("error") or f"HTTP {status_code}"],
        data=body,
    )
