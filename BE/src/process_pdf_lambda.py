import io
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import unquote_plus

import boto3

try:
    import pdfplumber
except Exception:  # pragma: no cover
    pdfplumber = None

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None


AWS_REGION = os.environ.get("AWS_REGION", "ap-southeast-1")
DOCUMENTS_TABLE = os.environ.get("DOCUMENTS_TABLE", "StudyBotDocuments")
UPLOADS_BUCKET_NAME = os.environ.get("UPLOADS_BUCKET_NAME", "")
BEDROCK_KNOWLEDGE_BASE_ID = os.environ.get("BEDROCK_KNOWLEDGE_BASE_ID", "")
BEDROCK_DATA_SOURCE_ID = os.environ.get("BEDROCK_DATA_SOURCE_ID", "")
KB_PROCESSED_PREFIX = os.environ.get("KB_PROCESSED_PREFIX", "documents/processed")
USE_TEXTRACT_FALLBACK = os.environ.get("USE_TEXTRACT_FALLBACK", "true").lower() == "true"


s3 = boto3.client("s3", region_name=AWS_REGION)
ddb = boto3.resource("dynamodb", region_name=AWS_REGION).Table(DOCUMENTS_TABLE)
textract = boto3.client("textract", region_name=AWS_REGION)
bedrock_agent = boto3.client("bedrock-agent", region_name=AWS_REGION)


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_object_key(key):
    # Expected upload key: documents/{user_id}/{doc_id}/{filename}
    match = re.match(r"^documents/(?P<user_id>[^/]+)/(?P<doc_id>[^/]+)/(?P<filename>.+)$", key)
    if not match:
        return None
    return match.groupdict()


def update_doc(user_id, doc_id, **attrs):
    item = ddb.get_item(Key={"PK": f"USER#{user_id}", "SK": f"DOC#{doc_id}"}).get("Item")
    if not item:
        item = {"PK": f"USER#{user_id}", "SK": f"DOC#{doc_id}", "doc_id": doc_id}
    item.update(attrs)
    ddb.put_item(Item=item)


def extract_with_pdfplumber(pdf_bytes):
    if not pdfplumber:
        return {"ok": False, "reason": "pdfplumber_not_installed"}

    text_parts = []
    page_count = 0
    non_empty_pages = 0
    table_rows = 0
    table_cells = 0

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page_count = len(pdf.pages)
        for page in pdf.pages:
            text = (page.extract_text() or "").strip()
            if text:
                non_empty_pages += 1
                text_parts.append(text)
            tables = page.extract_tables() or []
            for table in tables:
                table_rows += len(table or [])
                for row in table or []:
                    for cell in row or []:
                        if str(cell or "").strip():
                            table_cells += 1

    full_text = "\n\n".join(text_parts).strip()
    density = len(full_text) / max(page_count, 1)
    non_empty_ratio = non_empty_pages / max(page_count, 1)
    table_quality = table_cells / max(table_rows, 1) if table_rows else 0

    scanned_like = non_empty_ratio < 0.35 or density < 90
    table_poor = table_rows > 0 and table_quality < 1.5
    ok = bool(full_text) and not scanned_like and not table_poor

    return {
        "ok": ok,
        "text": full_text,
        "page_count": page_count,
        "density": density,
        "table_quality": table_quality,
        "scanned_like": scanned_like,
        "table_poor": table_poor,
    }


def extract_with_pypdf(pdf_bytes):
    if not PdfReader:
        return {"ok": False, "reason": "pypdf_not_installed"}

    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = []
    for page in reader.pages:
        pages.append((page.extract_text() or "").strip())
    text = "\n\n".join([p for p in pages if p]).strip()
    density = len(text) / max(len(reader.pages), 1)
    return {"ok": bool(text and density >= 90), "text": text, "page_count": len(reader.pages), "density": density}


def extract_with_textract(bucket, key):
    job = textract.start_document_text_detection(
        DocumentLocation={"S3Object": {"Bucket": bucket, "Name": key}}
    )
    job_id = job["JobId"]

    status = "IN_PROGRESS"
    attempts = 0
    while status == "IN_PROGRESS" and attempts < 90:
        attempts += 1
        time.sleep(2)
        poll = textract.get_document_text_detection(JobId=job_id, MaxResults=1000)
        status = poll.get("JobStatus", "IN_PROGRESS")
        if status in {"SUCCEEDED", "FAILED", "PARTIAL_SUCCESS"}:
            break

    if status not in {"SUCCEEDED", "PARTIAL_SUCCESS"}:
        raise RuntimeError(f"Textract job failed: {status}")

    lines = []
    token = None
    while True:
        page = textract.get_document_text_detection(JobId=job_id, MaxResults=1000, NextToken=token) if token else textract.get_document_text_detection(JobId=job_id, MaxResults=1000)
        for block in page.get("Blocks", []):
            if block.get("BlockType") == "LINE" and block.get("Text"):
                lines.append(block["Text"])
        token = page.get("NextToken")
        if not token:
            break
    return {"text": "\n".join(lines).strip(), "job_id": job_id}


