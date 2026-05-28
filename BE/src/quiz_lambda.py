from app import (
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
from quiz_kb import generate_fallback_quiz, generate_quiz_from_kb


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
    difficulty = str(payload.get("difficulty") or "medium").lower()
    requested_count = payload.get("count", 5)

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
    if difficulty == "easy":
        count = max(5, min(count, 7))
    elif difficulty == "hard":
        count = min(10, max(count, 7))

    questions = []
    if BEDROCK_KNOWLEDGE_BASE_ID:
        try:
            questions = generate_quiz_from_kb(
                knowledge_base_id=BEDROCK_KNOWLEDGE_BASE_ID,
                selected_doc_ids=[item.get("doc_id") for item in selected_docs if item.get("doc_id")],
                fallback_concepts=fallback_concepts,
                count=count,
            )
        except Exception:
            questions = []

    if not questions:
        questions = generate_fallback_quiz(fallback_concepts, count=count)

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
            "questions": questions,
        },
    )


def lambda_handler(event, _context):
    try:
        return handle_quiz(event)
    except Exception as exc:
        return response(500, {"message": "Internal server error", "error": str(exc)})
