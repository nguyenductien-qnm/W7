ifeq ($(OS),Windows_NT)
SHELL := powershell.exe
.SHELLFLAGS := -NoProfile -Command
HASH = \#
LOAD_ENV = if (Test-Path .env) { Get-Content .env | ForEach-Object { $$line = $$_.Trim(); if ($$line -ne '' -and -not $$line.StartsWith('$(HASH)')) { $$parts = $$line -split '=',2; [System.Environment]::SetEnvironmentVariable($$parts[0].Trim(), $$parts[1], 'Process') } } };
PYTHON ?= python
SAM ?= sam
else
SHELL := /bin/zsh
LOAD_ENV = set -a; [ -f .env ] && source .env || true; set +a;
PYTHON ?= python3
SAM ?= sam
endif

.PHONY: local-ddb-up local-ddb-down init-ddb build api

local-ddb-up:
	docker compose up -d dynamodb-local

local-ddb-down:
	docker compose down

init-ddb:
	@$(LOAD_ENV) $(PYTHON) scripts/init_dynamodb.py

build:
	sam build

api:
	@$(LOAD_ENV) $(SAM) local start-api --env-vars local-env.json --port 3000
