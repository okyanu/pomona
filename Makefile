PYTHON ?= python3

.PHONY: up down logs health events sim fake-greenhouse fake-greenhouse-dry fool-space-check fool-space-build fool-space-venv fake-greenhouse-score local-validation pre-hardware-validation hardware-simulation-validation backup-recovery-validation article-runtime-benchmark article-demo commit-plan test-local local-check docker-config backup-local restore-local test setup advisor install check publish-check publish-github publish-github-push publish-hf split-ml

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

# SCENARIO=path/to/scenario.json runs another scenario (for example one downloaded from the "Try to fool Pomona" Space).
SCENARIO ?= examples/simulators/scenarios/demo.json
fake-greenhouse:
	$(PYTHON) -m pip install -q -r examples/simulators/requirements.txt 2>/dev/null || true
	@echo "Control page: http://127.0.0.1:8090/"
	MQTT_HOST=$${MQTT_HOST:-localhost} MQTT_PORT=$${MQTT_PORT:-1883} $(PYTHON) examples/simulators/fake_greenhouse.py --scenario $(SCENARIO) --control-port 8090

# No MQTT: events go to data/fake_greenhouse/events.jsonl, the control page runs in real time.
fake-greenhouse-dry:
	@mkdir -p data/fake_greenhouse
	@echo "Control page: http://127.0.0.1:8090/"
	$(PYTHON) examples/simulators/fake_greenhouse.py --dry-run --out data/fake_greenhouse/events.jsonl --control-port 8090

# Real-time run against a no-Docker stack, then the scorer. SCENARIO=... INTERVAL=30 CONTROL_PORT=8090 (optional).
fake-greenhouse-score:
	./scripts/run_fake_greenhouse_score.sh

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
	services/model-router/.venv/bin/python -m pytest scripts/datasets/tests -q
	services/core/.venv/bin/python -m pytest services/core/tests services/dashboard/tests services/safety-checker/tests services/digital-twin/tests -q
	services/core/.venv/bin/python -m pytest examples/simulators/tests -q
	services/model-router/.venv/bin/python -m pytest scripts/tests -q
	services/model-router/.venv/bin/python -m pytest services/model-router/tests -q
	services/automation-engine/.venv/bin/python -m pytest services/automation-engine/tests -q

# "Try to fool Pomona" Space (spaces/try-to-fool-pomona): the Space's own Python 3.11 venv, the vendored engine files
# (copied from the repo, generated, not committed) and its tests. No network is used by the tests.
FOOL_SPACE := spaces/try-to-fool-pomona
FOOL_PY := $(FOOL_SPACE)/.venv/bin/python
PYTHON311 ?= python3.11

$(FOOL_PY):
	$(PYTHON311) -m venv $(FOOL_SPACE)/.venv
	$(FOOL_SPACE)/.venv/bin/pip install -q -r $(FOOL_SPACE)/requirements-dev.txt

fool-space-venv: $(FOOL_PY)

fool-space-build:
	./scripts/build_fool_space.sh

# Rebuild vendor/, verify every vendored file against the repo (hashes), run the Space tests. Part of publish-check.
fool-space-check: $(FOOL_PY)
	./scripts/build_fool_space.sh
	./scripts/build_fool_space.sh --check
	$(FOOL_PY) -m pytest $(FOOL_SPACE)/tests -q

.PHONY: print-pack
# 3D-printable station and sensor mounts: render STL/3MF and run geometry checks (needs OpenSCAD).
print-pack:
	hardware/a1mini-sensor-station/build.sh

.PHONY: test-checker
# Sensor Data Checker Space: JS rules must match the Python rules (needs python3.11 + node).
test-checker:
	python3.11 spaces/sensor-data-checker/tests/make_parity_cases.py
	node spaces/sensor-data-checker/tests/parity.test.mjs
	node spaces/sensor-data-checker/tests/checker.test.mjs

.PHONY: test-demo
# Greenhouse demo Space: the page's own JavaScript (tomato rules, and the sensor check -> veto -> tomato chain)
# must match the Python rules; its rules.js must be an exact copy of the Sensor Data Checker's.
test-demo:
	services/model-router/.venv/bin/python spaces/pomona-greenhouse-demo/tests/make_parity_cases.py
	node spaces/pomona-greenhouse-demo/tests/parity.test.cjs

.PHONY: test-ph-checker
# pH Calibration Checker Space: the page's JavaScript must match the Python calibrator and Core's probe health.
test-ph-checker:
	python3 spaces/ph-calibration-checker/tests/make_parity_cases.py
	node spaces/ph-calibration-checker/tests/parity.test.cjs

.PHONY: demo-local
.PHONY: fault-replay
fault-replay:
	services/model-router/.venv/bin/python scripts/benchmark_sensor_fault_replay.py

.PHONY: real-replay
# Real third-party sensor logs (local raw files, see datasets/sources/); skips missing datasets.
real-replay:
	services/model-router/.venv/bin/python scripts/benchmark_real_sensor_replay.py

demo-local:
	services/model-router/.venv/bin/python scripts/demo_local.py

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
	docker compose run --rm --no-deps -e PYTHONPATH=/app core python3 -m pytest /app/tests/ -v

publish-check:
	chmod +x scripts/publish/*.sh && ./scripts/publish/check.sh

publish-github:
	chmod +x scripts/publish/*.sh && ./scripts/publish/github.sh

publish-github-push:
	chmod +x scripts/publish/*.sh && ./scripts/publish/github.sh push

publish-hf:
	chmod +x scripts/publish/*.sh && ./scripts/publish/huggingface.sh
