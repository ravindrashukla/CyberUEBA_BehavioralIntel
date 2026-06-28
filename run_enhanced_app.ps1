# Launch the ENHANCED dashboard against its OWN isolated Docker DB (port 5438).
# Streamlit does not read .env, so the DB target is set here explicitly.
# Usage:  ./run_enhanced_app.ps1        (from the enhanced folder)

Set-Location $PSScriptRoot

# 1. ensure the isolated DB container is up
docker compose -f docker-compose.enhanced.yml up -d db | Out-Null

# 2. point all host connections at the isolated DB (5438), not the baseline (5437)
$env:DATABASE_URL_HOST = 'postgresql://cyber_ueba:password@127.0.0.1:5438/cyber_ueba'
$env:DB_HOST = '127.0.0.1'
$env:DB_PORT = '5438'
$env:PYTHONIOENCODING = 'utf-8'

# 3. run the dashboard on 8502 (baseline uses its own port)
python -m streamlit run streamlit_app.py --server.port 8502 --server.headless true
