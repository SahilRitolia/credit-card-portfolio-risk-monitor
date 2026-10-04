PY ?= python
VENV ?= .venv

.PHONY: setup audit build test lint app screenshots readme-results notebooks verify package all

setup:
	$(PY) -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -r requirements-dev.txt
	$(VENV)/bin/python -m playwright install chromium || echo "Playwright browser not installed; screenshots fall back to chart exports"

audit:
	CCRM_DATA_MODE=local $(PY) -m src.pipeline --stage audit

build:
	CCRM_DATA_MODE=local $(PY) -m src.pipeline --stage all

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

app:
	CCRM_DATA_MODE=deploy $(PY) -m streamlit run app/streamlit_app.py

screenshots:
	$(PY) scripts/capture_screenshots.py

readme-results:
	$(PY) scripts/render_readme_numbers.py

notebooks:
	for nb in notebooks/*.ipynb; do CCRM_DATA_MODE=deploy $(PY) -m jupyter nbconvert --to notebook --execute --inplace $$nb; done

verify:
	$(PY) scripts/verify_deliverables.py

package:
	$(PY) scripts/package.py

all: build readme-results notebooks test lint screenshots verify package
