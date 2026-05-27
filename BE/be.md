# StudyBot Backend (Python + SAM + Lambda + DynamoDB Local)

## 1. Mục tiêu

Backend này được scaffold để:
- Deploy dễ lên AWS Lambda sau này (SAM template chuẩn).
- Chạy local giống API Gateway + Lambda bằng `sam local start-api`.
- Mô phỏng DynamoDB bằng Docker (`amazon/dynamodb-local`).
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
- `docker-compose.yml`: DynamoDB Local.
- `scripts/init_dynamodb.py`: script tạo bảng local.
- `local-env.json`: env khi chạy `sam local`.
- `Makefile`: lệnh tắt.

## 3. Chạy local

Yêu cầu:
- Docker
- Python 3.9+ (khớp runtime hiện tại của `template.yaml`)
- AWS SAM CLI

Chạy:

```bash
cd BE
make local-ddb-up
make init-ddb
make build
make api
```

API local:
- `http://127.0.0.1:3000`

Lưu ý:
- `local-env.json` đang dùng `DDB_ENDPOINT_URL=http://host.docker.internal:8000` để Lambda container gọi về DynamoDB Local trên host.
- Nếu môi trường Linux không resolve được `host.docker.internal`, đổi sang endpoint host phù hợp.

## 4. Demo credential

- email: `demo@studybot.com` (BE cũng accept `demo@studybot.ai` để tương thích FE hiện tại)
- password: `123456`
- login trả `user_id=demo`

## 5. Hành vi demo chính

- Upload tạo document với trạng thái `PROCESSING`.
- Endpoint status tự chuyển sang `READY` sau vài giây để mô phỏng pipeline xử lý.
- Summary / concepts / answer / quiz đều có dữ liệu demo ổn định để FE chạy end-to-end.

## 6. Test nhanh bằng cURL

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
