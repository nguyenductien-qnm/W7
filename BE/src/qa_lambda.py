from app import (
    BEDROCK_KNOWLEDGE_BASE_ID,
    TABLE,
    get_selected_docs_for_session,
    get_session_id,
    get_user_id,
    normalize_doc_ids,
    now_iso,
    parse_json_body,
    pk_user,
    response,
    sk_question,
)
from qa_kb import ask_knowledge_base


def handle_ask(event):
    payload = parse_json_body(event)
    user_id = get_user_id(event, payload)
    session_id = get_session_id(event, payload) or "default"
    selected_doc_ids = normalize_doc_ids(payload)
    question = (payload.get("question") or "").strip()

    if not selected_doc_ids or not question:
        return response(400, {"message": "selected_doc_ids (or doc_id) and question are required"})

    selected_docs, error_response = get_selected_docs_for_session(user_id, selected_doc_ids, session_id)
    if error_response:
        return error_response

    primary_doc = selected_docs[0]
    doc_id = primary_doc.get("doc_id")

    created_at = now_iso()
    topic = (primary_doc.get("concepts") or ["General"])[0]
    answer = (
        "I do not have enough grounded context from the selected document chunks to answer this yet. "
        "Try rephrasing the question or wait until document ingestion completes."
    )
    citations = []

    if BEDROCK_KNOWLEDGE_BASE_ID:
        kb_result = ask_knowledge_base(
            question=question,
            knowledge_base_id=BEDROCK_KNOWLEDGE_BASE_ID,
            doc_title=primary_doc.get("title", "uploaded.pdf"),
            allowed_doc_ids=[item.get("doc_id") for item in selected_docs if item.get("doc_id")],
            doc_titles_by_id={
                item.get("doc_id"): item.get("title", "uploaded.pdf")
                for item in selected_docs
                if item.get("doc_id")
            },
        )
        answer = kb_result.get("answer") or answer
        citations = kb_result.get("citations") or citations
        topic = kb_result.get("topic") or topic

    TABLE.put_item(
        Item={
            "PK": pk_user(user_id),
            "SK": sk_question(created_at),
            "doc_id": doc_id,
            "session_id": session_id,
            "selected_doc_ids": [item.get("doc_id") for item in selected_docs if item.get("doc_id")],
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
            "session_id": session_id,
            "selected_doc_ids": [item.get("doc_id") for item in selected_docs if item.get("doc_id")],
            "question": question,
            "answer": answer,
            "citation": citations,
            "citations": citations,
        },
    )


def lambda_handler(event, _context):
    try:
        return handle_ask(event)
    except Exception as exc:
        return response(500, {"message": "Internal server error", "error": str(exc)})
