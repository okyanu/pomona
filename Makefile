PYTHON ?= python3

.PHONY: up down logs health events sim test setup advisor install check publish-check publish-github publish-github-push publish-hf split-ml

up:
	./scripts/up.sh

down:
	./scripts/down.sh

install setup:
	./scripts/setup.sh

check:
	./scripts/check-prerequisites.sh

logs:
	docker compose logs -f core model-router

health:
	curl -s http://localhost:8080/health | python3 -m json.tool

events:
	curl -s "http://localhost:8080/v1/sensors/events?limit=5" | python3 -m json.tool

advisor-health:
	curl -s http://localhost:8081/health | python3 -m json.tool

advisor-models:
	curl -s http://localhost:8081/v1/models | python3 -m json.tool

advisor:
	curl -s http://localhost:8081/v1/advisor/explain \
		-H 'Content-Type: application/json' \
		-d @models/registry/examples/advisor-input.json | python3 -m json.tool

split-ml:
	chmod +x scripts/split/extract-ml-repo.sh && ./scripts/split/extract-ml-repo.sh

sim:
	./scripts/sim.sh

sim-pip: sim

test:
	cd services/core && PYTHONPATH=. $(PYTHON) -m pytest tests/ -v
	cd services/model-router && PYTHONPATH=. $(PYTHON) -m pytest tests/ -v

test-docker:
	docker compose run --rm --no-deps core python3 -m pip install pytest httpx -q && \
	docker compose run --rm --no-deps -e PYTHONPATH=/app core python3 -m pytest /app/tests/ -v || true

publish-check:
	chmod +x scripts/publish/*.sh && ./scripts/publish/check.sh

publish-github:
	chmod +x scripts/publish/*.sh && ./scripts/publish/github.sh

publish-github-push:
	chmod +x scripts/publish/*.sh && ./scripts/publish/github.sh push

publish-hf:
	chmod +x scripts/publish/*.sh && ./scripts/publish/huggingface.sh
