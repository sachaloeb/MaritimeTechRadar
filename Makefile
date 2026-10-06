.PHONY: install test lint app run demo demo-app validate analyse bench clean

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
	uv run radar run --demo

demo-app:
	RADAR_CSV=data/demo/processed/radar.csv uv run streamlit run app/dashboard.py --server.headless true

validate:
	uv run radar validate

analyse:
	uv run radar analyse

bench:
	uv run pytest -v -k "determinism" --tb=short

clean:
	rm -rf data/raw data/interim data/demo logs/__pycache__
