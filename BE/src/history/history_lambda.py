import re
from datetime import datetime, timedelta, timezone

from core import get_session_id, get_user_id, list_user_items, response
from tool_contract import is_tool_event, parse_http_response, tool_name_from_event, tool_payload, tool_response


def _normalize_limit(value, default=200, max_value=500):
    try:
        return max(1, min(max_value, int(value or default)))
    except (TypeError, ValueError):
        return default


def _same_session(item, session_id):
    item_session_id = str(item.get("session_id") or "default")
    if session_id == "default":
        return item_session_id in ("", "default")
    return item_session_id == session_id


def _is_summary_history(sk):
    return "#SUMMARY#TS#" in str(sk or "")


def _is_quiz_history(sk):
    return "#QUIZ#TS#" in str(sk or "")


def _is_exam_plan_history(sk):
    return str(sk or "").startswith("EXAM_PLAN#TS#")


def _parse_days(value, default=7):
    try:
        return max(1, min(30, int(value or default)))
    except (TypeError, ValueError):
        return default


def _parse_timestamp(value):
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _event_timestamp(item):
    return _parse_timestamp(item.get("created_at") or item.get("generated_at") or item.get("updated_at"))


def _clean_topic(value):
    text = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n:;,.?\"'")
    if not text:
        return ""
    if len(text) > 90:
        text = text[:87].rstrip() + "..."
    return text


def _topic_key(value):
    return re.sub(r"\s+", " ", _clean_topic(value).casefold())


def _question_topic(question):
    explicit = _clean_topic(question.get("topic"))
    if explicit:
        return explicit
    for field in ("source_title", "source_doc_id"):
        topic = _clean_topic(question.get(field))
        if topic:
            return topic
    text = _clean_topic(question.get("question"))
    text = re.sub(r"^(what|which|why|how|when)\s+(is|are|does|do|did|can|should)\s+", "", text, flags=re.IGNORECASE)
    return text or "Quiz question"


def _add_topic(topics_by_key, label, source, studied_at):
    clean = _clean_topic(label)
    if not clean:
        return
    key = _topic_key(clean)
    existing = topics_by_key.get(key)
    if not existing:
        topics_by_key[key] = {
            "topic": clean,
            "count": 0,
            "sources": set(),
            "last_studied_at": studied_at.isoformat().replace("+00:00", "Z"),
            "_last_dt": studied_at,
        }
        existing = topics_by_key[key]
    elif len(clean) < len(existing["topic"]) or existing["topic"].islower():
        existing["topic"] = clean
    existing["count"] += 1
    existing["sources"].add(source)
    if studied_at > existing["_last_dt"]:
        existing["_last_dt"] = studied_at
        existing["last_studied_at"] = studied_at.isoformat().replace("+00:00", "Z")


def _dashboard_from_items(items, user_id, session_id="all", days=7, now=None):
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    topics_by_key = {}
    totals = {
        "topics": 0,
        "summaries": 0,
        "quizzes": 0,
        "flashcards": 0,
        "questions": 0,
        "plans": 0,
    }

    for item in items:
        if session_id not in ("", "all") and not _same_session(item, session_id):
            continue
        studied_at = _event_timestamp(item)
        if not studied_at or studied_at < since:
            continue

        sk = str(item.get("SK") or "")
        if sk.startswith("QUESTION#"):
            totals["questions"] += 1
            _add_topic(topics_by_key, item.get("topic") or item.get("question"), "q&a", studied_at)
            continue

        if _is_summary_history(sk):
            totals["summaries"] += 1
            for concept in item.get("testable_concepts") or []:
                _add_topic(topics_by_key, concept, "summary", studied_at)
            continue

        if _is_quiz_history(sk):
            feature = str(item.get("feature") or "quiz").lower()
            if feature == "flashcards":
                totals["flashcards"] += 1
                source = "flashcards"
            else:
                totals["quizzes"] += 1
                source = "quiz"
            for question in item.get("questions") or []:
                if isinstance(question, dict):
                    _add_topic(topics_by_key, _question_topic(question), source, studied_at)
            continue

        if _is_exam_plan_history(sk):
            totals["plans"] += 1
            for task in item.get("tasks") or []:
                if isinstance(task, dict):
                    _add_topic(topics_by_key, task.get("topic"), "planning", studied_at)
            for topic in item.get("weak_topics") or []:
                _add_topic(topics_by_key, topic, "planning", studied_at)

    topics = []
    for topic in topics_by_key.values():
        topics.append(
            {
                "topic": topic["topic"],
                "count": topic["count"],
                "sources": sorted(topic["sources"]),
                "last_studied_at": topic["last_studied_at"],
            }
        )
    topics.sort(key=lambda item: (item["last_studied_at"], item["count"]), reverse=True)
    totals["topics"] = len(topics)
    return {
        "user_id": user_id,
        "session_id": session_id or "all",
        "window_days": days,
        "since": since.isoformat().replace("+00:00", "Z"),
        "topics": topics,
        "totals": totals,
    }


