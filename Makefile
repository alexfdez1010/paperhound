.PHONY: help install test test-unit test-integration lint format check build clean

help:
	@echo "Targets:"
	@echo "  install            Sync dev dependencies (creates .venv)"
	@echo "  test               Run unit tests"
	@echo "  test-integration   Run live network integration tests (PAPERHOUND_RUN_INTEGRATION=1)"
	@echo "  lint               ruff check"
	@echo "  format             ruff format (auto-fix)"
	@echo "  check              lint + format check + unit tests"
	@echo "  build              Build sdist + wheel into dist/"
	@echo "  clean              Remove build/cache artifacts"

install:
	uv sync --extra dev

test test-unit:
	uv run pytest tests/unit

test-integration:
	PAPERHOUND_RUN_INTEGRATION=1 uv run pytest tests/integration

lint:
	uv run ruff check

format:
	uv run ruff format

check:
	uv run ruff check
	uv run ruff format --check
	uv run pytest tests/unit

build:
	uv build

clean:
	rm -rf dist/ build/ *.egg-info .pytest_cache .ruff_cache .coverage htmlcov
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
