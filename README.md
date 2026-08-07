# ⚡ GridVision

An end-to-end MLOps system that forecasts US electricity demand: it pulls live
grid + weather data daily, retrains a LightGBM quantile model, gates any new
candidate against both the current production model and a naive baseline
before promoting it, and serves the result to a 3D geospatial dashboard.

**Live:**
- Dashboard: https://jeffreyblay.github.io/energy_demand_mlops/
- API: https://gridvision-api.onrender.com/health

*(Render's free tier sleeps after inactivity — the API may take ~30–60s to wake up on first request.)*

---

## How it works

```mermaid
flowchart TB
    subgraph EXT["External APIs"]
        EIA[["EIA API v2<br/>hourly demand"]]
        OM[["Open-Meteo<br/>archive + forecast temp"]]
    end

    subgraph GHA["GitHub Actions — cron 0 6 * * * UTC (retrain.yml)"]
        direction TB
        S1["1. fetch_demand + fetch_weather<br/>(parallel)"]
        S2["2. build_features<br/>(~2yr rolling feature store)"]
        S3["3. train<br/>candidate LightGBM P10/P50/P90"]
        S4["4. backtest + gate<br/>candidate vs production vs baseline"]
        S5{"beats production<br/>AND baseline?"}
        S6["5a. promote:<br/>copy candidate → production"]
        S7["5b. reject:<br/>keep existing production"]
        S8["6. generate_forecast<br/>next 24h, every region"]
        S1 --> S2 --> S3 --> S4 --> S5
        S5 -->|yes| S6 --> S8
        S5 -->|no| S7 --> S8
    end

    subgraph REPO["GitHub repo (git = model registry)"]
        MS[("models/production/<br/>model.joblib + metadata.json")]
    end

    subgraph SUPA["Supabase Postgres + PostGIS"]
        DB[("feature store · forecast ·<br/>region_summary · promotion_log")]
    end

    subgraph RENDER["Render — FastAPI (read-only)"]
        API["/regions /regions/coverage<br/>/regions/nearby /forecast<br/>/history /health"]
    end

    subgraph PAGES["GitHub Pages — dashboard"]
        WEB["React + MapLibre + deck.gl<br/>3D demand map, coverage toggle,<br/>nearby grids, promotion timeline"]
    end

    USER(["👤 Browser"])

    EIA -->|"HTTP"| S1
    OM -->|"HTTP"| S1
    S6 -->|"git commit + push"| MS
    S4 -->|"read current production"| MS
    S8 -->|"read production model"| MS
    S1 -.->|"features"| DB
    S8 -->|"write forecast +<br/>region_summary"| DB
    S6 -->|"write promotion_log"| DB
    S7 -->|"write promotion_log"| DB
    API -->|"SELECT (read-only)"| DB
    WEB -->|"HTTPS GET"| API
    USER -->|"loads"| WEB
```

No always-on server runs the pipeline — **GitHub Actions' cron trigger is the
scheduler**, standing in for what would otherwise be an Airflow instance that
has to stay up 24/7. Since each Actions run starts from a clean, ephemeral
checkout with no memory of yesterday's state, the "model registry" is the
**git repo itself**: a promoted model's weights and metadata are committed
straight into `models/production/`, so next run's checkout already has it.

Full diagram set (use case, activity, component, class, sequence, state
machine, deployment) lives in [`diagram/uml.md`](diagram/uml.md).

---

## Why these choices

- **LightGBM, not a neural net** — demand forecasting here is tabular
  regression with strong lagged/calendar features; gradient boosting wins on
  data of this size and shape, trains in seconds (matters for daily
  retraining), and supports quantile loss natively for the P10/P50/P90
  intervals the dashboard needs.
- **Double promotion gate** — a candidate is only promoted if it beats *both*
  the current production model *and* a seasonal-naive baseline
  (`demand_lag_168h`) on the same rolling 7-day holdout. Beating a bad
  production model isn't enough; it also has to beat a real benchmark. Pure,
  deterministic, unit-tested in isolation (`tests/test_promote.py`).
- **Git as the model registry** — no MLflow server to keep alive between
  ephemeral CI runs. The production model is a small file, versioned and
  audit-tracked by git history like everything else in the repo.
- **PostGIS for spatial queries** — grid coverage buffers (`/regions/coverage`)
  and "which grids are nearby" (`/regions/nearby`) are one `ST_Buffer` /
  `ST_DWithin` query each, not client-side geometry math.
- **FastAPI never recomputes** — it only reads what the pipeline already
  wrote to Postgres. Forecasting is scheduled and batch; serving is cheap and
  fast.

---

## Stack

| Layer | Tech |
|---|---|
| Orchestration (live) | GitHub Actions (cron) |
| Orchestration (local dev) | Apache Airflow via Docker Compose |
| Model | LightGBM, quantile regression (P10/P50/P90) |
| Model registry | Git-committed (`models/production/`) — MLflow used locally only |
| Database | Postgres + PostGIS (Supabase, hosted; local Docker for dev) |
| API | FastAPI, read-only |
| Dashboard | React + TypeScript, MapLibre GL JS + deck.gl |
| Hosting | Render (API) + GitHub Pages (dashboard) |
| Data sources | EIA API v2 (demand), Open-Meteo (weather, no key needed) |

9 US balancing authorities: ERCOT, MISO, PJM, NYISO, ISO-NE, SWPP (Southwest
Power Pool), CAISO, PacifiCorp West, PacifiCorp East.

---

## Local development

Full stack, mirrors what runs in CI/production but with local infra:

```bash
docker compose up -d              # Airflow, MLflow, local Postgres
conda activate gridMlops
uvicorn api.main:app --reload --port 8000

cd dashboard
npm install
npm run dev
```

- Airflow UI: http://localhost:8080
- MLflow UI: http://localhost:5000
- API: http://localhost:8000
- Dashboard: http://localhost:5173

Run the pipeline standalone (no Airflow) the same way GitHub Actions does:

```bash
python scripts/run_pipeline.py
```

Requires `EIA_API_KEY` and `POSTGRES_DSN` in `.env` (see `.env.example`).

---

## Repo map

```
src/                  pipeline modules (fetch, features, train, gate, forecast, model store)
scripts/run_pipeline.py   GitHub Actions entrypoint (sequential, no Airflow)
dags/                 Airflow DAG — local dev only, same logic as scripts/run_pipeline.py
api/                  FastAPI serving layer
dashboard/            React + MapLibre + deck.gl frontend
diagram/uml.md         full UML diagram set
.github/workflows/    retrain.yml (daily cron) + deploy-dashboard.yml
tests/                unit tests (promotion gate logic)
```
