import json
import os
import re

import boto3


AWS_REGION = os.environ.get("AWS_REGION", "ap-southeast-1")
BEDROCK_GENERATION_MODEL_ID = os.environ.get(
    "BEDROCK_GENERATION_MODEL_ID",
    "global.amazon.nova-2-lite-v1:0",
)
SUMMARY_RETRIEVAL_RESULTS = int(os.environ.get("SUMMARY_RETRIEVAL_RESULTS", "20"))

BEDROCK_AGENT_RUNTIME = boto3.client("bedrock-agent-runtime", region_name=AWS_REGION)
BEDROCK_RUNTIME = boto3.client("bedrock-runtime", region_name=AWS_REGION)


def _clean_text(value):
    text = " ".join(str(value or "").split())
    text = re.sub(r"https?://\S+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b[a-z0-9_.-]{25,}\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\S*[%=&]\S*\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_doc_id_from_uri(source_uri):
    uri = str(source_uri or "")
    patterns = [
        r"/documents/raw/[^/]+/(?P<doc_id>doc_[^/.]+)/",
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
    for key in ("x-amz-bedrock-kb-source-uri", "source_uri", "source"):
        if metadata.get(key):
            return str(metadata.get(key))
    return ""


def _result_matches_doc_ids(result, allowed_doc_ids):
    if not allowed_doc_ids:
        return True

    allowed = {str(doc_id).strip().lower() for doc_id in allowed_doc_ids if str(doc_id).strip()}
    source_uri = str(_extract_source_uri(result) or "").lower()
    canonical_uri = "/documents/raw/" in source_uri or "/documents/processed/" in source_uri
    doc_id_from_uri = _extract_doc_id_from_uri(source_uri).lower()
    if doc_id_from_uri and doc_id_from_uri in allowed:
        return True

    metadata = result.get("metadata") or {}
    meta_doc_id = str(
        metadata.get("doc_id")
        or metadata.get("document_id")
        or metadata.get("source_doc_id")
        or ""
    ).lower()
    if meta_doc_id and meta_doc_id in allowed:
        return True

    return canonical_uri and any(
        f"/{doc_id}/" in source_uri or f"/{doc_id}." in source_uri for doc_id in allowed
    )


def _context_from_results(results, limit=10, chars_per_chunk=850):
    snippets = []
    seen = set()
    for idx, result in enumerate(results, start=1):
        text = _clean_text((result.get("content") or {}).get("text"))
        if len(text) < 50:
            continue
        key = text[:160].lower()
        if key in seen:
            continue
        seen.add(key)
        snippets.append(f"[{idx}] {text[:chars_per_chunk]}")
        if len(snippets) >= limit:
            break
    return "\n\n".join(snippets)


def _invoke_text_model(prompt, max_tokens=900, temperature=0.2):
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
    content = (((payload.get("output") or {}).get("message") or {}).get("content") or [])
    if content and isinstance(content, list):
        return "\n".join(part.get("text", "") for part in content if isinstance(part, dict)).strip()
    return str(payload.get("outputText") or payload.get("completion") or "").strip()


def _extract_json_object(text):
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"\{.*\}", text or "", flags=re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except Exception:
        return {}


def summarize_knowledge_base(question, knowledge_base_id, selected_doc_ids, fallback_concepts):
    try:
        response_data = BEDROCK_AGENT_RUNTIME.retrieve(
            knowledgeBaseId=knowledge_base_id,
            retrievalQuery={"text": question},
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": SUMMARY_RETRIEVAL_RESULTS,
                }
            },
        )
    except Exception:
        return {}

    results = response_data.get("retrievalResults", []) or []
    results = [item for item in results if _result_matches_doc_ids(item, selected_doc_ids or [])]
    context = _context_from_results(results)
    if not context:
        return {}

    prompt = (
        "Create a concise study summary from only the grounded context. "
        "Return strict JSON with keys summary and testable_concepts. "
        "summary should be 2-4 short paragraphs, not copied snippets. "
        "testable_concepts must be 3-5 short strings. "
        "If the context is insufficient, keep the summary honest about that.\n\n"
        f"Grounded context:\n{context}\n\n"
        "JSON:"
    )
    try:
        generated = _invoke_text_model(prompt)
    except Exception:
        return {}

    data = _extract_json_object(generated)
    summary = str(data.get("summary") or "").strip()
    concepts = data.get("testable_concepts") or fallback_concepts
    if not isinstance(concepts, list):
        concepts = fallback_concepts
    concepts = [str(item).strip() for item in concepts if str(item).strip()]

    return {
        "summary": summary,
        "testable_concepts": (concepts or fallback_concepts)[:5],
    }
