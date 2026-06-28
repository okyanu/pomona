# Plug and play — full stack vision

**Goal:** Clone repo → one command → entire Pomona mechanism running in Docker.

```bash
git clone https://github.com/Okyanus/pomona.git
cd pomona
cp .env.example .env
./scripts/up.sh
# open http://localhost:3000
```

No OS-specific setup. No manual database install. No separate Python venv for core services.

---

## Today (Phase 1) vs target (Phase 2+)

| Piece | Phase 1 (now) | Full plug & play (target) |
|-------|---------------|---------------------------|
| MQTT broker | ✅ Docker | ✅ Docker |
| Core API | ✅ Docker | ✅ Docker |
| Model router | ✅ Docker | ✅ Docker |
| **Database** | ❌ in-memory only | ✅ **SQLite or Postgres in Docker** |
| **Web dashboard** | ❌ none | ✅ **Dashboard container :3000** |
| Simulator | Host Python script | ✅ Optional container |
| One command | `./scripts/up.sh` | Same — more services inside |

**Phase 2 is what makes it feel like a complete product in Docker**, not just an API demo.

---

## Target Docker stack (one `docker compose up`)

```text
docker compose up -d
        │
        ├── mqtt          (Mosquitto :1883)
        ├── db            (SQLite volume or Postgres :5432)
        ├── core          (FastAPI :8080) ──→ db
        ├── model-router  (:8081)
        ├── dashboard     (Next/React :3000) ──→ core API
        └── simulator     (optional profile — fake sensors)
```

All services on one Docker network. Data persists in a named volume. Restarting containers does not wipe readings.

---

## Docker image strategy

| Approach | Best for |
|----------|----------|
| **docker-compose.yml** (current) | Development, contributors, plug-and-play clone ✅ **recommended** |
| Pre-built images on GHCR/Docker Hub | Users who skip `git clone` — `docker pull okyanus/pomona` later |
| Single “all-in-one” mega image | ❌ Avoid — hard to update, bad for open source |

**For open source:** keep **compose + Dockerfiles per service**. Publish images optionally for convenience:

```bash
# Future (optional)
docker compose -f docker-compose.yml -f docker-compose.release.yml up -d
```

Cloners build locally today (`--build`). Later you publish `:latest` images so pull is faster.

---

## What “whole mech” includes (v0.1 complete)

1. **Ingest** — MQTT + simulator (or ESP32 later)  
2. **Store** — database, not memory  
3. **See** — dashboard with pH, EC, temp, humidity  
4. **Think** — model-router + stub/HF advisor  
5. **Persist** — volumes survive `docker compose down`  

Phases 3–6 add reasoner, safety, automation — still inside the same compose file.

---

## Volumes (persistence)

```yaml
volumes:
  pomona_data:      # SQLite file or Postgres data
  mosquitto_data:   # optional MQTT persistence
```

User data stays on disk between restarts. Documented in `.env.example`.

---

## Optional profiles

```bash
./scripts/up.sh              # core stack: mqtt + db + core + router + dashboard
./scripts/up.sh --profile sim   # also run simulator in Docker
./scripts/up.sh --profile ollama  # optional local LLM
```

Simulator on host (today) vs in Docker (target) — both OK; Docker simulator = zero Python install for users.

---

## Not included in Docker (by design)

| Item | Where |
|------|--------|
| ML training | `pomona-agronomist-llm` repo |
| Model weights | Hugging Face |
| Your private notes | `private/` |
| GPU LLM inference | Host or separate GPU container (advanced) |

---

## Roadmap link

| Phase | Plug-and-play contribution |
|-------|----------------------------|
| 1 ✅ | API + MQTT in Docker |
| **2 ⏳** | **Database + dashboard in Docker** ← “whole mech” |
| 3 | Reasoner wired to dashboard |
| 4–6 | Safety + automation in stack |
| 7 | Hosted demo (same stack, cloud deploy) |

When Phase 2 ships, update [PHASES.md](./PHASES.md) and README “Project phases” table.

---

## Success check for contributors

After Phase 2, a new user should:

1. Install Docker Desktop only  
2. Clone + `./scripts/up.sh`  
3. Open **http://localhost:3000** and see live (simulated) greenhouse data  
4. Run `docker compose down` and `up` again — **data still there**

That is the plug-and-play bar.
