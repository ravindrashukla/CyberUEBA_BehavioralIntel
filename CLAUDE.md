# CLAUDE.md — Cyber UEBA Behavioral Intelligence

## Architecture

- **Docker:** base stack PostgreSQL+pgvector (5433)/FastAPI (8000); **the Streamlit app runs against the _enhanced_ stack** (`docker-compose.enhanced.yml`: db **5438**, api **8003**, worker).
- **Embeddings:** ALL 1536-d (OpenAI text-embedding-3-small), unified space
- **Entity types:** User, Device, Network Segment, Application, Session
- **Detection:** Multi-front threat-profile detector (`threat_profile_detector.py`) — measurable known-bad behavioral profiles (cohort-relative + raw-event: C2-beacon, DGA, LOTL-process, cohort-rare access, recon-fanout, insider-collection) — catches 4/4 injected attacks at 0 false positives. Embedding/composite scoring cleanly separates only 2/4 (USR-156, USR-118); CUSUM/drift-direction are legacy comparison baselines.

## Streamlit App (UI)

- **Full enhancement reference: [docs/APP_REFERENCE.md](docs/APP_REFERENCE.md)** — run/stop, data loaders, all 16 pages, chart formulas, artifacts, lessons. Read it before changing the app.
- **Run** (bare `streamlit` is NOT on PATH — use `python -m`):
  ```bash
  docker-compose -f docker-compose.enhanced.yml up -d
  DATABASE_URL_HOST='postgresql://cyber_ueba:password@127.0.0.1:5438/cyber_ueba' DB_HOST='127.0.0.1' DB_PORT='5438' \
  python -m streamlit run streamlit_app.py --server.port 8502 --server.headless true   # → http://localhost:8502/
  ```
- **Nav:** 16 pages grouped into 5 sections via `NAV_GROUPS` (selectbox "Section" → radio of pages). Page names unchanged, so `if/elif page == "<name>":` blocks are intact. Find a page's code: search `elif page == "<name>":`.
- **Dataset:** 250 users · 70 weeks · 485 days · 17,500 weekly rows (246 normal + 4 attackers: USR-118 Salt Typhoon #1/51.7, USR-156 insider #2/46.2, USR-234 slow-APT #7/20.0, USR-042 Volt-Typhoon-LOTL #30/12.9). Never "19 weeks / 4,750". (Composite scores updated 2026-06-28 after the attacker-department fix re-embed.)
- **Canonical detection story — keep EVERY page consistent:** traditional 0/4 → z-score 1/4 (noisy) → composite 4/4 (cleanly separates only 2/4) at **10.6% FP** → threat-profile **4/4 at 0 FP**.
- **FP convention = "catch-all-four":** threshold = lowest attacker composite `cs[cs.is_attack]["composite"].min()` (=12.95) → 26/246 = **10.6%** (as of 2026-06-28). **NEVER hardcode this number** — the app computes it live (`FP_ALL4_TXT` in `streamlit_app.py`); docs cite the current value. Do NOT use `composite.quantile(0.90)` for a "catch all 4" claim — use the lowest-attacker-composite threshold.
- **USR-234 acid test:** the slow APT escapes BOTH drift lenses (feature + embedding CUSUM); only the known-bad profile + novelty persistence catch it. Any "drift catches all 4" claim is wrong.

## Development

```bash
# Generate synthetic data (70 weeks / 485 days)
python -m simulator.generate --days 7    # quick test
python -m simulator.generate --days 485  # full dataset

# Run API
docker-compose up -d --build

# Load data into DB
docker exec cyber-ueba-api python -m db.seed
```

## Key Design Decisions

1. Text serialization → embedding: raw metrics become prose before embedding
2. 5 signals per entity composed via weighted average (NOT concatenation)
3. CUSUM catches slow drift that individual thresholds miss
4. Reference concepts as text embeddings for drift direction interpretation
5. Real OpenAI embeddings are mandatory — every pipeline hard-fails without `OPENAI_API_KEY` (mock embeddings were removed from the codebase; the test suite skips embedding tests when no key is present)

## Docker-First

- Never hardcode `localhost` for DB — use `DATABASE_URL` env var
- DB host in Docker is `db`, externally is `localhost:5433`
- Code changes are live via volume mount; dependency changes need `--build`