def _to_message_id(prefix, timestamp, suffix):
    base = str(timestamp or "").replace(":", "-")
    return f"{prefix}_{base}_{suffix}"


def _summary_text(item):
    summary = str(item.get("summary") or "").strip()
    concepts = item.get("testable_concepts") or []
    if not concepts:
        return summary
    lines = [summary, "", "Testable concepts:"]
    for idx, concept in enumerate(concepts[:5], start=1):
        lines.append(f"{idx}. {concept}")
    return "\n".join([line for line in lines if line is not None]).strip()


def _flash_cards(questions):
    cards = []
    for index, question in enumerate(questions):
        explanation = question.get("explanation")
        back = question.get("answer") or ""
        if explanation:
            back = f"{back}\n\n{explanation}"
        cards.append(
            {
                "id": f"card_{index}",
                "front": question.get("question") or "",
                "back": back,
            }
        )
    return cards


def _events_for_session(items, session_id):
    events = []
    for item in items:
        if not _same_session(item, session_id):
            continue
        sk = str(item.get("SK") or "")
        if sk.startswith("QUESTION#"):
            events.append(
                {
                    "type": "ask",
                    "created_at": item.get("created_at") or "",
                    "item": item,
                }
            )
            continue
        if _is_summary_history(sk):
            events.append(
                {
                    "type": "summary",
                    "created_at": item.get("generated_at") or "",
                    "item": item,
                }
            )
            continue
        if _is_quiz_history(sk):
            events.append(
                {
                    "type": "quiz",
                    "created_at": item.get("generated_at") or "",
                    "item": item,
                }
            )
            continue
        if _is_exam_plan_history(sk):
            events.append(
                {
                    "type": "planning",
                    "created_at": item.get("generated_at") or "",
                    "item": item,
                }
            )
    events.sort(key=lambda event: event.get("created_at") or "")
    return events


