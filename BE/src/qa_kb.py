import os
import re
from urllib.parse import unquote_plus
from urllib.parse import urlparse

import boto3


AWS_REGION = os.environ.get("AWS_REGION", "ap-southeast-1")
QA_RETRIEVAL_RESULTS = int(os.environ.get("QA_RETRIEVAL_RESULTS", "20"))

BEDROCK_AGENT_RUNTIME = boto3.client("bedrock-agent-runtime", region_name=AWS_REGION)


def _normalize_text(value):
    text = unquote_plus(str(value or ""))
    text = re.sub(r"https?://\S+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b[a-z0-9_.-]{25,}\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\S*[%=&]\S*\b", " ", text)
    text = re.sub(r"\b\S*tls\S*\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\S*mongosh\S*\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_doc_id_from_uri(source_uri):
    uri = str(source_uri or "")
    patterns = [
        r"/documents/[^/]+/(?P<doc_id>doc_[^/.]+)/",
        r"/documents/processed/[^/]+/(?P<doc_id>doc_[^/.]+)\.txt",
    ]
    for pattern in patterns:
        match = re.search(pattern, uri)
        if match:
            return match.group("doc_id")
    return ""


def _extract_source_uri(result):
    location = result.get("location") or {}
    s3_location = location.get("s3Location") or {}
    if s3_location.get("uri"):
        return s3_location.get("uri")

    metadata = result.get("metadata") or {}
    # Common metadata keys from Bedrock KB ingestion
    for key in ("x-amz-bedrock-kb-source-uri", "source_uri", "source"):
        if metadata.get(key):
            return str(metadata.get(key))
    return ""


def _extract_document_name(source_uri, fallback, doc_titles_by_id=None):
    doc_titles_by_id = doc_titles_by_id or {}
    extracted_doc_id = _extract_doc_id_from_uri(source_uri)
    if extracted_doc_id and doc_titles_by_id.get(extracted_doc_id):
        return doc_titles_by_id[extracted_doc_id]

    if not source_uri:
        return fallback
    parsed = urlparse(source_uri)
    name = os.path.basename(parsed.path or "").strip()
    if name.startswith("doc_") and name.endswith(".txt") and extracted_doc_id and doc_titles_by_id.get(extracted_doc_id):
        return doc_titles_by_id[extracted_doc_id]
    return name or fallback


def _to_citation(result, fallback_document, doc_titles_by_id=None):
    source_uri = _extract_source_uri(result)
    metadata = result.get("metadata") or {}

    page = metadata.get("page") or metadata.get("page_number") or metadata.get("slide")
    try:
        page = int(page) if page is not None else None
    except Exception:
        page = None

    chunk_id = str(
        metadata.get("chunk_id")
        or metadata.get("x-amz-bedrock-kb-chunk-id")
        or metadata.get("id")
        or ""
    )

    return {
        "document": _extract_document_name(source_uri, fallback_document, doc_titles_by_id),
        "slide": page,
        "chunk_id": chunk_id,
        "source_uri": source_uri,
    }


def _result_matches_doc_ids(result, allowed_doc_ids):
    if not allowed_doc_ids:
        return True

    metadata = result.get("metadata") or {}
    source_uri = str(_extract_source_uri(result) or "").lower()
    allowed = {str(doc_id).lower() for doc_id in allowed_doc_ids if str(doc_id).strip()}

    # Match by source URI patterns from our ingestion flow:
    # - documents/{user_id}/{doc_id}/{filename}
    # - documents/processed/{user_id}/{doc_id}.txt
    for doc_id in allowed:
        if f"/{doc_id}/" in source_uri or f"/{doc_id}." in source_uri:
            return True

    # Optional metadata keys if present.
    meta_doc_id = str(
        metadata.get("doc_id")
        or metadata.get("document_id")
        or metadata.get("source_doc_id")
        or ""
    ).lower()
    if meta_doc_id and meta_doc_id in allowed:
        return True

    return False


def _fallback_answer(question, doc_title):
    return (
        f"I could not find grounded chunks in Knowledge Base for your question: '{question}'. "
        f"Please try rephrasing or wait until document '{doc_title}' finishes ingestion."
    )


def _select_useful_snippets(results, limit=2):
    snippets = []
    seen = set()
    for result in results:
        raw_text = (result.get("content") or {}).get("text")
        cleaned = _normalize_text(raw_text)
        if not cleaned:
            continue
        if len(cleaned) < 50:
            continue
        key = cleaned[:120].lower()
        if key in seen:
            continue
        seen.add(key)
        snippets.append(cleaned[:420])
        if len(snippets) >= limit:
            break
    return snippets


def ask_knowledge_base(
    question,
    knowledge_base_id,
    doc_title,
    allowed_doc_ids=None,
    doc_titles_by_id=None,
):
    allowed_doc_ids = allowed_doc_ids or []
    doc_titles_by_id = doc_titles_by_id or {}

    response_data = BEDROCK_AGENT_RUNTIME.retrieve(
        knowledgeBaseId=knowledge_base_id,
        retrievalQuery={"text": question},
        retrievalConfiguration={
            "vectorSearchConfiguration": {
                "numberOfResults": QA_RETRIEVAL_RESULTS,
            }
        },
    )
    results = response_data.get("retrievalResults", []) or []
    results = [item for item in results if _result_matches_doc_ids(item, allowed_doc_ids or [])]
    if not results:
        return {
            "answer": _fallback_answer(question, doc_title),
            "citations": [],
            "topic": "General",
        }

    citations = []
    for result in results[:3]:
        citations.append(_to_citation(result, doc_title, doc_titles_by_id))

    snippets = _select_useful_snippets(results, limit=2)

    if not snippets:
        return {
            "answer": _fallback_answer(question, doc_title),
            "citations": citations,
            "topic": "General",
        }

    answer = "Từ các tài liệu bạn đã chọn, câu trả lời bám theo nội dung như sau:\n\n" + "\n\n".join(
        f"- {snippet}" for snippet in snippets
    )
    return {
        "answer": answer,
        "citations": citations,
        "topic": citations[0].get("document") or "General",
    }
