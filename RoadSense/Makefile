.PHONY: all setup preprocess module_a module_b module_c score evaluate visualise test lint clean

all: preprocess score visualise

setup:
	conda env create -f environment.yml
	cp .env.example .env
	@echo "Edit .env with your API tokens before running the pipeline."

preprocess:
	python -m src.preprocessing

module_a:
	python -m src.module_a

module_b:
	python -m src.module_b

module_c:
	python -m src.module_c

score:
	python -m src.scoring

evaluate:
	python -m src.evaluation

visualise:
	python -m src.visualise

test:
	pytest tests/ -v

lint:
	black src/ tests/
	flake8 src/ tests/

clean:
	rm -f data/processed/*.gpkg
	rm -f outputs/**/*
	find . -name "__pycache__" -exec rm -rf {} +