def _events_to_messages(events):
    messages = []
    for event in events:
        item = event["item"]
        created_at = event.get("created_at") or ""
        event_type = event["type"]

        if event_type == "ask":
            user_message = {
                "id": _to_message_id("ask", created_at, "user"),
                "role": "user",
                "feature": "chat",
                "text": item.get("question") or "",
                "createdAt": created_at,
            }
            bot_message = {
                "id": _to_message_id("ask", created_at, "bot"),
                "role": "bot",
                "feature": "chat",
                "text": item.get("answer") or "",
                "citations": item.get("citations") or [],
                "createdAt": created_at,
            }
            messages.extend([user_message, bot_message])
            continue

        if event_type == "summary":
            user_text = item.get("question") or "Summarize selected documents."
            messages.append(
                {
                    "id": _to_message_id("summary", created_at, "user"),
                    "role": "user",
                    "feature": "summary",
                    "text": user_text,
                    "createdAt": created_at,
                }
            )
            messages.append(
                {
                    "id": _to_message_id("summary", created_at, "bot"),
                    "role": "bot",
                    "feature": "summary",
                    "text": _summary_text(item),
                    "createdAt": created_at,
                }
            )
            continue

        if event_type == "quiz":
            questions = item.get("questions") or []
            feature = item.get("feature") or "quiz"
            user_text = item.get("question") or (
                "Create flash cards from selected documents." if feature == "flashcards" else "Generate quiz from selected documents."
            )
            messages.append(
                {
                    "id": _to_message_id("quiz", created_at, "user"),
                    "role": "user",
                    "feature": feature,
                    "text": user_text,
                    "createdAt": created_at,
                }
            )
            if feature == "flashcards":
                cards = _flash_cards(questions)
                messages.append(
                    {
                        "id": _to_message_id("quiz", created_at, "bot"),
                        "role": "bot",
                        "feature": "flashcards",
                        "text": f"Created {len(cards)} flash cards." if cards else "No flash cards returned.",
                        "cards": cards,
                        "createdAt": created_at,
                    }
                )
                continue
            messages.append(
                {
                    "id": _to_message_id("quiz", created_at, "bot"),
                    "role": "bot",
                    "feature": "quiz",
                    "text": "Quiz ready." if questions else "No quiz questions returned.",
                    "quiz": questions,
                    "createdAt": created_at,
                }
            )
            continue

        if event_type == "planning":
            tasks = item.get("tasks") or []
            messages.append(
                {
                    "id": _to_message_id("planning", created_at, "user"),
                    "role": "user",
                    "feature": "planning",
                    "text": f"Create an exam plan for {item.get('exam_date') or 'the exam'}.",
                    "createdAt": created_at,
                }
            )
            lines = [item.get("summary") or "Exam plan ready.", ""]
            for task in tasks:
                lines.append(
                    f"{task.get('date')}: {task.get('duration_minutes')} min {task.get('activity')} - {task.get('topic')}"
                )
            messages.append(
                {
                    "id": _to_message_id("planning", created_at, "bot"),
                    "role": "bot",
                    "feature": "planning",
                    "text": "\n".join(lines).strip(),
                    "plan": {
                        "plan_id": item.get("plan_id"),
                        "exam_date": item.get("exam_date"),
                        "summary": item.get("summary"),
                        "selected_doc_ids": item.get("selected_doc_ids") or [],
                        "selected_documents": item.get("selected_documents") or [],
                        "weak_topics": item.get("weak_topics") or [],
                        "created_at": item.get("created_at") or item.get("generated_at"),
                        "generated_at": item.get("generated_at"),
                        "tasks": tasks,
                    },
                    "createdAt": created_at,
                }
            )

    return messages


def handle_history(event):
    query = event.get("queryStringParameters") or {}
    user_id = get_user_id(event)
    session_id = get_session_id(event) or "default"
    limit = _normalize_limit(query.get("limit"), default=200, max_value=500)

    items = list_user_items(user_id)
    events = _events_for_session(items, session_id)
    if limit:
        events = events[-limit:]
    messages = _events_to_messages(events)

    return response(
        200,
        {
            "user_id": user_id,
            "session_id": session_id,
            "count": len(messages),
            "messages": messages,
        },
    )


def handle_dashboard(event):
    query = event.get("queryStringParameters") or {}
    user_id = get_user_id(event)
    session_id = get_session_id(event) or "all"
    if session_id == "default" and query.get("session_id") in (None, "", "all"):
        session_id = "all"
    days = _parse_days(query.get("days"), default=7)
    return response(200, _dashboard_from_items(list_user_items(user_id), user_id, session_id, days))


def lambda_handler(event, _context):
    try:
        if not is_tool_event(event):
            path = event.get("rawPath") or event.get("path") or ""
            if path == "/dashboard":
                return handle_dashboard(event)
            return handle_history(event)
        payload = tool_payload(event)
        api_event = {
            "headers": {
                "X-User-Id": str(payload.get("user_id") or ""),
                "X-Session-Id": str(payload.get("session_id") or "default"),
            },
            "queryStringParameters": {
                "user_id": payload.get("user_id"),
                "session_id": payload.get("session_id") or "default",
                "limit": payload.get("limit"),
            },
        }
        status_code, body = parse_http_response(handle_history(api_event))
        if 200 <= status_code < 300:
            return tool_response(tool_name_from_event(event, "get_history"), "success", data=body)
        return tool_response(tool_name_from_event(event, "get_history"), "error", data=body, errors=[body.get("message") or "History failed"])
    except Exception as exc:
        return response(500, {"message": "Internal server error", "error": str(exc)})
