PYTHON ?= python3

.PHONY: up down logs health events sim local-validation pre-hardware-validation hardware-simulation-validation backup-recovery-validation article-runtime-benchmark article-demo commit-plan test-local local-check docker-config backup-local restore-local test setup advisor install check publish-check publish-github publish-github-push publish-hf split-ml

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

local-validation:
	./scripts/run_local_validation.sh

pre-hardware-validation:
	./scripts/run_pre_hardware_validation.sh

hardware-simulation-validation:
	./scripts/run_hardware_simulation_validation.sh

backup-recovery-validation:
	./scripts/run_backup_recovery_validation.sh

article-runtime-benchmark:
	services/model-router/.venv/bin/python scripts/benchmark_article_runtime.py

article-demo:
	./scripts/run_article_demo.sh

commit-plan:
	$(PYTHON) scripts/publish/commit_plan.py

test-local:
	services/core/.venv/bin/python -m pytest services/core/tests services/dashboard/tests services/safety-checker/tests services/digital-twin/tests -q
	services/model-router/.venv/bin/python -m pytest services/model-router/tests -q
	services/automation-engine/.venv/bin/python -m pytest services/automation-engine/tests -q

local-check: test-local local-validation

docker-config:
	docker compose config >/dev/null
	@echo "Docker Compose configuration valid"

backup-local:
	./scripts/backup_sqlite.sh $(DB_PATH) $(BACKUP_PATH)

restore-local:
	./scripts/restore_sqlite.sh $(BACKUP_PATH) $(DB_PATH)

sim-pip: sim

test:
	services/core/.venv/bin/python -m pytest services/core/tests -v
	services/model-router/.venv/bin/python -m pytest services/model-router/tests -v

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
