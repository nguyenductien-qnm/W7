import json
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import boto3

from core import (
    TABLE,
    doc_in_session,
    ensure_document_ready,
    get_selected_docs_for_session,
    get_session_id,
    get_user_id,
    list_documents,
    list_user_items,
    normalize_doc_ids,
    now_iso,
    parse_json_body,
    pk_user,
    response,
)
from memory_utils import create_memory_event, retrieve_memory_texts
from tool_contract import parse_http_response, run_tool_handler, tool_name_from_event, tool_response


ACTIVITY_SEQUENCE = ("review", "flashcards", "quiz", "practice", "recap")
SKIP_WORDS = {"skip", "blank", "none", "no", "nope", "n/a", "na"}
AWS_REGION = os.environ.get("AWS_REGION", "ap-southeast-1")
BEDROCK_GENERATION_MODEL_ID = os.environ.get(
    "BEDROCK_GENERATION_MODEL_ID",
    "global.amazon.nova-2-lite-v1:0",
)

BEDROCK_RUNTIME = boto3.client("bedrock-runtime", region_name=AWS_REGION)


def sk_exam_plan(plan_id):
    return f"EXAM_PLAN#{plan_id}"


def sk_exam_plan_history(created_at_iso, plan_id, event_id=None):
    suffix = str(event_id or uuid.uuid4().hex[:10])
    return f"EXAM_PLAN#TS#{created_at_iso}#{plan_id}#{suffix}"


def _parse_date(value):
    if value in (None, ""):
        return None
    try:
        return datetime.strptime(str(value or ""), "%Y-%m-%d").date()
    except ValueError:
        return None


def _extract_json_object(text):
    try:
        parsed = json.loads(text or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass
    match = re.search(r"\{.*\}", text or "", flags=re.DOTALL)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _invoke_text_model(prompt, max_tokens=450, temperature=0.0):
    body = {
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": {
            "maxTokens": max_tokens,
            "temperature": temperature,
            "topP": 0.9,
        },
    }
    response_data = BEDROCK_RUNTIME.invoke_model(
        modelId=BEDROCK_GENERATION_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(body),
    )
    payload = json.loads(response_data["body"].read().decode("utf-8"))
    content = (((payload.get("output") or {}).get("message") or {}).get("content") or [])
    if content and isinstance(content, list):
        return "\n".join(part.get("text", "") for part in content if isinstance(part, dict)).strip()
    return str(payload.get("outputText") or payload.get("completion") or "").strip()


