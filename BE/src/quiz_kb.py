import os
import re

import boto3


AWS_REGION = os.environ.get("AWS_REGION", "ap-southeast-1")
QUIZ_RETRIEVAL_RESULTS = int(os.environ.get("QUIZ_RETRIEVAL_RESULTS", "24"))

BEDROCK_AGENT_RUNTIME = boto3.client("bedrock-agent-runtime", region_name=AWS_REGION)


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


def _result_matches_doc_ids(result, allowed_doc_ids):
    if not allowed_doc_ids:
        return True

    allowed = {str(doc_id).strip().lower() for doc_id in allowed_doc_ids if str(doc_id).strip()}
    source_uri = str(_extract_source_uri(result) or "").lower()
    metadata = result.get("metadata") or {}
    meta_doc_id = str(
        metadata.get("doc_id")
        or metadata.get("document_id")
        or metadata.get("source_doc_id")
        or ""
    ).lower()
    if meta_doc_id and meta_doc_id in allowed:
        return True

    for doc_id in allowed:
        if f"/{doc_id}/" in source_uri or f"/{doc_id}." in source_uri:
            return True
    return False


def _extract_concepts(text, fallback_concepts):
    candidates = [
        "CAP theorem",
        "Replication",
        "Consistency model",
        "Quorum",
        "Partition tolerance",
        "Eventual consistency",
        "Leader election",
        "Fault tolerance",
        "Consensus",
        "Distributed systems",
    ]
    found = []
    lower_text = text.lower()
    for concept in candidates:
        if concept.lower() in lower_text and concept not in found:
            found.append(concept)
        if len(found) >= 10:
            break

    for concept in fallback_concepts:
        if concept not in found:
            found.append(concept)
        if len(found) >= 10:
            break
    return found


def _build_mcq(concept, idx):
    correct = f"It explains trade-offs and reliability behavior related to {concept}."
    distractors = [
        "It is mainly a frontend styling technique.",
        "It is a media file compression format.",
        "It is only about DNS record management.",
    ]
    options = [correct, *distractors]

    # Rotate so answer letter is not always A.
    rotate = idx % 4
    rotated = options[rotate:] + options[:rotate]
    answer_letter = ["A", "B", "C", "D"][rotated.index(correct)]

    return {
        "question": f"Which statement best describes {concept} in distributed systems?",
        "options": rotated,
        "answer": answer_letter,
        "explanation": f"{concept} is used to reason about distributed-system correctness and trade-offs.",
    }


def generate_fallback_quiz(concepts, count=5):
    count = max(5, min(10, int(count or 5)))
    questions = []
    for idx, concept in enumerate((concepts or [])[:count]):
        questions.append(_build_mcq(concept, idx))
    return questions


def generate_quiz_from_kb(
    knowledge_base_id,
    selected_doc_ids,
    fallback_concepts,
    count=5,
):
    response_data = BEDROCK_AGENT_RUNTIME.retrieve(
        knowledgeBaseId=knowledge_base_id,
        retrievalQuery={"text": "Identify key testable concepts from selected documents."},
        retrievalConfiguration={
            "vectorSearchConfiguration": {
                "numberOfResults": QUIZ_RETRIEVAL_RESULTS,
            }
        },
    )
    results = response_data.get("retrievalResults", []) or []
    results = [item for item in results if _result_matches_doc_ids(item, selected_doc_ids or [])]

    snippet_text = " ".join(
        _clean_text((item.get("content") or {}).get("text"))
        for item in results[:10]
    )
    concepts = _extract_concepts(snippet_text, fallback_concepts)
    if not concepts:
        concepts = ["CAP theorem", "Replication", "Consistency model", "Quorum", "Partition tolerance"]

    count = max(5, min(10, int(count or 5)))
    questions = []
    for idx, concept in enumerate(concepts):
        questions.append(_build_mcq(concept, idx))
        if len(questions) >= count:
            break
    return questions
