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


def _doc_id_filter(allowed_doc_ids):
    doc_ids = [str(doc_id).strip() for doc_id in (allowed_doc_ids or []) if str(doc_id).strip()]
    if not doc_ids:
        return None
    if len(doc_ids) == 1:
        return {"equals": {"key": "doc_id", "value": doc_ids[0]}}
    return {"orAll": [{"equals": {"key": "doc_id", "value": doc_id}} for doc_id in doc_ids]}


def _retrieve_with_filter(knowledge_base_id, retrieval_query, metadata_filter, number_of_results):
    vector_search = {
        "numberOfResults": number_of_results,
    }
    if metadata_filter:
        vector_search["filter"] = metadata_filter
    response_data = BEDROCK_AGENT_RUNTIME.retrieve(
        knowledgeBaseId=knowledge_base_id,
        retrievalQuery={"text": retrieval_query},
        retrievalConfiguration={
            "vectorSearchConfiguration": vector_search,
        },
    )
    return response_data.get("retrievalResults", []) or []


def _retrieve_selected_documents(knowledge_base_id, retrieval_query, allowed_doc_ids):
    doc_ids = [str(doc_id).strip() for doc_id in (allowed_doc_ids or []) if str(doc_id).strip()]
    if len(doc_ids) <= 1:
        return _retrieve_with_filter(
            knowledge_base_id,
            retrieval_query,
            _doc_id_filter(doc_ids),
            QA_RETRIEVAL_RESULTS,
        )

    per_doc_results = []
    per_doc_limit = max(3, min(6, QA_RETRIEVAL_RESULTS // max(1, len(doc_ids))))
    for doc_id in doc_ids:
        per_doc_results.extend(
            _retrieve_with_filter(
                knowledge_base_id,
                retrieval_query,
                _doc_id_filter([doc_id]),
                per_doc_limit,
            )
        )
    return sorted(per_doc_results, key=lambda item: float(item.get("score") or 0), reverse=True)


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


def _unique_results(results, limit=4):
    unique = []
    seen = set()
    for result in results:
        text = _clean_text((result.get("content") or {}).get("text"))
        if len(text) < 40:
            continue
        key = text[:160].lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(result)
        if len(unique) >= limit:
            break
    return unique


def _context_from_results(results, chars_per_chunk=900):
    snippets = []
    for idx, result in enumerate(results, start=1):
        text = _clean_text((result.get("content") or {}).get("text"))
        if len(text) < 40:
            continue
        source_uri = _extract_source_uri(result)
        document = _extract_document_name(source_uri, "Document")
        snippets.append(f"[{idx}] Source {idx}: {document}\n{text[:chars_per_chunk]}")
    return "\n\n".join(snippets)


def _chunk_text(text, max_chars=7500):
    cleaned = str(text or "").strip()
    if not cleaned:
        return []
    return [cleaned[index:index + max_chars] for index in range(0, len(cleaned), max_chars)]


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
    doc_hints=None,
):
    allowed_doc_ids = allowed_doc_ids or []
    doc_titles_by_id = doc_titles_by_id or {}

    try:
        results = _retrieve_selected_documents(
            knowledge_base_id,
            question,
            allowed_doc_ids,
        )
    except Exception:
        return {
            "answer": _fallback_answer(question, doc_title),
            "citations": [],
            "topic": "General",
        }

    results = [item for item in results if _result_matches_doc_ids(item, allowed_doc_ids)]
    cited_results = _unique_results(results, limit=4)
    citations = [_to_citation(result, doc_title, doc_titles_by_id) for result in cited_results]
    context = _context_from_results(cited_results)

    if not context:
        return {
            "answer": _fallback_answer(question, doc_title),
            "citations": citations,
            "topic": "General",
        }

    prompt = (
        "Answer the student's question using only the grounded context below. "
        "The selected documents may include unrelated context; use the relevant context and ignore unrelated chunks. "
        "If no selected-document context is relevant, say that there is not enough grounded context. "
        "Use bracket citations like [1] or [2] only when they refer to the matching Source number below. "
        "Do not cite source numbers that are not listed below.\n\n"
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


def answer_from_processed_texts(question, doc_texts, fallback_doc_title):
    context_blocks = []
    citations = []
    citation_index = 1
    for doc in doc_texts:
        title = doc.get("title") or doc.get("doc_id") or fallback_doc_title or "Document"
        text = doc.get("text") or ""
        for chunk in _chunk_text(text)[:4]:
            cleaned = _clean_text(chunk)
            if len(cleaned) < 40:
                continue
            context_blocks.append(f"[{citation_index}] Document: {title}\n{cleaned[:1200]}")
            citations.append(
                {
                    "document": title,
                    "slide": None,
                    "chunk_id": f"processed_text_{citation_index}",
                    "source_uri": doc.get("source_uri") or "",
                    "text": cleaned[:1200],
                }
            )
            citation_index += 1
        if len(context_blocks) >= 4:
            break

    if not context_blocks:
        return {}

    prompt = (
        "Answer the student's question using only the grounded processed document text below. "
        "If the text does not contain enough information, say that there is not enough grounded context. "
        "Be concise and cite source numbers in brackets when useful.\n\n"
        f"Question: {question}\n\n"
        "Grounded processed text:\n"
        + "\n\n".join(context_blocks)
        + "\n\nAnswer:"
    )
    try:
        answer = _invoke_text_model(prompt)
    except Exception:
        return {}

    answer = str(answer or "").strip()
    if not answer:
        return {}

    return {
        "answer": answer,
        "citations": citations[:4],
        "topic": citations[0]["document"] if citations else "General",
    }
