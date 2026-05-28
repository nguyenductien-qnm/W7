import os
from datetime import datetime, timezone

import boto3
from botocore.exceptions import BotoCoreError, ClientError, UnknownServiceError


AWS_REGION = os.environ.get("AWS_REGION", "ap-southeast-1")
AGENTCORE_MEMORY_ID = os.environ.get("AGENTCORE_MEMORY_ID", "")
AGENTCORE_MEMORY_STRATEGY_ID = os.environ.get("AGENTCORE_MEMORY_STRATEGY_ID", "")


def _client():
    if not AGENTCORE_MEMORY_ID:
        return None
    try:
        return boto3.client("bedrock-agentcore", region_name=AWS_REGION)
    except (BotoCoreError, UnknownServiceError):
        return None


def _memory_namespace(user_id, session_id):
    return f"/actors/{user_id}/sessions/{session_id}/"


def create_memory_event(user_id, session_id, role, text, metadata=None):
    client = _client()
    content = str(text or "").strip()
    if not client or not content:
        return None
    try:
        return client.create_event(
            memoryId=AGENTCORE_MEMORY_ID,
            actorId=str(user_id),
            sessionId=str(session_id or "default"),
            eventTimestamp=datetime.now(timezone.utc),
            payload=[
                {
                    "conversational": {
                        "content": {"text": content[:8000]},
                        "role": str(role or "OTHER").upper(),
                    }
                }
            ],
            metadata={
                key: {"stringValue": str(value)}
                for key, value in (metadata or {}).items()
                if value is not None
            },
        )
    except (BotoCoreError, ClientError):
        return None


def retrieve_memory_texts(user_id, session_id, query, top_k=3):
    client = _client()
    if not client or not query:
        return []
    search_criteria = {"searchQuery": str(query), "topK": int(top_k or 3)}
    if AGENTCORE_MEMORY_STRATEGY_ID:
        search_criteria["memoryStrategyId"] = AGENTCORE_MEMORY_STRATEGY_ID
    try:
        response = client.retrieve_memory_records(
            memoryId=AGENTCORE_MEMORY_ID,
            namespacePath=_memory_namespace(user_id, session_id),
            searchCriteria=search_criteria,
            maxResults=top_k,
        )
    except (BotoCoreError, ClientError):
        return []

    texts = []
    for record in response.get("memoryRecordSummaries") or []:
        text = ((record.get("content") or {}).get("text") or "").strip()
        if text:
            texts.append(text)
    return texts
