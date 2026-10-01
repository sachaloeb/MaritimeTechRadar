.PHONY: install test lint app run demo clean

install:
	uv sync --all-extras

test:
	uv run pytest -v

lint:
	uv run ruff check src/ app/ tests/

app:
	uv run streamlit run app/dashboard.py --server.headless true

run:
	uv run radar run

demo:
	uv run radar run --fixtures
	uv run radar score --fixtures

clean:
	rm -rf data/raw data/interim data/demo logs/__pycache__