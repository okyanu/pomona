PYTHON ?= python3

.PHONY: up down install setup check logs health events advisor-health advisor-models advisor split-ml sim \
	fake-greenhouse fake-greenhouse-dry fake-greenhouse-score local-validation pre-hardware-validation \
	hardware-simulation-validation backup-recovery-validation article-runtime-benchmark article-demo commit-plan \
	bootstrap lock check-venvs test test-local local-check fool-space-venv fool-space-build fool-space-check \
	fool-space-pyodide-check print-pack test-checker test-demo test-ph-checker demo-local fault-replay real-replay \
	docker-config backup restore backup-local restore-local sim-pip publish-check publish-github publish-github-push \
	publish-hf

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
	. ./scripts/mqtt-env.sh && load_mqtt_credentials .env && MQTT_HOST=$${MQTT_HOST:-localhost} MQTT_PORT=$${MQTT_PORT:-1883} $(PYTHON) examples/simulators/fake_greenhouse.py --scenario $(SCENARIO) --control-port 8090

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

# Python 3.11 venvs for the test suites (what CONTRIBUTING.md lists), installed with the pins in constraints-dev.txt.
# A venv path that already exists is left alone (delete it to rebuild).
define make_venv
	@if [ -e services/$(1)/.venv ]; then echo "services/$(1)/.venv already exists: skipped"; else \
		echo "Creating services/$(1)/.venv"; \
		$(PYTHON311) -m venv services/$(1)/.venv && \
		services/$(1)/.venv/bin/pip install -q $(2) -c constraints-dev.txt pytest httpx pyyaml \
		|| { rm -rf services/$(1)/.venv; echo "Could not create services/$(1)/.venv" >&2; exit 1; }; \
	fi
endef

bootstrap:
	$(call make_venv,core,-r services/core/requirements.txt -r services/dashboard/requirements.txt -r services/safety-checker/requirements.txt -r services/digital-twin/requirements.txt -r examples/simulators/requirements.txt)
	$(call make_venv,model-router,-r services/model-router/requirements.txt)
	$(call make_venv,automation-engine,-r services/automation-engine/requirements.txt)

check-venvs:
	@missing=0; for v in core model-router automation-engine; do \
		[ -x services/$$v/.venv/bin/python ] || { echo "Missing services/$$v/.venv" >&2; missing=1; }; \
	done; \
	[ $$missing = 0 ] || { echo "Run 'make bootstrap' first." >&2; exit 1; }; \
	for v in core model-router automation-engine; do \
		services/$$v/.venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || { \
			echo "WARNING: services/$$v/.venv runs Python $$(services/$$v/.venv/bin/python -c 'import platform; print(platform.python_version())'), older than 3.11. The tests are running on an older Python than Docker and CI (3.11). Rebuild it: rm -rf services/$$v/.venv && make bootstrap" >&2; }; \
	done

# Regenerate the exact pins (constraints.txt per service, constraints-dev.txt for the test venvs) from the
# requirements.txt files, for Python 3.11 on Linux (what the containers run). Needs uv (pip install uv).
# Existing pins are kept unless a requirement changed; `make lock UPGRADE=1` moves everything to the newest versions.
LOCK_FLAGS := --python-version 3.11 --python-platform linux $(if $(UPGRADE),--upgrade)
lock:
	@command -v uv >/dev/null || { echo "uv not found: pip install uv" >&2; exit 1; }
	@set -e; for s in core dashboard digital-twin safety-checker model-router automation-engine; do \
		uv pip compile services/$$s/requirements.txt $(LOCK_FLAGS) -o services/$$s/constraints.txt; \
	done
	uv pip compile requirements-dev.txt $(LOCK_FLAGS) -o constraints-dev.txt

# One virtual environment per service group, created by `make bootstrap`; `make test` is the same full suite.
test-local: check-venvs
	services/model-router/.venv/bin/python -m pytest scripts/datasets/tests -q
	services/core/.venv/bin/python -m pytest services/core/tests services/dashboard/tests services/safety-checker/tests services/digital-twin/tests -q
	services/core/.venv/bin/python -m pytest examples/simulators/tests -q
	services/model-router/.venv/bin/python -m pytest scripts/tests -q
	services/model-router/.venv/bin/python -m pytest services/model-router/tests -q
	services/automation-engine/.venv/bin/python -m pytest services/automation-engine/tests -q

