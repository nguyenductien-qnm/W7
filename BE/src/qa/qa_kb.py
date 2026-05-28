import json
import os
import re
from urllib.parse import unquote_plus, urlparse

import boto3


AWS_REGION = os.environ.get("AWS_REGION", "ap-southeast-1")
BEDROCK_GENERATION_MODEL_ID = os.environ.get(
    "BEDROCK_GENERATION_MODEL_ID",
    "global.amazon.nova-2-lite-v1:0",
)
QA_RETRIEVAL_RESULTS = int(os.environ.get("QA_RETRIEVAL_RESULTS", "20"))

BEDROCK_AGENT_RUNTIME = boto3.client("bedrock-agent-runtime", region_name=AWS_REGION)
BEDROCK_RUNTIME = boto3.client("bedrock-runtime", region_name=AWS_REGION)


def _clean_text(value):
    text = unquote_plus(str(value or ""))
    text = re.sub(r"https?://\S+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b[a-z0-9_.-]{25,}\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\S*[%=&]\S*\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_doc_id_from_uri(source_uri):
    uri = str(source_uri or "")
    patterns = [
        r"/raw/[^/]+/[^/]+/(?P<doc_id>doc_[^/.]+)/",
        r"/processed/[^/]+/[^/]+/(?P<doc_id>doc_[^/.]+)\.txt",
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
    return name or fallback


def _to_citation(result, fallback_document, doc_titles_by_id=None):
    source_uri = _extract_source_uri(result)
    metadata = result.get("metadata") or {}
    text = _clean_text((result.get("content") or {}).get("text"))

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
        "text": text,
    }


def _result_matches_doc_ids(result, allowed_doc_ids):
    if not allowed_doc_ids:
        return True

    metadata = result.get("metadata") or {}
    source_uri = str(_extract_source_uri(result) or "").lower()
    allowed = {str(doc_id).lower() for doc_id in allowed_doc_ids if str(doc_id).strip()}
    canonical_uri = any(prefix in source_uri for prefix in ("/raw/", "/processed/"))

    if canonical_uri:
        doc_id_from_uri = _extract_doc_id_from_uri(source_uri).lower()
        if doc_id_from_uri and doc_id_from_uri in allowed:
            return True
        for doc_id in allowed:
            if f"/{doc_id}/" in source_uri or f"/{doc_id}." in source_uri:
                return True

    meta_doc_id = str(
        metadata.get("doc_id")
        or metadata.get("document_id")
        or metadata.get("source_doc_id")
        or ""
    ).lower()
    return bool(meta_doc_id and meta_doc_id in allowed)


def _fallback_answer(question, doc_title):
    return (
        "I do not have enough grounded context from the selected document chunks "
        f"to answer '{question}'. Try rephrasing the question or wait until "
        f"'{doc_title}' finishes ingestion."
    )


def _context_from_results(results, limit=8, chars_per_chunk=900):
    snippets = []
    seen = set()
    for idx, result in enumerate(results, start=1):
        text = _clean_text((result.get("content") or {}).get("text"))
        if len(text) < 40:
            continue
        key = text[:160].lower()
        if key in seen:
            continue
        seen.add(key)
        snippets.append(f"[{idx}] {text[:chars_per_chunk]}")
        if len(snippets) >= limit:
            break
    return "\n\n".join(snippets)


def _extract_model_text(payload):
    content = (((payload.get("output") or {}).get("message") or {}).get("content") or [])
    if content and isinstance(content, list):
        return "\n".join(part.get("text", "") for part in content if isinstance(part, dict)).strip()
    if payload.get("outputText"):
        return str(payload.get("outputText")).strip()
    if payload.get("completion"):
        return str(payload.get("completion")).strip()
    return ""


def _invoke_text_model(prompt, max_tokens=900, temperature=0.1):
    body = {
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": {
            "maxTokens": max_tokens,
            "temperature": temperature,
            "topP": 0.9,
        },
    }
    response = BEDROCK_RUNTIME.invoke_model(
        modelId=BEDROCK_GENERATION_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(body),
    )
    payload = json.loads(response["body"].read().decode("utf-8"))
    return _extract_model_text(payload)


def ask_knowledge_base(
    question,
    knowledge_base_id,
    doc_title,
    allowed_doc_ids=None,
    doc_titles_by_id=None,
):
    allowed_doc_ids = allowed_doc_ids or []
    doc_titles_by_id = doc_titles_by_id or {}

    try:
        response_data = BEDROCK_AGENT_RUNTIME.retrieve(
            knowledgeBaseId=knowledge_base_id,
            retrievalQuery={"text": question},
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": QA_RETRIEVAL_RESULTS,
                }
            },
        )
    except Exception:
        return {
            "answer": _fallback_answer(question, doc_title),
            "citations": [],
            "topic": "General",
        }

    results = response_data.get("retrievalResults", []) or []
    results = [item for item in results if _result_matches_doc_ids(item, allowed_doc_ids)]
    citations = [_to_citation(result, doc_title, doc_titles_by_id) for result in results[:4]]
    context = _context_from_results(results)

    if not context:
        return {
            "answer": _fallback_answer(question, doc_title),
            "citations": citations,
            "topic": "General",
        }

    prompt = (
        "Answer the student's question using only the grounded context below. "
        "If the context is insufficient, say that there is not enough grounded context. "
        "Be concise, specific, and cite chunk numbers in brackets when useful.\n\n"
        f"Question: {question}\n\n"
        f"Grounded context:\n{context}\n\n"
        "Answer:"
    )
    try:
        answer = _invoke_text_model(prompt)
    except Exception:
        answer = _fallback_answer(question, doc_title)

    return {
        "answer": answer or _fallback_answer(question, doc_title),
        "citations": citations,
        "topic": citations[0].get("document") if citations else "General",
    }
