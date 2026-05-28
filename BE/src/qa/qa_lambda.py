from core import (
    BEDROCK_KNOWLEDGE_BASE_ID,
    TABLE,
    UPLOADS_BUCKET_NAME,
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
import boto3
from botocore.exceptions import ClientError

from .qa_kb import answer_from_processed_texts, ask_knowledge_base
from memory_utils import create_memory_event
from tool_contract import run_tool_handler


S3 = boto3.client("s3")


def _processed_key_candidates(doc):
    keys = []
    doc_id = str(doc.get("doc_id") or "").strip()
    for field in ("processed_text_s3_key", "processed_s3_key", "processed_s3_prefix"):
        value = str(doc.get(field) or "").strip()
        if not value:
            continue
        if value.endswith(".txt") and value not in keys:
            keys.append(value)
            continue
        if value.endswith("/") and doc_id:
            composed = f"{value}{doc_id}.txt"
            if composed not in keys:
                keys.append(composed)
    user_id = str(doc.get("PK") or "").replace("USER#", "")
    session_id = str(doc.get("session_id") or "default")
    for key in (f"processed/{user_id}/{session_id}/{doc_id}.txt",):
        if user_id and doc_id and key not in keys:
            keys.append(key)
    return keys


def _read_processed_text(doc):
    if not UPLOADS_BUCKET_NAME:
        return "", ""
    for key in _processed_key_candidates(doc):
        try:
            obj = S3.get_object(Bucket=UPLOADS_BUCKET_NAME, Key=key)
            text = obj["Body"].read().decode("utf-8", errors="replace").strip()
            if text:
                return text, f"s3://{UPLOADS_BUCKET_NAME}/{key}"
        except ClientError:
            continue
        except Exception:
            continue
    return "", ""


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

    if not citations:
        processed_texts = []
        for doc in selected_docs:
            text, source_uri = _read_processed_text(doc)
            if text:
                processed_texts.append(
                    {
                        "doc_id": doc.get("doc_id"),
                        "title": doc.get("title", "uploaded.pdf"),
                        "source_uri": source_uri,
                        "text": text,
                    }
                )
        if processed_texts:
            s3_result = answer_from_processed_texts(question, processed_texts, primary_doc.get("title", "uploaded.pdf"))
            if s3_result.get("answer"):
                answer = s3_result["answer"]
                citations = s3_result.get("citations") or citations
                topic = s3_result.get("topic") or topic

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
    create_memory_event(user_id, session_id, "USER", question, {"feature": "chat"})
    create_memory_event(user_id, session_id, "ASSISTANT", answer, {"feature": "chat"})

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
        return run_tool_handler(event, "ask_documents", handle_ask)
    except Exception as exc:
        return response(500, {"message": "Internal server error", "error": str(exc)})