# "Try to fool Pomona" Space (spaces/try-to-fool-pomona): a static Space. Its Python (game.py, engine_api.py and the
# vendored engine files) runs in the visitor's browser with Pyodide; here the same code is tested in CPython with the
# Space's own Python 3.11 venv (pydantic, pydantic-settings, httpx, pytest), and in Pyodide under Node.
# The Space folder is generated by scripts/build_fool_space.sh (vendor/, pyodide/, wheels/, pomona.zip; gitignored).
FOOL_SPACE := spaces/try-to-fool-pomona
FOOL_PY := $(FOOL_SPACE)/.venv/bin/python
PYTHON311 ?= python3.11

$(FOOL_PY): $(FOOL_SPACE)/tests/requirements.txt
	$(PYTHON311) -m venv $(FOOL_SPACE)/.venv
	$(FOOL_SPACE)/.venv/bin/pip install -q -r $(FOOL_SPACE)/tests/requirements.txt
	@touch $(FOOL_PY)

fool-space-venv: $(FOOL_PY)

# Build the Space folder (downloads the pinned Pyodide files the first time; to look at it: python3 -m http.server 8767
# --directory spaces/try-to-fool-pomona).
fool-space-build:
	./scripts/build_fool_space.sh

# Rebuild the Space folder, verify every vendored and pinned file (hashes) and pomona.zip, run the Space tests (CPython).
# Part of publish-check. The Space tests need no network.
fool-space-check: $(FOOL_PY)
	./scripts/build_fool_space.sh
	./scripts/build_fool_space.sh --check
	$(FOOL_PY) -m pytest $(FOOL_SPACE)/tests -q

# The engine in Pyodide (the page's own start-up, boot.js, on the self-hosted files, with eval disabled) must give
# byte-identical results to CPython on scenarios a, b, c (+ the worker's rebuild path). Needs node; `npm ci` fetches the
# pinned pyodide package the first time.
fool-space-pyodide-check: $(FOOL_PY)
	./scripts/build_fool_space.sh
	FOOL_PY=$(CURDIR)/$(FOOL_PY) $(FOOL_SPACE)/tests/pyodide_check.sh

# 3D-printable station and sensor mounts: render STL/3MF and run geometry checks (needs OpenSCAD).
print-pack:
	hardware/a1mini-sensor-station/build.sh

# Sensor Data Checker Space: JS rules (rules.js) and persistent checks (persistent.js: Core's trusted stream reference and
# apply_persistent_checks) must match the Python code (needs python3.11 + node).
test-checker:
	python3.11 spaces/sensor-data-checker/tests/make_parity_cases.py
	node spaces/sensor-data-checker/tests/parity.test.mjs
	python3.11 spaces/sensor-data-checker/tests/make_persistent_cases.py
	node spaces/sensor-data-checker/tests/persistent.test.mjs
	node spaces/sensor-data-checker/tests/checker.test.mjs

# Greenhouse demo Space: the page's own JavaScript (tomato rules, and the sensor check -> veto -> tomato chain)
# must match the Python rules; its rules.js must be an exact copy of the Sensor Data Checker's.
test-demo:
	services/model-router/.venv/bin/python spaces/pomona-greenhouse-demo/tests/make_parity_cases.py
	node spaces/pomona-greenhouse-demo/tests/parity.test.cjs

# pH Calibration Checker Space: the page's JavaScript must match the Python calibrator and Core's probe health.
test-ph-checker:
	python3 spaces/ph-calibration-checker/tests/make_parity_cases.py
	node spaces/ph-calibration-checker/tests/parity.test.cjs

fault-replay:
	services/model-router/.venv/bin/python scripts/benchmark_sensor_fault_replay.py

# Real third-party sensor logs (local raw files, see datasets/sources/); skips missing datasets.
real-replay:
	services/model-router/.venv/bin/python scripts/benchmark_real_sensor_replay.py

demo-local:
	services/model-router/.venv/bin/python scripts/demo_local.py

local-check: test-local local-validation

docker-config:
	docker compose config >/dev/null
	@echo "Docker Compose configuration valid"

# Docker stack: both databases and the audit log into backups/<timestamp>/ (see docs/INSTALL.md).
backup:
	./scripts/backup.sh

restore:
	./scripts/restore.sh $(BACKUP)

backup-local:
	./scripts/backup_sqlite.sh $(DB_PATH) $(BACKUP_PATH)

restore-local:
	./scripts/restore_sqlite.sh $(BACKUP_PATH) $(DB_PATH)

sim-pip: sim

test: test-local

publish-check:
	chmod +x scripts/publish/*.sh && ./scripts/publish/check.sh

publish-github:
	chmod +x scripts/publish/*.sh && ./scripts/publish/github.sh

publish-github-push:
	chmod +x scripts/publish/*.sh && ./scripts/publish/github.sh push

publish-hf:
	chmod +x scripts/publish/*.sh && ./scripts/publish/huggingface.sh
