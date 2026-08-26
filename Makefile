.PHONY: setup test lint typecheck backfill api mcp clean

setup:
	uv sync --all-extras --all-groups

test:
	uv run pytest --cov=indiquant --cov-report=term-missing --cov-fail-under=70

lint:
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/
	@echo "Checking for Polars imports outside ingest/ and store/..."
	@! grep -rn "^import polars\|from polars" src/indiquant/factors src/indiquant/engine src/indiquant/validation src/indiquant/report src/indiquant/api || (echo "Polars is restricted to ingest/ and store/. Downstream modules must use pandas." && exit 1)

typecheck:
	uv run mypy --strict src/

backfill:
	uv run python -m indiquant.ingest.backfill

api:
	uv run uvicorn indiquant.api:app --reload

mcp:
	npx @modelcontextprotocol/server

clean:
	rm -rf .venv dist .mypy_cache .pytest_cache .ruff_cache __pycache__
	find . -type d -name __pycache__ -exec rm -rf {} +