def upload_processed_text(bucket, user_id, doc_id, text):
    processed_key = f"{KB_PROCESSED_PREFIX.rstrip('/')}/{user_id}/{doc_id}.txt"
    s3.put_object(
        Bucket=bucket,
        Key=processed_key,
        Body=text.encode("utf-8"),
        ContentType="text/plain; charset=utf-8",
    )
    return processed_key


def start_kb_ingestion():
    if not BEDROCK_KNOWLEDGE_BASE_ID or not BEDROCK_DATA_SOURCE_ID:
        raise RuntimeError("Missing BEDROCK_KNOWLEDGE_BASE_ID or BEDROCK_DATA_SOURCE_ID")
    response_data = bedrock_agent.start_ingestion_job(
        knowledgeBaseId=BEDROCK_KNOWLEDGE_BASE_ID,
        dataSourceId=BEDROCK_DATA_SOURCE_ID,
        clientToken=str(uuid.uuid4()),
        description="ProcessPdfLambda ingestion trigger",
    )
    return response_data.get("ingestionJob", {})


def process_record(record):
    detail = record.get("detail") or {}
    bucket = (detail.get("bucket") or {}).get("name")
    key = (detail.get("object") or {}).get("key")
    if not bucket or not key:
        # Support direct S3 event shape as fallback
        s3_record = (record.get("s3") or {})
        bucket = ((s3_record.get("bucket") or {}).get("name")) or bucket
        key = ((s3_record.get("object") or {}).get("key")) or key
    if not bucket or not key:
        return {"skipped": True, "reason": "missing_bucket_or_key"}

    key = unquote_plus(key)
    parsed = parse_object_key(key)
    if not parsed:
        return {"skipped": True, "reason": "key_not_in_documents_prefix", "key": key}

    user_id = parsed["user_id"]
    doc_id = parsed["doc_id"]
    filename = parsed["filename"]

    update_doc(user_id, doc_id, kb_status="PROCESSING", processing_started_at=now_iso(), title=filename)

    obj = s3.get_object(Bucket=bucket, Key=key)
    pdf_bytes = obj["Body"].read()

    extraction_mode = "pdfplumber"
    extraction = extract_with_pdfplumber(pdf_bytes)

    if not extraction.get("ok"):
        extraction_mode = "pypdf"
        extraction = extract_with_pypdf(pdf_bytes)

    if (not extraction.get("ok") or extraction.get("scanned_like") or extraction.get("table_poor")) and USE_TEXTRACT_FALLBACK:
        extraction_mode = "textract"
        textract_result = extract_with_textract(bucket, key)
        extraction = {"ok": bool(textract_result.get("text")), "text": textract_result.get("text", ""), "textract_job_id": textract_result.get("job_id")}

    text = (extraction.get("text") or "").strip()
    if not text:
        update_doc(user_id, doc_id, kb_status="FAILED", failure_reason="text_extraction_failed", processed_at=now_iso())
        return {"doc_id": doc_id, "status": "FAILED", "reason": "text_extraction_failed"}

    processed_key = upload_processed_text(bucket, user_id, doc_id, text)
    ingestion_job = start_kb_ingestion()

    update_doc(
        user_id,
        doc_id,
        kb_status="PROCESSING",
        extraction_mode=extraction_mode,
        processed_text_s3_key=processed_key,
        ingestion_job_id=ingestion_job.get("ingestionJobId", ""),
        ingestion_status=ingestion_job.get("status", "STARTING"),
        processed_at=now_iso(),
    )

    return {
        "doc_id": doc_id,
        "status": "PROCESSING",
        "extraction_mode": extraction_mode,
        "processed_text_s3_key": processed_key,
        "ingestion_job_id": ingestion_job.get("ingestionJobId", ""),
        "ingestion_status": ingestion_job.get("status", "STARTING"),
    }


def lambda_handler(event, _context):
    records = event.get("Records") or [event]
    results = []
    for record in records:
        try:
            results.append(process_record(record))
        except Exception as exc:  # pragma: no cover
            results.append({"status": "ERROR", "error": str(exc), "record": record})
    return {"results": results}
