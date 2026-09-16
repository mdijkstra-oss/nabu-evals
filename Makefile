PROMPTS ?= ../nabu-prompts
CHANCERY ?= chancery
DRAGOMAN ?= dragoman
BRIDGE_URL ?=
CHANCERY_PORT ?= 8081
MODEL_TABLE ?=

.PHONY: dev check test optimize campaign

dev:
	uv run python -m nabu_evals.dev --prompts "$(PROMPTS)" --chancery-bin "$(CHANCERY)" --dragoman-bin "$(DRAGOMAN)" --chancery-port "$(CHANCERY_PORT)" $(if $(BRIDGE_URL),--bridge-url "$(BRIDGE_URL)") $(if $(MODEL_TABLE),--model-table "$(MODEL_TABLE)")

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