def _parse_planner_prompt_deterministic(text):
    prompt = str(text or "")
    if not prompt.strip():
        return {}
    exam_date = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", prompt)
    daily = re.search(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\s*(?:per\s+day|daily|/\s*day)", prompt, re.IGNORECASE)
    weekly = re.search(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\s*(?:per\s+week|weekly|/\s*week)", prompt, re.IGNORECASE)
    generic_hours = re.search(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\b", prompt, re.IGNORECASE)
    session_length = re.search(r"(\d+)\s*(?:minutes?|mins?|m)\s*(?:sessions?|session length)", prompt, re.IGNORECASE)
    weak_topics = re.search(r"weak topics?\s*:\s*([^.;]+)", prompt, re.IGNORECASE)
    excluded_days = re.search(r"(?:exclude|excluded days?)\s*:\s*([^.;]+)", prompt, re.IGNORECASE)
    target_grade = re.search(r"(?:target grade|goal)\s*:\s*([^.;]+)", prompt, re.IGNORECASE)
    target_exam_prefix = re.search(
        r"\b([A-Za-z][A-Za-z0-9&+\- ]{2,60}?\s+(?:exam|test|midterm|final))\s+(?:on|by|at)\s+20\d{2}-\d{2}-\d{2}\b",
        prompt,
        re.IGNORECASE,
    )
    target_exam = target_exam_prefix or re.search(
        r"(?:exam|test|midterm|final)\s*(?:is\s*)?(?:on|for|about|covers?|covering|topic:?)\s*([^.;,\n]+)",
        prompt,
        re.IGNORECASE,
    )
    if not target_exam:
        target_exam = re.search(r"(?:subject|course|exam topic)\s*:\s*([^.;,\n]+)", prompt, re.IGNORECASE)
    parsed = {}
    if exam_date:
        parsed["exam_date"] = exam_date.group(1)
    if daily:
        parsed["daily_study_hours"] = float(daily.group(1))
    elif weekly:
        parsed["weekly_study_hours"] = float(weekly.group(1))
    elif generic_hours:
        parsed["daily_study_hours"] = float(generic_hours.group(1))
    if session_length:
        parsed["preferred_session_length"] = int(session_length.group(1))
    if weak_topics:
        parsed["weak_topics"] = [item.strip() for item in weak_topics.group(1).split(",") if item.strip()]
    if excluded_days:
        parsed["excluded_days"] = [item.strip() for item in excluded_days.group(1).split(",") if item.strip()]
    if target_grade:
        parsed["target_grade"] = target_grade.group(1).strip()
    if target_exam:
        target_exam_text = target_exam.group(1).strip()
        if not _parse_date(target_exam_text):
            parsed["target_exam"] = target_exam_text
    return parsed


def _parse_planner_prompt_llm(text):
    prompt_text = str(text or "").strip()
    if not prompt_text:
        return {}
    today = datetime.now(timezone.utc).date().isoformat()
    prompt = f"""
Extract exam planning fields from the user's request.
Return only a JSON object with these keys when known:
exam_date as YYYY-MM-DD, daily_study_hours as a number, weekly_study_hours as a number,
preferred_session_length as minutes, weak_topics as an array of strings,
excluded_days as an array of weekday names or YYYY-MM-DD dates, target_grade as a string,
target_exam as a short string.
If the user gives a single hours value without saying weekly, treat it as daily_study_hours.
Use today's date only to resolve relative dates if needed: {today}.
User request: {prompt_text}
"""
    try:
        parsed = _extract_json_object(_invoke_text_model(prompt))
    except Exception:
        return {}
    out = {}
    if _parse_date(parsed.get("exam_date")):
        out["exam_date"] = parsed.get("exam_date")
    for key in ("daily_study_hours", "weekly_study_hours"):
        try:
            value = float(parsed.get(key))
            if value > 0:
                out[key] = value
        except (TypeError, ValueError):
            pass
    if parsed.get("preferred_session_length"):
        out["preferred_session_length"] = parsed.get("preferred_session_length")
    for key in ("weak_topics", "excluded_days"):
        values = parsed.get(key)
        if isinstance(values, list):
            out[key] = [str(item).strip() for item in values if str(item).strip()]
    for key in ("target_grade", "target_exam"):
        if parsed.get(key):
            out[key] = str(parsed.get(key)).strip()
    return out


def _normalize_planner_payload(payload):
    normalized = dict(payload or {})
    prior_fields = normalized.get("prior_fields")
    if isinstance(prior_fields, dict):
        for key, value in prior_fields.items():
            if normalized.get(key) in (None, "", []):
                normalized[key] = value
    normalized.pop("prior_fields", None)
    prompt_text = normalized.get("prompt") or normalized.get("question") or normalized.get("message") or ""
    deterministic = _parse_planner_prompt_deterministic(prompt_text)
    for key, value in deterministic.items():
        if normalized.get(key) in (None, "", []):
            normalized[key] = value
    if not normalized.get("exam_date") or not (
        normalized.get("daily_study_hours")
        or normalized.get("weekly_study_hours")
        or normalized.get("hours_per_day")
        or normalized.get("hours_per_week")
    ):
        llm_fields = _parse_planner_prompt_llm(prompt_text)
        for key, value in llm_fields.items():
            if normalized.get(key) in (None, "", []):
                normalized[key] = value
    return normalized


def _is_skip_reply(value):
    text = str(value or "").strip().lower()
    return text in SKIP_WORDS


def _normalize_string_array(value):
    if value in (None, ""):
        return []
    if isinstance(value, str):
        values = re.split(r"[,;\n]+", value)
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = [value]
    return [str(item).strip() for item in values if str(item).strip()]


def _parse_bounded_number(value, field, label, minimum, maximum, errors):
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        errors[field] = f"{label} must be numeric."
        return None
    if parsed <= 0:
        errors[field] = f"{label} must be greater than 0."
        return None
    if parsed < minimum or parsed > maximum:
        errors[field] = f"{label} must be between {minimum:g} and {maximum:g}."
        return None
    return parsed


def _decimal_or_none(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _validate_and_normalize_planner_payload(payload, require_fields=True):
    normalized = _normalize_planner_payload(payload)
    errors = {}

    exam_date_value = normalized.get("exam_date")
    exam_date = _parse_date(exam_date_value)
    if exam_date:
        normalized["exam_date"] = exam_date.isoformat()
    elif exam_date_value not in (None, ""):
        errors["exam_date"] = "Exam date must be a valid YYYY-MM-DD date."

    daily = _parse_bounded_number(
        normalized.get("daily_study_hours") or normalized.get("hours_per_day") or normalized.get("daily_hours"),
        "daily_study_hours",
        "Daily study hours",
        0.25,
        12,
        errors,
    )
    weekly = _parse_bounded_number(
        normalized.get("weekly_study_hours") or normalized.get("hours_per_week") or normalized.get("weekly_hours"),
        "weekly_study_hours",
        "Weekly study hours",
        0.25,
        84,
        errors,
    )
    session_length = _parse_bounded_number(
        normalized.get("preferred_session_length") or normalized.get("preferred_session_minutes"),
        "preferred_session_length",
        "Preferred session length",
        20,
        180,
        errors,
    )

    if daily is not None:
        normalized["daily_study_hours"] = daily
    if weekly is not None:
        normalized["weekly_study_hours"] = weekly
    if session_length is not None:
        normalized["preferred_session_length"] = int(round(session_length))

    normalized["weak_topics"] = _normalize_string_array(normalized.get("weak_topics"))
    normalized["excluded_days"] = _normalize_string_array(normalized.get("excluded_days"))
    for key in ("target_grade", "target_exam"):
        if normalized.get(key) is not None:
            normalized[key] = str(normalized.get(key)).strip()
    if not normalized.get("target_exam") and normalized.get("exam_subject"):
        normalized["target_exam"] = str(normalized.get("exam_subject")).strip()

    missing_required = []
    if require_fields:
        if not normalized.get("target_exam"):
            missing_required.append("target_exam")
        if not exam_date and "exam_date" not in errors:
            missing_required.append("exam_date")
        if daily is None and weekly is None and "daily_study_hours" not in errors and "weekly_study_hours" not in errors:
            missing_required.append("study_hours")

    return normalized, missing_required, errors


def _clarification_question(missing_required, field_errors):
    if field_errors:
        labels = []
        if "exam_date" in field_errors:
            labels.append("a valid exam date in YYYY-MM-DD format")
        if "daily_study_hours" in field_errors or "weekly_study_hours" in field_errors:
            labels.append("study hours as a positive number")
        if "preferred_session_length" in field_errors:
            labels.append("preferred session length in minutes")
        return f"Please send {', '.join(labels)}."
    if {"target_exam", "exam_date", "study_hours"}.issubset(set(missing_required)):
        return "What exam or subject is this for, what is the exam date, and how many hours can you study per day or per week?"
    if "target_exam" in missing_required and "exam_date" in missing_required:
        return "What exam or subject is this for, and what is the exam date? Please use YYYY-MM-DD for the date."
    if "target_exam" in missing_required and "study_hours" in missing_required:
        return "What exam or subject is this for, and how many hours can you study per day or per week?"
    if "exam_date" in missing_required and "study_hours" in missing_required:
        return "What is your exam date, and how many hours can you study per day or per week?"
    if "target_exam" in missing_required:
        return "What exam or subject is this study plan for?"
    if "exam_date" in missing_required:
        return "What is the exam date? Please use YYYY-MM-DD."
    if "study_hours" in missing_required:
        return "How many hours can you study per day or per week?"
    return "Any weak topics, excluded days, session length, or target grade? You can say skip."


def _planner_clarification(payload):
    normalized, missing_required, errors = _validate_and_normalize_planner_payload(payload, require_fields=True)
    prompt_text = normalized.get("prompt") or normalized.get("question") or normalized.get("message") or ""
    skipped_optional = _is_skip_reply(prompt_text)
    ready = not missing_required and not errors
    unclear_optional = [] if ready or skipped_optional else []
    return {
        "ready": ready,
        "fields": normalized,
        "missing_required": missing_required,
        "unclear_optional": unclear_optional,
        "field_errors": errors,
        "clarification_question": "" if ready else _clarification_question(missing_required, errors),
    }


def _positive_int(value, default=None, minimum=1, maximum=None):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def _normalize_excluded_days(values):
    out = set()
    for value in values or []:
        text = str(value or "").strip()
        parsed = _parse_date(text)
        if parsed:
            out.add(parsed.isoformat())
            continue
        lowered = text.lower()
        if lowered in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"):
            out.add(lowered)
    return out


def _availability(payload):
    try:
        daily = float(payload.get("daily_study_hours") or payload.get("hours_per_day") or payload.get("daily_hours") or 0)
    except (TypeError, ValueError):
        daily = 0
    try:
        weekly = float(payload.get("weekly_study_hours") or payload.get("hours_per_week") or payload.get("weekly_hours") or 0)
    except (TypeError, ValueError):
        weekly = 0
    if daily:
        return int(round(daily * 60)), "daily"
    if weekly:
        return max(30, int(round((weekly * 60) / 5))), "weekly"
    return None, ""


def _recent_quiz_topics(user_id, session_id):
    topics = []
    for item in list_user_items(user_id):
        if item.get("session_id") != session_id:
            continue
        if "#QUIZ#TS#" not in str(item.get("SK") or ""):
            continue
        for question in item.get("questions") or []:
            text = str(question.get("question") or "")
            match = re.search(r"about\s+([^?]+)", text, re.IGNORECASE)
            topic = (match.group(1) if match else text).strip(" .?")
            if topic and topic not in topics:
                topics.append(topic)
    return topics[-5:]


def _plan_public(item):
    selected_documents = item.get("selected_documents") or []
    return {
        "plan_id": item.get("plan_id"),
        "session_id": item.get("session_id", "default"),
        "exam_date": item.get("exam_date"),
        "summary": item.get("summary"),
        "selected_doc_ids": item.get("selected_doc_ids") or [],
        "selected_documents": selected_documents,
        "weak_topics": item.get("weak_topics") or [],
        "excluded_days": item.get("excluded_days") or [],
        "daily_study_hours": item.get("daily_study_hours"),
        "weekly_study_hours": item.get("weekly_study_hours"),
        "preferred_session_length": item.get("preferred_session_length"),
        "target_grade": item.get("target_grade"),
        "target_exam": item.get("target_exam"),
        "tasks": item.get("tasks") or [],
        "created_at": item.get("created_at") or item.get("generated_at") or "",
        "generated_at": item.get("generated_at") or item.get("created_at") or "",
    }


def _plan_sort_value(item):
    return item.get("created_at") or item.get("generated_at") or ""


def _get_plan_item(user_id, plan_id):
    latest = TABLE.get_item(Key={"PK": pk_user(user_id), "SK": sk_exam_plan(plan_id)}).get("Item")
    if latest:
        return latest

    matches = []
    for item in list_user_items(user_id):
        sk = str(item.get("SK") or "")
        if sk.startswith("EXAM_PLAN#TS#") and item.get("plan_id") == plan_id:
            matches.append(item)
    if not matches:
        return None
    matches.sort(key=_plan_sort_value, reverse=True)
    return matches[0]


def _ready_session_docs(user_id, session_id):
    docs = []
    for doc in list_documents(user_id):
        if not doc_in_session(doc, session_id):
            continue
        ensured = ensure_document_ready(user_id, doc.get("doc_id"))
        if ensured and ensured.get("kb_status") == "READY":
            docs.append(ensured)
    return docs


def _rank_docs_for_plan(docs, payload, weak_topics, quiz_topics, memory_texts):
    terms = []
    for value in [
        payload.get("question"),
        payload.get("prompt"),
        payload.get("target_exam"),
        payload.get("target_grade"),
        payload.get("exam_date"),
        *weak_topics,
        *quiz_topics,
        *memory_texts,
    ]:
        terms.extend(re.findall(r"[a-z0-9]{3,}", str(value or "").lower()))
    term_set = set(terms)

    ranked = []
    for doc in docs:
        haystack = " ".join(
            [
                str(doc.get("title") or ""),
                " ".join(str(item) for item in (doc.get("concepts") or [])),
            ]
        ).lower()
        score = sum(3 for term in term_set if term in haystack)
        if weak_topics:
            score += sum(4 for topic in weak_topics if str(topic).lower() in haystack)
        score += len(doc.get("concepts") or [])
        ranked.append((score, doc.get("uploaded_at", ""), doc))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in ranked]


def _rank_docs_with_reasons(docs, plan, limit=5):
    weak_topics = [str(item).strip() for item in plan.get("weak_topics") or [] if str(item).strip()]
    task_topics = [
        str(task.get("topic") or "").strip()
        for task in (plan.get("tasks") or [])
        if str(task.get("topic") or "").strip()
    ]
    selected_ids = {str(doc_id) for doc_id in plan.get("selected_doc_ids") or []}
    query_values = [
        plan.get("summary"),
        plan.get("exam_date"),
        plan.get("target_grade"),
        *weak_topics,
        *task_topics,
    ]
    terms = []
    for value in query_values:
        terms.extend(re.findall(r"[a-z0-9]{3,}", str(value or "").lower()))
    term_set = set(terms)

    ranked = []
    for doc in docs:
        doc_id = str(doc.get("doc_id") or "")
        title = str(doc.get("title") or "uploaded.pdf")
        concepts = [str(item).strip() for item in doc.get("concepts") or [] if str(item).strip()]
        haystack = " ".join([title, *concepts]).lower()
        matched_terms = sorted({term for term in term_set if term in haystack})[:8]
        matched_weak_topics = [topic for topic in weak_topics if topic.lower() in haystack]
        matched_concepts = [concept for concept in concepts if concept.lower() in term_set or concept.lower() in haystack]

        score = len(matched_terms) * 3 + len(matched_weak_topics) * 5 + len(matched_concepts)
        if doc_id in selected_ids:
            score += 2
        score += min(len(concepts), 5) * 0.2

        reasons = []
        if doc_id in selected_ids:
            reasons.append("Already part of this exam plan")
        if matched_weak_topics:
            reasons.append("Matches weak topics: " + ", ".join(matched_weak_topics[:3]))
        if matched_terms:
            reasons.append("Matches plan terms: " + ", ".join(matched_terms[:5]))
        if not reasons:
            reasons.append("Ready document in the active session")

        ranked.append(
            {
                "score": score,
                "uploaded_at": doc.get("uploaded_at", ""),
                "document": {
                    "doc_id": doc_id,
                    "title": title,
                    "filename": title,
                    "kb_status": doc.get("kb_status", "READY"),
                    "session_id": doc.get("session_id", "default"),
                    "concepts": concepts[:8],
                    "reasons": reasons,
                    "already_selected": doc_id in selected_ids,
                },
            }
        )

    ranked.sort(key=lambda item: (item["score"], item["uploaded_at"]), reverse=True)
    return [item["document"] for item in ranked[:limit]]


def _auto_select_docs(user_id, session_id, payload, weak_topics, quiz_topics, memory_texts):
    ready_docs = _ready_session_docs(user_id, session_id)
    if not ready_docs:
        return None, response(400, {"message": "No ready documents found in the active session. Upload documents and wait for processing to finish before creating a plan."})
    ranked = _rank_docs_for_plan(ready_docs, payload, weak_topics, quiz_topics, memory_texts)
    return ranked[: min(5, len(ranked))], None


def _selected_topics(selected_docs, weak_topics, quiz_topics):
    topics = []
    for topic in weak_topics + quiz_topics:
        text = str(topic or "").strip()
        if text and text not in topics:
            topics.append(text)
    for doc in selected_docs:
        for concept in doc.get("concepts") or []:
            if concept not in topics:
                topics.append(concept)
    if not topics:
        topics.append("Selected document review")
    return topics


def _format_plan_text(plan):
    lines = [plan.get("summary", "Exam plan ready."), ""]
    for task in plan.get("tasks", []):
        lines.append(
            f"{task['date']}: {task['duration_minutes']} min {task['activity']} - {task['topic']}"
        )
    return "\n".join(lines).strip()


def _build_tasks(start_date, exam_date, minutes_per_study_day, preferred_session_length, excluded, topics, doc_ids):
    tasks = []
    current = start_date
    activity_idx = 0
    topic_idx = 0
    while current <= exam_date:
        weekday = current.strftime("%A").lower()
        if current.isoformat() in excluded or weekday in excluded:
            current += timedelta(days=1)
            continue

        remaining = max(0, minutes_per_study_day)
        while remaining > 0:
            duration = min(preferred_session_length, remaining)
            topic = topics[topic_idx % len(topics)]
            activity = "recap" if current == exam_date else ACTIVITY_SEQUENCE[activity_idx % (len(ACTIVITY_SEQUENCE) - 1)]
            tasks.append(
                {
                    "date": current.isoformat(),
                    "duration_minutes": duration,
                    "topic": topic,
                    "activity": activity,
                    "doc_ids": doc_ids,
                    "reason": "Weak topic focus" if topic_idx < len(topics) and topic in topics[:2] else "Spaced exam preparation",
                }
            )
            remaining -= duration
            activity_idx += 1
            topic_idx += 1
        current += timedelta(days=1)
    return tasks


def _write_planner(event, plan_id=None):
    payload, missing_required, field_errors = _validate_and_normalize_planner_payload(parse_json_body(event), require_fields=True)
    user_id = get_user_id(event, payload)
    session_id = get_session_id(event, payload) or "default"
    selected_doc_ids = normalize_doc_ids(payload)
    exam_date = _parse_date(payload.get("exam_date"))
    minutes_per_study_day, availability_mode = _availability(payload)

    if field_errors or missing_required:
        return response(
            400,
            {
                "message": _clarification_question(missing_required, field_errors),
                "field_errors": field_errors,
                "missing_required": missing_required,
            },
        )
    today = datetime.now(timezone.utc).date()
    start_date = min(today, exam_date)
    weak_topics = [str(item).strip() for item in payload.get("weak_topics") or [] if str(item).strip()]
    memory_texts = retrieve_memory_texts(
        user_id,
        session_id,
        f"Exam plan for {exam_date.isoformat()} weak topics study history",
        top_k=3,
    )
    for memory_text in memory_texts:
        if memory_text not in weak_topics:
            weak_topics.append(memory_text[:120])
    quiz_topics = _recent_quiz_topics(user_id, session_id)

    if selected_doc_ids:
        selected_docs, error_response = get_selected_docs_for_session(user_id, selected_doc_ids, session_id)
        if error_response:
            return error_response
        not_ready = [doc.get("doc_id") for doc in selected_docs if doc.get("kb_status") != "READY"]
        if not_ready:
            return response(400, {"message": "Selected documents must finish processing before planning", "not_ready_doc_ids": not_ready})
    else:
        selected_docs, error_response = _auto_select_docs(user_id, session_id, payload, weak_topics, quiz_topics, memory_texts)
        if error_response:
            return error_response

    topics = _selected_topics(selected_docs, weak_topics, quiz_topics)
    excluded = _normalize_excluded_days(payload.get("excluded_days") or [])
    normalized_excluded_days = sorted(excluded)
    preferred_session_length = _positive_int(
        payload.get("preferred_session_length") or payload.get("preferred_session_minutes"),
        default=60,
        minimum=20,
        maximum=180,
    )
    selected_ids = [item.get("doc_id") for item in selected_docs if item.get("doc_id")]
    selected_documents = [
        {"doc_id": item.get("doc_id"), "title": item.get("title", "uploaded.pdf")}
        for item in selected_docs
        if item.get("doc_id")
    ]
    tasks = _build_tasks(
        start_date=start_date,
        exam_date=exam_date,
        minutes_per_study_day=minutes_per_study_day,
        preferred_session_length=preferred_session_length,
        excluded=excluded,
        topics=topics,
        doc_ids=selected_ids,
    )

    if not tasks:
        return response(400, {"message": "No study days are available before the exam after exclusions"})

    plan_id = plan_id or f"plan_{uuid.uuid4().hex[:10]}"
    summary = (
        f"Study plan through {exam_date.isoformat()} using {availability_mode} availability. "
        f"{len(tasks)} sessions cover {len(topics)} focus topics across {len(selected_ids)} document(s)."
    )
    plan = {
        "session_id": session_id,
        "plan_id": plan_id,
        "exam_date": exam_date.isoformat(),
        "summary": summary,
        "tasks": tasks,
        "selected_doc_ids": selected_ids,
        "selected_documents": selected_documents,
        "weak_topics": weak_topics,
        "excluded_days": normalized_excluded_days,
        "daily_study_hours": payload.get("daily_study_hours"),
        "weekly_study_hours": payload.get("weekly_study_hours"),
        "preferred_session_length": preferred_session_length,
        "target_grade": payload.get("target_grade"),
        "target_exam": payload.get("target_exam"),
    }
    generated_at = now_iso()
    item = {
        "PK": pk_user(user_id),
        "SK": sk_exam_plan(plan_id),
        "session_id": session_id,
        "plan_id": plan_id,
        "exam_date": exam_date.isoformat(),
        "selected_doc_ids": selected_ids,
        "selected_documents": selected_documents,
        "target_grade": payload.get("target_grade"),
        "target_exam": payload.get("target_exam"),
        "daily_study_hours": _decimal_or_none(payload.get("daily_study_hours")),
        "weekly_study_hours": _decimal_or_none(payload.get("weekly_study_hours")),
        "preferred_session_length": preferred_session_length,
        "excluded_days": normalized_excluded_days,
        "weak_topics": weak_topics,
        "summary": summary,
        "tasks": tasks,
        "created_at": generated_at,
        "generated_at": generated_at,
    }
    TABLE.put_item(Item=item)
    TABLE.put_item(Item={**item, "SK": sk_exam_plan_history(generated_at, plan_id)})
    create_memory_event(user_id, session_id, "USER", f"Create exam plan for {exam_date.isoformat()}", {"feature": "planning"})
    create_memory_event(user_id, session_id, "ASSISTANT", _format_plan_text(plan), {"feature": "planning", "plan_id": plan_id})

    return response(200, _plan_public(item))


def handle_planner(event):
    return _write_planner(event)


def handle_planner_clarify(event):
    return response(200, _planner_clarification(parse_json_body(event)))


def handle_planner_list(event):
    user_id = get_user_id(event)
    session_id = get_session_id(event) or "default"
    plans_by_id = {}
    for item in list_user_items(user_id):
        sk = str(item.get("SK") or "")
        if not sk.startswith("EXAM_PLAN#"):
            continue
        if item.get("session_id", "default") != session_id:
            continue
        plan_id = item.get("plan_id")
        if not plan_id:
            continue
        existing = plans_by_id.get(plan_id)
        if existing and not sk.startswith("EXAM_PLAN#TS#"):
            continue
        if existing and _plan_sort_value(existing) >= _plan_sort_value(item):
            continue
        plans_by_id[plan_id] = item

    plans = []
    for item in plans_by_id.values():
        public = _plan_public(item)
        public["tasks"] = public["tasks"][:3]
        public["task_count"] = len(item.get("tasks") or [])
        public["selected_doc_count"] = len(item.get("selected_doc_ids") or [])
        plans.append(public)
    plans.sort(key=lambda item: item.get("created_at") or item.get("generated_at") or "", reverse=True)
    return response(200, {"plans": plans, "session_id": session_id})


def handle_planner_detail(event, plan_id):
    user_id = get_user_id(event)
    session_id = get_session_id(event) or "default"
    item = _get_plan_item(user_id, plan_id)
    if not item:
        return response(404, {"message": "Plan not found"})
    if item.get("session_id", "default") != session_id:
        return response(403, {"message": "Plan does not belong to the active session"})
    return response(200, _plan_public(item))


def handle_planner_delete(event, plan_id):
    user_id = get_user_id(event)
    session_id = get_session_id(event) or "default"
    item = _get_plan_item(user_id, plan_id)
    if not item:
        return response(404, {"message": "Plan not found"})
    if item.get("session_id", "default") != session_id:
        return response(403, {"message": "Plan does not belong to the active session"})
    with TABLE.batch_writer() as batch:
        for existing in list_user_items(user_id):
            sk = str(existing.get("SK") or "")
            if existing.get("plan_id") == plan_id and sk.startswith("EXAM_PLAN#"):
                batch.delete_item(Key={"PK": pk_user(user_id), "SK": sk})
    return response(200, {"deleted": True, "plan_id": plan_id})


def handle_planner_update(event, plan_id):
    payload = parse_json_body(event)
    user_id = get_user_id(event, payload)
    session_id = get_session_id(event, payload) or "default"
    item = _get_plan_item(user_id, plan_id)
    if not item:
        return response(404, {"message": "Plan not found"})
    if item.get("session_id", "default") != session_id:
        return response(403, {"message": "Plan does not belong to the active session"})
    return _write_planner(event, plan_id=plan_id)


def handle_planner_recommend_docs(event, plan_id):
    payload = parse_json_body(event)
    query = event.get("queryStringParameters") or {}
    user_id = get_user_id(event, payload)
    session_id = get_session_id(event, payload) or "default"
    limit = _positive_int(payload.get("limit") or query.get("limit"), default=5, minimum=1, maximum=10)
    item = _get_plan_item(user_id, plan_id)
    if not item:
        return response(404, {"message": "Plan not found"})
    if item.get("session_id", "default") != session_id:
        return response(403, {"message": "Plan does not belong to the active session"})

    ready_docs = _ready_session_docs(user_id, session_id)
    if not ready_docs:
        return response(400, {"message": "No ready documents found in the active session"})

    recommended_documents = _rank_docs_with_reasons(ready_docs, item, limit=limit)
    recommended_doc_ids = [doc["doc_id"] for doc in recommended_documents if doc.get("doc_id")]
    return response(
        200,
        {
            "plan_id": plan_id,
            "session_id": session_id,
            "recommended_doc_ids": recommended_doc_ids,
            "recommended_documents": recommended_documents,
        },
    )


def route_request(event):
    request_context = event.get("requestContext", {})
    http_info = request_context.get("http", {})
    method = http_info.get("method") or event.get("httpMethod", "")
    path = event.get("rawPath") or event.get("path", "")
    if method == "POST" and path == "/planner/clarify":
        return handle_planner_clarify(event)
    if method == "POST" and path == "/planner":
        return handle_planner(event)
    if method == "GET" and path == "/planner":
        return handle_planner_list(event)
    match = re.match(r"^/planner/([^/]+)$", path)
    if match and method == "GET":
        return handle_planner_detail(event, match.group(1))
    if match and method in ("PUT", "PATCH"):
        return handle_planner_update(event, match.group(1))
    if match and method == "DELETE":
        return handle_planner_delete(event, match.group(1))
    recommend_match = re.match(r"^/planner/([^/]+)/recommend-docs$", path)
    if recommend_match and method == "POST":
        return handle_planner_recommend_docs(event, recommend_match.group(1))
    return response(404, {"message": f"Route not found: {method} {path}"})


def lambda_handler(event, _context):
    try:
        if not event.get("input") and not event.get("tool_name") and not event.get("name"):
            return route_request(event)
        if tool_name_from_event(event, "") == "recommend_exam_plan_documents":
            payload = {}
            if isinstance(event.get("input"), dict):
                payload.update(event.get("input") or {})
            payload.update({key: event.get(key) for key in ("user_id", "session_id", "plan_id", "limit") if event.get(key) is not None})
            plan_id = str(payload.get("plan_id") or "")
            api_event = {
                "body": "{}",
                "headers": {
                    "X-User-Id": str(payload.get("user_id") or ""),
                    "X-Session-Id": str(payload.get("session_id") or "default"),
                },
                "queryStringParameters": {
                    "user_id": payload.get("user_id"),
                    "session_id": payload.get("session_id") or "default",
                    "limit": payload.get("limit") or 5,
                },
            }
            status_code, body = parse_http_response(handle_planner_recommend_docs(api_event, plan_id))
            if 200 <= status_code < 300:
                return tool_response("recommend_exam_plan_documents", "success", data=body)
            return tool_response("recommend_exam_plan_documents", "error", data=body, errors=[body.get("message") or "Recommendation failed"])
        return run_tool_handler(event, "create_exam_plan", handle_planner)
    except Exception as exc:
        return response(500, {"message": "Internal server error", "error": str(exc)})
