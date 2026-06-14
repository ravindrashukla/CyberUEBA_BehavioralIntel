# CLAUDE.md — Cyber UEBA Behavioral Intelligence

## Architecture

- **Docker:** PostgreSQL+pgvector (5433), FastAPI (8000), Background Worker
- **Embeddings:** ALL 1536-d (OpenAI text-embedding-3-small), unified space
- **Entity types:** User, Device, Network Segment, Application, Session
- **Detection:** Multi-front threat-profile detector (`threat_profile_detector.py`) — measurable known-bad behavioral profiles (cohort-relative + raw-event: C2-beacon, DGA, LOTL-process, cohort-rare access, recon-fanout, insider-collection) — catches 4/4 injected attacks at 0 false positives. Embedding/composite scoring cleanly separates only 2/4 (USR-156, USR-118); CUSUM/drift-direction are legacy comparison baselines.

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
