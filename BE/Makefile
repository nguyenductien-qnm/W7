SHELL := /bin/zsh

.PHONY: local-ddb-up local-ddb-down init-ddb build api

local-ddb-up:
	docker compose up -d dynamodb-local

local-ddb-down:
	docker compose down

init-ddb:
	@set -a; [ -f .env ] && source .env || true; set +a; python3 scripts/init_dynamodb.py

build:
	sam build

api:
	@set -a; [ -f .env ] && source .env || true; set +a; sam local start-api --env-vars local-env.json --port 3000
