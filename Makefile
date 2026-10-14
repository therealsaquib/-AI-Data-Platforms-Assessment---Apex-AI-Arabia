ifeq ($(OS),Windows_NT)
PYTHON = .venv/Scripts/python.exe
else
PYTHON = .venv/bin/python
endif

.PHONY: setup run demo generate test fail-demo schema-drift-demo package

setup:
	python -m venv .venv
	$(PYTHON) -m pip install -r requirements.txt

run:
	python -m src.pipeline

demo:
	python -m src.pipeline

generate:
	python -m src.generate_data

test:
	python -m pytest

fail-demo:
	python -m src.pipeline --fail-demo

schema-drift-demo:
	python -m src.pipeline --schema-drift-demo

package:
	python -m src.package_submission
