ROOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
export UV_CACHE_DIR := $(ROOT).cache/uv
UV_RUN := uv run --frozen

.PHONY: sync test check fmt run

sync:
	uv sync --frozen

test:
	$(UV_RUN) pytest --cov=cloudyreader --cov-report=term-missing --cov-fail-under=75

check:
	$(UV_RUN) ruff check .
	$(UV_RUN) ruff format --check .

fmt:
	$(UV_RUN) ruff check --fix .
	$(UV_RUN) ruff format .

run:
	$(UV_RUN) python -m cloudyreader
