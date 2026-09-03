.PHONY: dev test lint typecheck eval kb validate-kb smoke deploy

dev:
	uv run uvicorn cv_agent.api.app:app --reload --port 8080

test:
	uv run pytest -q

lint:
	uv run ruff check --fix . && uv run ruff format .

typecheck:
	uv run mypy

validate-kb:
	uv run python scripts/validate_kb.py

kb:
	uv run python scripts/build_kb.py

eval:
	uv run python -m evals.run --seeds 3

smoke:
	./scripts/smoke.sh $(URL)

deploy:
	gcloud run deploy cv-agent --source . --region $$CLOUD_RUN_REGION
