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
    sk_summary,
    sk_summary_history,
    summary_text_for,
    testable_concepts_for,
)
import boto3
from botocore.exceptions import ClientError

from .summary_kb import summarize_knowledge_base, summarize_processed_texts
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
    doc_id = doc.get("doc_id")
    for key in (
        f"processed/{user_id}/{session_id}/{doc_id}.txt",
        f"documents/processed/{user_id}/{doc_id}.txt",
    ):
        if user_id and doc_id and key not in keys:
            keys.append(key)
    return keys


def _read_processed_text(doc):
    bucket = UPLOADS_BUCKET_NAME
    if not bucket:
        return ""
    for key in _processed_key_candidates(doc):
        try:
            obj = S3.get_object(Bucket=bucket, Key=key)
            return obj["Body"].read().decode("utf-8", errors="replace").strip()
        except ClientError:
            continue
        except Exception:
            continue
    return ""


def handle_summary(event):
    payload = parse_json_body(event)
    user_id = payload.get("user_id") or get_user_id(event, payload)
    session_id = get_session_id(event, payload) or "default"
    selected_doc_ids = normalize_doc_ids(payload)
    user_question = (payload.get("question") or payload.get("prompt") or "").strip() or "Summarize selected documents."
    if not selected_doc_ids:
        return response(400, {"message": "selected_doc_ids (or doc_id) is required"})

    selected_docs, error_response = get_selected_docs_for_session(user_id, selected_doc_ids, session_id)
    if error_response:
        return error_response

    primary_doc = selected_docs[0]
    fallback_summary_text = summary_text_for(primary_doc.get("title", "uploaded.pdf"))

    fallback_concepts = []
    for doc in selected_docs:
        for concept in doc.get("concepts", []):
            if concept not in fallback_concepts:
                fallback_concepts.append(concept)
    fallback_concepts = fallback_concepts[:5] or testable_concepts_for([])

    summary_text = fallback_summary_text
    testable_concepts = fallback_concepts

    processed_texts = []
    for doc in selected_docs:
        text = _read_processed_text(doc)
        if text:
            processed_texts.append(
                {
                    "doc_id": doc.get("doc_id"),
                    "title": doc.get("title", "uploaded.pdf"),
                    "text": text,
                }
            )

    if processed_texts:
        try:
            s3_summary = summarize_processed_texts(processed_texts, fallback_concepts)
            summary_text = s3_summary.get("summary") or summary_text
            testable_concepts = s3_summary.get("testable_concepts") or testable_concepts
        except Exception:
            pass

    if not processed_texts and BEDROCK_KNOWLEDGE_BASE_ID:
        try:
            kb_summary = summarize_knowledge_base(
                question="Create a concise study summary and identify testable concepts.",
                knowledge_base_id=BEDROCK_KNOWLEDGE_BASE_ID,
                selected_doc_ids=[item.get("doc_id") for item in selected_docs if item.get("doc_id")],
                fallback_concepts=fallback_concepts,
            )
            summary_text = kb_summary.get("summary") or summary_text
            testable_concepts = kb_summary.get("testable_concepts") or testable_concepts
        except Exception:
            pass

    generated_at = now_iso()
    doc_id = primary_doc.get("doc_id")
    selected_ids = [item.get("doc_id") for item in selected_docs if item.get("doc_id")]
    latest_item = {
        "PK": pk_user(user_id),
        "SK": sk_summary(doc_id),
        "doc_id": doc_id,
        "session_id": session_id,
        "question": user_question,
        "selected_doc_ids": selected_ids,
        "summary": summary_text,
        "testable_concepts": testable_concepts[:5],
        "generated_at": generated_at,
    }
    history_item = {
        **latest_item,
        "SK": sk_summary_history(doc_id, generated_at),
    }
    TABLE.put_item(Item=latest_item)
    TABLE.put_item(Item=history_item)

    return response(
        200,
        {
            "doc_id": doc_id,
            "session_id": session_id,
            "selected_doc_ids": selected_ids,
            "summary": summary_text,
            "testable_concepts": testable_concepts[:5],
        },
    )
def lambda_handler(event, _context):
    try:
        return run_tool_handler(event, "summarize_documents", handle_summary)
    except Exception as exc:
        return response(500, {"message": "Internal server error", "error": str(exc)})
