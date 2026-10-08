.PHONY: install test lint app run demo demo-app validate analyse bench status reproduce check clean

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
	uv run radar run --demo && uv run radar score --demo

demo-app:
	RADAR_CSV=data/demo/processed/radar.csv uv run streamlit run app/dashboard.py --server.headless true

validate:
	uv run radar validate

analyse:
	uv run radar analyse

bench:
	uv run pytest -v -k "determinism" --tb=short

status:
	uv run radar status

reproduce:
	uv run radar run --offline && uv run radar score

check:
	uv run ruff check src/ app/ tests/ && uv run pytest -v

clean:
	rm -rf data/demo logs/__pycache__
