# CLAUDE.md — Cyber UEBA Behavioral Intelligence

## Architecture

- **Docker:** PostgreSQL+pgvector (5433), FastAPI (8000), Background Worker
- **Embeddings:** ALL 1536-d (OpenAI text-embedding-3-small), unified space
- **Entity types:** User, Device, Network Segment, Application, Session
- **Detection:** CUSUM change-point + drift direction + MITRE ATT&CK mapping

## Development

```bash
# Generate synthetic data (16 months, ~30K events/day)
python -m simulator.generate --days 7  # quick test
python -m simulator.generate            # full 486 days

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
5. MockEmbedder for dev/testing without OpenAI API key

## Docker-First

- Never hardcode `localhost` for DB — use `DATABASE_URL` env var
- DB host in Docker is `db`, externally is `localhost:5433`
- Code changes are live via volume mount; dependency changes need `--build`
