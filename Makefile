PROMPTS ?= ../nabu-prompts
CHANCERY ?= chancery
DRAGOMAN ?= dragoman
DRAGOMAN_REPO ?= ../../dragoman
EVAL_DRAGOMAN ?= .dev/dragoman
CODEX_BRIDGE ?= .dev/codex-bridge
CODEX_BRIDGE_ADDR ?= 127.0.0.1:8084
CODEX_BIN ?= codex
BRIDGE_URL ?=
CHANCERY_PORT ?= 8081
MODEL_TABLE ?=

.PHONY: dev check test optimize campaign report build-dragoman build-codex-bridge codex-bridge

build-dragoman:
	mkdir -p .dev
	go build -C "$(DRAGOMAN_REPO)" -o "$(CURDIR)/$(EVAL_DRAGOMAN)" ./cmd/dragoman

build-codex-bridge:
	mkdir -p .dev
	go build -C "$(DRAGOMAN_REPO)" -o "$(CURDIR)/$(CODEX_BRIDGE)" ./cmd/codex-bridge

codex-bridge: build-codex-bridge
	CODEX_HOME="$${CODEX_BRIDGE_HOME:-$$HOME/.codex}" "$(CODEX_BRIDGE)" --addr "$(CODEX_BRIDGE_ADDR)" --binary "$(CODEX_BIN)"

dev: build-dragoman
	uv run python -m nabu_evals.dev --prompts "$(PROMPTS)" --chancery-bin "$(CHANCERY)" --dragoman-bin "$(EVAL_DRAGOMAN)" --chancery-port "$(CHANCERY_PORT)" $(if $(BRIDGE_URL),--bridge-url "$(BRIDGE_URL)") $(if $(MODEL_TABLE),--model-table "$(MODEL_TABLE)")

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run pyright

test:
	uv run pytest

optimize: build-dragoman
	uv run nabu-evals optimize --dragoman-bin "$(EVAL_DRAGOMAN)" $(ARGS)

campaign: build-dragoman
	uv run nabu-evals campaign --dragoman-bin "$(EVAL_DRAGOMAN)" $(ARGS)

report:
	uv run nabu-evals report $(ARGS)
