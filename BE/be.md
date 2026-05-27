# StudyBot Backend (Python + SAM + Lambda + DynamoDB)

## 1. Mục tiêu

Backend này được scaffold để:
- Deploy dễ lên AWS Lambda sau này (SAM template chuẩn).
- Chạy local giống API Gateway + Lambda bằng `sam local start-api`.
- Mặc định kết nối DynamoDB trên AWS thật (table `StudyBotDocuments`).
- Có đủ endpoint cho FE:
  - `POST /login`
  - `POST /upload`
  - `GET /documents`
  - `GET /documents/{doc_id}`
  - `GET /documents/{doc_id}/status`
  - `POST /ask`
  - `POST /quiz`
  - `GET /dashboard`

## 2. Cấu trúc

- `template.yaml`: SAM stack (HttpApi + Lambda + DynamoDB table).
- `src/app.py`: Lambda handler + toàn bộ route logic demo.
- `src/requirements.txt`: dependency Python.
- `docker-compose.yml`: DynamoDB Local (tùy chọn, chỉ khi muốn giả lập local).
- `scripts/init_dynamodb.py`: script tạo bảng local (tùy chọn).
- `local-env.json`: env khi chạy `sam local`.
- `Makefile`: lệnh tắt.

## 3. ENV

File dùng:
- `.env`: biến môi trường local thực tế (đã ignore git).
- `.env.example`: mẫu ENV, có sẵn output hạ tầng đã deploy.
- `local-env.json`: env riêng cho `sam local start-api`.

Biến quan trọng:
- `AWS_REGION`
- `DOCUMENTS_TABLE`
- `UPLOADS_BUCKET_NAME`
- `BEDROCK_KNOWLEDGE_BASE_ID`
- `BEDROCK_DATA_SOURCE_ID`
- `VECTOR_INDEX_ARN`
- `INFRA_STACK_ARN`
- `DDB_ENDPOINT_URL` (tùy chọn, chỉ dùng khi muốn trỏ qua DynamoDB Local)
- `INGESTION_MODE`:
  - `mock` (dev): complete upload -> mock trạng thái xử lý
  - `bedrock` (prod): complete upload -> gọi `StartIngestionJob` vào Knowledge Base

## 4. Chạy local

Yêu cầu:
- Python 3.9+ (khớp runtime hiện tại của `template.yaml`)
- AWS SAM CLI
- AWS credentials/profile có quyền đọc/ghi DynamoDB table `StudyBotDocuments`

Chạy:

```bash
cd BE
cp .env.example .env
make build
make api
```

API local:
- `http://127.0.0.1:3000`

Lưu ý:
- `local-env.json` đã cấu hình chạy với DynamoDB trên AWS thật.
- Nếu muốn quay lại DynamoDB Local: set `DDB_ENDPOINT_URL` trong `.env` hoặc `local-env.json`, rồi dùng thêm `make local-ddb-up` + `make init-ddb`.

## 5. Demo credential

- email: `demo@studybot.com` (BE cũng accept `demo@studybot.ai` để tương thích FE hiện tại)
- password: `123456`
- login trả `user_id=demo`

## 6. Hành vi demo chính

- Upload tạo document với trạng thái `PROCESSING`.
- Endpoint status tự chuyển sang `READY` sau vài giây để mô phỏng pipeline xử lý.
- Summary / concepts / answer / quiz đều có dữ liệu demo ổn định để FE chạy end-to-end.

## 7. Test nhanh bằng cURL

```bash
# login
curl -s -X POST http://127.0.0.1:3000/login \
  -H "Content-Type: application/json" \
  -d '{"email":"demo@studybot.ai","password":"123456"}'

# upload (multipart giống FE)
curl -s -X POST http://127.0.0.1:3000/upload \
  -F "file=@/path/to/sample.pdf" \
  -F "user_id=demo"

# list documents
curl -s http://127.0.0.1:3000/documents
```
