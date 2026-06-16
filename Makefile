.PHONY: all setup install test lint format clean run run-4component run-roadsense run-both serve

all: install

setup:
	pip install -e .
	pip install -r requirements-dev.txt

install:
	pip install -e .
	pip install -r requirements-dev.txt

run:
	python run_pipeline.py --approach both

run-4component:
	python run_pipeline.py --approach 4component

run-roadsense:
	python run_pipeline.py --approach roadsense

run-both:
	python run_pipeline.py --approach both

serve:
	python run_pipeline.py --approach 4component --serve

test:
	python -m pytest tests/ -v --cov=src --cov-report=term-missing

lint:
	black --check src/ tests/ scripts/
	flake8 src/ tests/ scripts/

format:
	black src/ tests/ scripts/

clean:
	rm -rf outputs/*.csv outputs/*.gpkg outputs/*.geojson outputs/*.html
	rm -rf data/processed/
	rm -rf .pytest_cache
	rm -rf __pycache__
	find . -name "__pycache__" -exec rm -rf {} +
	find . -name "*.pyc" -delete
