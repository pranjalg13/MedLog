.PHONY: help install demo seed api ui evals redteam test clean precompute demo-ui
PY := .venv/bin/python

help:
	@echo "make install   create venv and install dependencies"
	@echo "make demo      seed the three demo patients (needs MEM0_API_KEY)"
	@echo "make api       run the FastAPI service on :8000"
	@echo "make ui        run the Streamlit app on :8501"
	@echo "make evals     run the ablation (no_memory / full_context / medlog)"
	@echo "make redteam   run the safety suite"
	@echo "make test      run unit tests (no API keys needed)"
	@echo "make precompute build demo_cache/ (needs BOTH keys, run once before deploying)"
	@echo "make demo-ui   run the public-demo build locally, with no Anthropic key"

install:
	uv venv --python 3.12
	uv pip install -e ".[dev]"
	@test -f .env || (cp .env.example .env && echo "-> created .env, add your keys")

demo seed:
	$(PY) seed.py

api:
	$(PY) -m uvicorn medlog.api.main:app --reload --port 8000

ui:
	$(PY) -m streamlit run ui/app.py --server.port 8501

evals:
	$(PY) evals/run.py

redteam:
	$(PY) evals/run.py --redteam

test:
	$(PY) -m pytest -q

precompute:
	$(PY) precompute.py

# Exactly what the public deployment runs. If this works with ANTHROPIC_API_KEY
# unset, it cannot need the key in production.
demo-ui:
	MEDLOG_DEMO=1 MEDLOG_SINGLE_PROCESS=1 ANTHROPIC_API_KEY= \
	  $(PY) -m streamlit run ui/app.py --server.port 8501

clean:
	rm -f medlog.db && rm -rf .pytest_cache **/__pycache__
