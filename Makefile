PROMPTS ?= ../nabu-prompts
CHANCERY ?= chancery
DRAGOMAN ?= dragoman
BRIDGE_URL ?= http://127.0.0.1:8082
CHANCERY_PORT ?= 8081
MODEL_TABLE ?= models.claude-cli.yaml

.PHONY: dev check test optimize campaign

dev:
	uv run python -m nabu_evals.dev --prompts "$(PROMPTS)" --chancery-bin "$(CHANCERY)" --dragoman-bin "$(DRAGOMAN)" --bridge-url "$(BRIDGE_URL)" --chancery-port "$(CHANCERY_PORT)" --model-table "$(MODEL_TABLE)"

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run pyright

test:
	uv run pytest

optimize:
	uv run nabu-evals optimize $(ARGS)

campaign:
	uv run nabu-evals campaign $(ARGS)
