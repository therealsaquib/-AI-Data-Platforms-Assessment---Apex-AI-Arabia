.PHONY: run test fail-demo schema-drift-demo

run:
	python -m src.pipeline

test:
	python -m pytest

fail-demo:
	python -m src.pipeline --fail-demo

schema-drift-demo:
	python -m src.pipeline --schema-drift-demo
