import os
import re

import boto3


AWS_REGION = os.environ.get("AWS_REGION", "ap-southeast-1")
SUMMARY_RETRIEVAL_RESULTS = int(os.environ.get("SUMMARY_RETRIEVAL_RESULTS", "20"))

BEDROCK_AGENT_RUNTIME = boto3.client("bedrock-agent-runtime", region_name=AWS_REGION)


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
    for key in ("x-amz-bedrock-kb-source-uri", "source_uri", "source"):
        if metadata.get(key):
            return str(metadata.get(key))
    return ""


def _result_matches_doc_ids(result, allowed_doc_ids):
    if not allowed_doc_ids:
        return True

    allowed = {str(doc_id).strip().lower() for doc_id in allowed_doc_ids if str(doc_id).strip()}
    source_uri = str(_extract_source_uri(result) or "").lower()
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

    for doc_id in allowed:
        if f"/{doc_id}/" in source_uri or f"/{doc_id}." in source_uri:
            return True
    return False


def _extract_concepts(text, fallback):
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
        if len(found) >= 5:
            break
    if found:
        return found
    return fallback[:5]


def summarize_knowledge_base(question, knowledge_base_id, selected_doc_ids, fallback_concepts):
    response_data = BEDROCK_AGENT_RUNTIME.retrieve(
        knowledgeBaseId=knowledge_base_id,
        retrievalQuery={"text": question},
        retrievalConfiguration={
            "vectorSearchConfiguration": {
                "numberOfResults": SUMMARY_RETRIEVAL_RESULTS,
            }
        },
    )
    results = response_data.get("retrievalResults", []) or []
    results = [item for item in results if _result_matches_doc_ids(item, selected_doc_ids or [])]
    if not results:
        return {
            "summary": "No relevant chunks were found for the selected documents yet. Try again after ingestion completes.",
            "testable_concepts": fallback_concepts[:5],
        }

    snippets = []
    seen = set()
    for result in results:
        text = _clean_text((result.get("content") or {}).get("text"))
        if len(text) < 60:
            continue
        key = text[:120].lower()
        if key in seen:
            continue
        seen.add(key)
        snippets.append(text[:380])
        if len(snippets) >= 4:
            break

    if not snippets:
        return {
            "summary": "Selected documents were retrieved but usable text is still too sparse.",
            "testable_concepts": fallback_concepts[:5],
        }

    summary = (
        "Summary from selected documents:\n\n"
        + "\n\n".join(f"- {snippet}" for snippet in snippets[:3])
    )
    concepts = _extract_concepts(" ".join(snippets), fallback_concepts)
    return {"summary": summary, "testable_concepts": concepts[:5]}
