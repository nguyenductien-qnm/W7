from core import (
    BEDROCK_KNOWLEDGE_BASE_ID,
    TABLE,
    concepts_for,
    get_selected_docs_for_session,
    get_session_id,
    get_user_id,
    normalize_doc_ids,
    normalize_quiz_count,
    now_iso,
    parse_json_body,
    pk_user,
    response,
    sk_quiz,
    sk_quiz_history,
)
from .quiz_kb import generate_fallback_quiz, generate_quiz_from_kb
from tool_contract import run_tool_handler
import re


COUNT_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
}


def _allocate_counts(total, size):
    size = max(1, size)
    base = total // size
    remainder = total % size
    return [base + (1 if index < remainder else 0) for index in range(size)]


def _parse_count_from_text(text, feature):
    value = str(text or "").lower()
    targets = (
        r"(?:flash\s*cards?|flashcards?|cards?)"
        if feature == "flashcards"
        else r"(?:mcq|multiple[-\s]*choice|questions?|quiz(?:zes|z)?)"
    )
    patterns = [
        rf"\b(\d{{1,2}})\s+{targets}\b",
        rf"\b{targets}\s*(?:count|number|num)?\s*(?:of|=|:)?\s*(\d{{1,2}})\b",
        r"\b(?:make|create|generate|give me|give)\s+(\d{1,2})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, value)
        if match:
            return match.group(1)

    for word, number in COUNT_WORDS.items():
        word_patterns = [
            rf"\b{word}\s+{targets}\b",
            rf"\b(?:make|create|generate|give me|give)\s+{word}\b",
        ]
        if any(re.search(pattern, value) for pattern in word_patterns):
            return number
    return None


def _parse_difficulty_from_text(text):
    value = str(text or "").lower()
    if re.search(r"\b(hard|difficult|challenging|advanced|tough)\b", value):
        return "hard"
    if re.search(r"\b(easy|simple|basic|beginner)\b", value):
        return "easy"
    if re.search(r"\b(medium|moderate|normal|standard)\b", value):
        return "medium"
    return None


def _normalize_difficulty(value):
    difficulty = str(value or "medium").strip().lower()
    return difficulty if difficulty in {"easy", "medium", "hard"} else "medium"


def handle_quiz(event):
    payload = parse_json_body(event)
    user_id = payload.get("user_id") or get_user_id(event, payload)
    session_id = get_session_id(event, payload) or "default"
    selected_doc_ids = normalize_doc_ids(payload)
    requested_feature = str(payload.get("feature") or "quiz").strip().lower()
    if requested_feature not in ("quiz", "flashcards"):
        requested_feature = "quiz"
    user_question = (payload.get("question") or payload.get("prompt") or "").strip()
    if not user_question:
        user_question = "Create flash cards from selected documents." if requested_feature == "flashcards" else "Generate quiz from selected documents."
    parsed_count = _parse_count_from_text(user_question, requested_feature)
    parsed_difficulty = _parse_difficulty_from_text(user_question)
    default_difficulty = "easy" if requested_feature == "flashcards" else "medium"
    default_count = 6 if requested_feature == "flashcards" else 5
    difficulty = _normalize_difficulty(parsed_difficulty or payload.get("difficulty") or default_difficulty)
    requested_count = parsed_count or payload.get("count") or default_count

    if not selected_doc_ids:
        return response(400, {"message": "selected_doc_ids (or doc_id) is required"})

    selected_docs, error_response = get_selected_docs_for_session(user_id, selected_doc_ids, session_id)
    if error_response:
        return error_response

    primary_doc = selected_docs[0]
    doc_id = primary_doc.get("doc_id")

    fallback_concepts = []
    for doc in selected_docs:
        for concept in doc.get("concepts", []):
            if concept not in fallback_concepts:
                fallback_concepts.append(concept)
    fallback_concepts = fallback_concepts[:10] or concepts_for(primary_doc.get("title"))

    count = normalize_quiz_count(requested_count)

    questions = []
    if BEDROCK_KNOWLEDGE_BASE_ID:
        allocations = _allocate_counts(count, len(selected_docs))
        for doc, doc_count in zip(selected_docs, allocations):
            if doc_count <= 0:
                continue
            doc_concepts = doc.get("concepts") or fallback_concepts
            try:
                questions.extend(
                    generate_quiz_from_kb(
                        knowledge_base_id=BEDROCK_KNOWLEDGE_BASE_ID,
                        selected_doc_ids=[doc.get("doc_id")],
                        fallback_concepts=doc_concepts,
                        count=doc_count,
                        source_title=doc.get("title", ""),
                        difficulty=difficulty,
                    )
                )
            except Exception:
                pass

    if len(questions) < count:
        remaining = count - len(questions)
        allocations = _allocate_counts(remaining, len(selected_docs))
        for doc, doc_count in zip(selected_docs, allocations):
            if doc_count <= 0:
                continue
            questions.extend(
                generate_fallback_quiz(
                    doc.get("concepts") or fallback_concepts,
                    count=doc_count,
                    source_doc_id=doc.get("doc_id", ""),
                    source_title=doc.get("title", ""),
                    difficulty=difficulty,
                )
            )
    questions = questions[:count]

    generated_at = now_iso()
    selected_ids = [item.get("doc_id") for item in selected_docs if item.get("doc_id")]
    latest_item = {
        "PK": pk_user(user_id),
        "SK": sk_quiz(doc_id),
        "doc_id": doc_id,
        "session_id": session_id,
        "feature": requested_feature,
        "question": user_question,
        "selected_doc_ids": selected_ids,
        "difficulty": difficulty,
        "count": count,
        "questions": questions,
        "generated_at": generated_at,
    }
    history_item = {
        **latest_item,
        "SK": sk_quiz_history(doc_id, generated_at),
    }
    TABLE.put_item(Item=latest_item)
    TABLE.put_item(Item=history_item)

    return response(
        200,
        {
            "doc_id": doc_id,
            "session_id": session_id,
            "selected_doc_ids": selected_ids,
            "difficulty": difficulty,
            "count": count,
            "questions": questions,
        },
    )


def lambda_handler(event, _context):
    try:
        tool_name = "generate_flashcards" if (event.get("input") or event).get("feature") == "flashcards" else "generate_quiz"
        return run_tool_handler(event, tool_name, handle_quiz)
    except Exception as exc:
        return response(500, {"message": "Internal server error", "error": str(exc)})
