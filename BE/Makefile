SHELL := /bin/zsh

.PHONY: local-ddb-up local-ddb-down init-ddb build api

local-ddb-up:
	docker compose up -d dynamodb-local

local-ddb-down:
	docker compose down

init-ddb:
	python3 scripts/init_dynamodb.py

build:
	sam build

api:
	sam local start-api --env-vars local-env.json --port 3000
