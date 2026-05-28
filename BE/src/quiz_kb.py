import json
import os
import re

import boto3


AWS_REGION = os.environ.get("AWS_REGION", "ap-southeast-1")
BEDROCK_GENERATION_MODEL_ID = os.environ.get(
    "BEDROCK_GENERATION_MODEL_ID",
    "global.amazon.nova-2-lite-v1:0",
)
QUIZ_RETRIEVAL_RESULTS = int(os.environ.get("QUIZ_RETRIEVAL_RESULTS", "24"))

BEDROCK_AGENT_RUNTIME = boto3.client("bedrock-agent-runtime", region_name=AWS_REGION)
BEDROCK_RUNTIME = boto3.client("bedrock-runtime", region_name=AWS_REGION)


def _clean_text(value):
    text = " ".join(str(value or "").split())
    text = re.sub(r"https?://\S+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b[a-z0-9_.-]{25,}\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\S*[%=&]\S*\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


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


def _extract_doc_id_from_uri(source_uri):
    uri = str(source_uri or "")
    patterns = [
        r"/raw/[^/]+/[^/]+/(?P<doc_id>doc_[^/.]+)/",
        r"/processed/[^/]+/[^/]+/(?P<doc_id>doc_[^/.]+)\.txt",
        r"/documents/raw/[^/]+/(?P<doc_id>doc_[^/.]+)/",
        r"/documents/processed/[^/]+/(?P<doc_id>doc_[^/.]+)\.txt",
    ]
    for pattern in patterns:
        match = re.search(pattern, uri)
        if match:
            return match.group("doc_id")
    return ""


def _result_matches_doc_ids(result, allowed_doc_ids):
    if not allowed_doc_ids:
        return True

    allowed = {str(doc_id).strip().lower() for doc_id in allowed_doc_ids if str(doc_id).strip()}
    source_uri = str(_extract_source_uri(result) or "").lower()
    canonical_uri = any(prefix in source_uri for prefix in ("/raw/", "/processed/", "/documents/raw/", "/documents/processed/"))
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


def _invoke_text_model(prompt, max_tokens=1400, temperature=0.35):
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


def _extract_json_array(text):
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("questions", [])
        return data if isinstance(data, list) else []
    except Exception:
        pass
    match = re.search(r"\[.*\]", text or "", flags=re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _normalize_question(item, source_doc_id="", source_title=""):
    if not isinstance(item, dict):
        return None
    question = str(item.get("question") or "").strip()
    options = item.get("options") or []
    answer = str(item.get("answer") or "").strip().upper()
    explanation = str(item.get("explanation") or "").strip()
    if len(options) != 4:
        return None
    options = [str(option).strip() for option in options]
    if not question or any(not option for option in options):
        return None
    if answer not in {"A", "B", "C", "D"}:
        return None
    question_item = {
        "question": question,
        "options": options,
        "answer": answer,
        "explanation": explanation,
    }
    if source_doc_id and not item.get("source_doc_id"):
        question_item["source_doc_id"] = source_doc_id
    elif item.get("source_doc_id"):
        question_item["source_doc_id"] = str(item.get("source_doc_id"))
    if source_title and not item.get("source_title"):
        question_item["source_title"] = source_title
    elif item.get("source_title"):
        question_item["source_title"] = str(item.get("source_title"))
    return question_item


def _build_mcq(concept, idx, source_doc_id="", source_title=""):
    correct = f"It is one of the main ideas the document asks the student to understand about {concept}."
    distractors = [
        "It is unrelated decorative formatting.",
        "It is only a file storage setting.",
        "It is a browser animation technique.",
    ]
    options = [correct, *distractors]
    rotate = idx % 4
    rotated = options[rotate:] + options[:rotate]
    answer_letter = ["A", "B", "C", "D"][rotated.index(correct)]
    question = {
        "question": f"Which statement best matches the document's treatment of {concept}?",
        "options": rotated,
        "answer": answer_letter,
        "explanation": f"{concept} appears as a testable idea from the selected document concepts.",
    }
    if source_doc_id:
        question["source_doc_id"] = source_doc_id
    if source_title:
        question["source_title"] = source_title
    return question


def _normalize_count(value):
    try:
        return max(5, min(10, int(value or 5)))
    except (TypeError, ValueError):
        return 5


def generate_fallback_quiz(concepts, count=5, source_doc_id="", source_title=""):
    count = _normalize_count(count)
    source = [str(concept).strip() for concept in (concepts or []) if str(concept).strip()]
    source = source or ["Core idea", "Trade-offs", "Architecture", "Reliability", "Performance"]
    questions = []
    for idx, concept in enumerate(source):
        questions.append(_build_mcq(concept, idx, source_doc_id, source_title))
        if len(questions) >= count:
            break
    return questions


def generate_quiz_from_kb(
    knowledge_base_id,
    selected_doc_ids,
    fallback_concepts,
    count=5,
    source_title="",
):
    count = _normalize_count(count)
    try:
        response_data = BEDROCK_AGENT_RUNTIME.retrieve(
            knowledgeBaseId=knowledge_base_id,
            retrievalQuery={"text": "Identify key testable concepts from selected documents."},
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": QUIZ_RETRIEVAL_RESULTS,
                }
            },
        )
    except Exception:
        return []

    results = response_data.get("retrievalResults", []) or []
    results = [item for item in results if _result_matches_doc_ids(item, selected_doc_ids or [])]
    context = _context_from_results(results)
    if not context:
        return []

    prompt = (
        "Generate multiple-choice quiz questions using only the grounded context. "
        f"Return strict JSON as an array of {count} objects. "
        "Each object must have question, options, answer, and explanation. "
        "Include source_doc_id and source_title when known. "
        "options must have exactly 4 strings. answer must be A, B, C, or D. "
        "Questions must be subject-relevant to the selected document, not generic filler.\n\n"
        f"Grounded context:\n{context}\n\n"
        "JSON array:"
    )
    try:
        generated = _invoke_text_model(prompt)
    except Exception:
        return []

    questions = []
    for item in _extract_json_array(generated):
        normalized = _normalize_question(item, selected_doc_ids[0] if selected_doc_ids else "", source_title)
        if normalized:
            questions.append(normalized)
        if len(questions) >= count:
            break
    return questions
