# ⚡ GridVision — Intelligent Energy Demand Forecasting with MLOps

> An end-to-end MLOps system that ingests live US grid data, retrains a LightGBM demand forecasting model daily, gates promotion against a performance threshold, and serves forecasts to a 3D interactive geospatial dashboard built with MapLibre GL JS.

---

## What this project is

GridVision mirrors what real grid operators (ISOs/RTOs and utilities) do operationally: forecast next-day and next-hour electricity demand across US balancing authorities so generation can be scheduled efficiently. Stale models quietly degrade as weather patterns and consumption behavior shift — this pipeline catches that degradation automatically and retrains without manual intervention.

It is a portfolio-grade demonstration of four distinct engineering disciplines working together:
- **Data engineering** — multi-source ingestion, rolling feature store, scheduled ETL via Airflow
- **MLOps** — automated retraining, experiment tracking, evaluation gating, model registry promotion
- **Backend engineering** — FastAPI serving layer always pointing at the live production model
- **Frontend / geospatial** — 3D MapLibre GL JS dashboard with extruded demand blocks per grid region, isometric analytics panels, and a live promotion timeline

---

## Data sources

| Source | What it provides | Access |
|---|---|---|
| EIA API v2 (`electricity/rto/region-data`) | Hourly electricity demand by US balancing authority | Free, API key required (sign up at eia.gov) |
| Open-Meteo | Hourly temperature and weather per region | Free, no key required |
| Calendar features | Day-of-week, hour-of-day, US federal holiday flags | Generated locally |

Ten US grid regions are covered out of the box: ERCOT, MISO, PJM, NYISO, ISO-NE, SPP, CAISO, Southwest Power Pool, PacifiCorp West, PacifiCorp East.

---

## Model choice — LightGBM

LightGBM (gradient boosted trees) is the correct model for this problem, not a deep learning approach:

- Demand forecasting at this granularity is a **tabular regression problem** with strong lagged and calendar features — gradient boosting consistently outperforms neural nets on structured tabular data of this size
- **Fast to retrain daily** (seconds to low minutes), which matters since the whole point is high-frequency automated retraining
- Handles the **temperature-demand non-linearity** (heating and cooling load curves) naturally via tree splits without manual feature engineering
- Supports **quantile loss** natively, producing P10/P90 prediction intervals alongside the point forecast — a requirement for any realistic operational dashboard

A Prophet or SARIMA model is kept as a **naive baseline** that every candidate LightGBM model must beat in the evaluation gate before promotion. This is a standard MLOps pattern that distinguishes the project from a simple "I trained a model" portfolio piece.

**Core feature set**

| Feature | Description |
|---|---|
| `demand_lag_24h` | Actual demand from 24 hours prior — single strongest predictor |
| `demand_lag_168h` | Demand from same hour last week — captures weekly seasonality |
| `temperature` | Hourly dry-bulb temperature for the region |
| `hour_of_day` | 0–23 integer |
| `day_of_week` | 0–6 integer |
| `is_holiday` | US federal holiday flag |
| `demand_rolling_7d` | 7-day rolling mean demand — trend signal |

---

## Architecture

```
EIA API ──────────────────────────────────────────────────────────────────┐
Open-Meteo ───────────────────────────────────────────────────────────────┤
                                                                          ▼
                                                               Airflow DAG (daily)
                                                                          │
                                        ┌─────────────────────────────────┤
                                        ▼                                 ▼
                               Feature store                     Promotion log
                             (Postgres + Parquet)                 (Postgres)
                                        │
                          ┌─────────────┴──────────────┐
                          ▼                            ▼
                  LightGBM candidate            MLflow registry
                    training + eval          (production model tag)
                          │
                  Evaluation gate
                 (beat production +
                  beat naive baseline)
                          │
               ┌──────────┴──────────┐
               ▼                     ▼
          Promote to          Log rejection
          production
               │
               ▼
      FastAPI /forecast
      /regions /history
               │
               ▼
    React dashboard + MapLibre 3D map
```

---

## Repo structure

```
gridvision/
├── dags/
│   └── demand_retrain_dag.py          # Main Airflow DAG
│
├── src/
│   ├── fetch_demand.py                # EIA API ingestion
│   ├── fetch_weather.py               # Open-Meteo ingestion
│   ├── build_features.py              # Feature engineering + lag construction
│   ├── validate_data.py               # Schema + null checks (Great Expectations)
│   ├── train.py                       # LightGBM training with MLflow logging
│   ├── backtest.py                    # Walk-forward validation, MAPE/RMSE
│   ├── promote.py                     # Evaluation gate: promote or reject
│   └── forecast.py                    # Generate next 24–48h forecast + intervals
│
├── data/
│   └── rolling_window/                # Parquet files, ~2yr rolling window
│
├── mlflow/
│   └── docker-compose.yml             # MLflow tracking server
│
├── serving/
│   ├── app.py                         # FastAPI app
│   └── routes/
│       ├── forecast.py                # GET /forecast?region=ERCOT
│       ├── regions.py                 # GET /regions — all region summaries
│       └── history.py                 # GET /history — promotion log
│
├── dashboard/
│   ├── src/
│   │   ├── components/
│   │   │   ├── Map3D.jsx              # MapLibre GL JS 3D extrusion map
│   │   │   ├── DemandChart.jsx        # Isometric hourly demand bars
│   │   │   ├── AccuracyChart.jsx      # Rolling MAPE trend
│   │   │   ├── PromotionTimeline.jsx  # Model promotion history
│   │   │   └── StatCards.jsx          # Peak forecast, MAPE, reserve margin
│   │   └── App.jsx
│   └── package.json
│
├── tests/
│   ├── test_features.py
│   ├── test_backtest.py
│   └── test_promote.py
│
├── docker-compose.yml                 # Spins up all services
└── README.md
```

---

## Airflow DAG: `demand_retrain_dag`

**Schedule**: `0 6 * * *` — runs at 6am daily after the prior day's EIA data is finalized.

**DAG task flow**

```
fetch_demand_data ──┐
                    ├──▶ build_features ──▶ append_to_store ──▶ retrain_model
fetch_weather_data ─┘                                                  │
                                                                       ▼
                                                           backtest_candidate
                                                                       │
                                                           branch_on_performance
                                                            │                  │
                                                     (beats gate)        (does not beat)
                                                            │                  │
                                                     promote_model       log_rejection
                                                            │
                                                    generate_forecast
                                                            │
                                                   write_dashboard_data
                                                            │
                                                          notify
```

**Task reference**

| Task | Operator | Description |
|---|---|---|
| `fetch_demand_data` | `PythonOperator` | Pull yesterday's hourly demand for all 10 regions from EIA API |
| `fetch_weather_data` | `PythonOperator` | Pull matching hourly temperature from Open-Meteo |
| `build_features` | `PythonOperator` | Join demand + weather, compute lags, calendar flags, rolling stats |
| `append_to_store` | `PythonOperator` | Append to rolling window Parquet store (keep ~2 years) |
| `retrain_model` | `PythonOperator` | Train candidate LightGBM, log all params + metrics to MLflow |
| `backtest_candidate` | `PythonOperator` | Walk-forward backtest on most recent 7 days vs production model vs naive baseline |
| `branch_on_performance` | `BranchPythonOperator` | Promote if candidate MAPE beats both production and baseline; else reject |
| `promote_model` | `PythonOperator` | Register new version in MLflow registry, tag as `production`, archive prior version |
| `log_rejection` | `PythonOperator` | Write rejection record to DB — rejection is informative signal, not a failure |
| `generate_forecast` | `PythonOperator` | Production model generates next 24–48h forecast with P10/P90 quantile intervals |
| `write_dashboard_data` | `PythonOperator` | Write forecast + region summaries + MAPE history to Postgres for the API to serve |
| `notify` | `PythonOperator` | Slack/email summary: MAPE, promoted or not, any validation failures, peak forecast |

> **Branching gate detail**: `branch_on_performance` compares candidate MAPE against both the current production model and the naive baseline on an identical 7-day held-out window. The candidate must beat both to be promoted. This double gate ensures the model is improving against a meaningful benchmark, not just outperforming a previous bad model.

---

## FastAPI endpoints

| Endpoint | Response |
|---|---|
| `GET /forecast?region=ERCOT` | Next 24–48h hourly forecast with P10/P90 intervals |
| `GET /regions` | All region summaries: demand, delta vs yesterday, temperature, model version |
| `GET /history?region=ERCOT` | Promotion/rejection log with dates and MAPE scores |
| `GET /health` | Service health + active model version |

The API always reads the latest pre-computed forecast from Postgres — it never recomputes on request. The DAG writes it; the API serves it.

---

## Dashboard

Built with React + MapLibre GL JS. All panels use an isometric 3D visual language.

**Map panel (MapLibre GL JS)**
- Dark CartoDB basemap
- Each US grid region rendered as a `fill-extrusion` block
- Block height proportional to forecast demand in GW
- Color mapped to intensity: teal (< 30 GW) → purple (30–50 GW) → coral/red (> 50 GW)
- Hover tooltip: region name, forecast GW, delta vs yesterday, temperature
- Fully interactive: drag to orbit, scroll to zoom, right-click to rotate bearing
- GeoJSON fed from `GET /regions` — refreshes every 15 minutes

**Analytics panels**
- Isometric hourly demand bar chart — 3D extruded blocks, peak block highlighted in coral
- Rolling MAPE accuracy chart — teal blocks for improving periods, red for degradation
- Stat cards — peak forecast GW, accuracy %, reserve margin, weekly retrain count
- Model promotion timeline — vertical dot timeline with promote/reject/drift events

---

## Execution steps

Work through these in order. Do not jump to Airflow until step 3 is solid.

**Step 1 — Manual prototype**
Manually run `fetch_demand.py` → `fetch_weather.py` → `build_features.py` → `train.py` → `backtest.py` for a few days of real EIA data. Confirm the model trains, features look correct, and MAPE numbers are in a reasonable range (3–6% is typical for this problem) before touching any orchestration.

**Step 2 — MLflow tracking**
Wrap `train.py` so every run logs hyperparameters, MAPE, RMSE, and the model artifact to MLflow. Verify you can pull the `production`-tagged model artifact back out programmatically using the MLflow client. This needs to work cleanly before the Airflow gate can use it.

**Step 3 — Evaluation gate in isolation**
Write and test `promote.py` as a standalone function independent of Airflow. Given two MAPE scores and a threshold, it should return `promote` or `reject` deterministically. Unit test this with `pytest` — it is the most critical logic in the pipeline.

**Step 4 — Wire into Airflow**
Convert each script into an Airflow task using the TaskFlow API (`@task` decorator). Use Airflow Variables for the EIA API key and Connections for the Postgres DSN — no secrets hardcoded. Run the full DAG manually first with `airflow dags test demand_retrain_dag <date>` before enabling the schedule.

**Step 5 — FastAPI serving**
Stand up the API with the three endpoints above. The `/forecast` endpoint loads the latest stored forecast from Postgres, not from MLflow on demand. Test that when you re-tag a model in MLflow, the next forecast written by the DAG reflects it.

**Step 6 — Dashboard**
Build the React app, start with the stat cards and the MAPE chart, then add the MapLibre 3D map last since it has the most moving parts (GeoJSON generation, extrusion height scaling, tooltip state). Connect to `GET /regions` and `GET /forecast`.

**Step 7 — Run it live for at least 2 weeks**
Do not call the project done after one successful DAG run. You need at least one real promotion, one real rejection, and ideally one drift event in the logs to point to during an interview. The promotion timeline in the dashboard is only compelling if it contains real entries from real runs.

---

## Docker services

```yaml
services:
  postgres:       # Feature store + forecast output + promotion log
  airflow:        # Scheduler + webserver
  mlflow:         # Tracking server + model registry
  backend:        # FastAPI serving layer
  dashboard:      # React + MapLibre frontend
```

Run everything with:

```bash
git clone https://github.com/your-username/gridvision
cd gridvision
cp .env.example .env   # add EIA API key here
docker-compose up
```

Then open:
- Dashboard: http://localhost:3000
- Airflow UI: http://localhost:8080
- MLflow UI: http://localhost:5000
- API docs: http://localhost:8000/docs

---

## What makes this portfolio-ready

Most ML portfolio projects show a trained model. This shows a system:

- **Automated retraining** that actually runs on a schedule, not just a notebook
- **Evaluation gating** that prevents model regression — most production ML teams implement this; most portfolio projects don't
- **Live data** from a real government API, not a static Kaggle CSV
- **3D geospatial dashboard** that makes the multi-region story immediately legible to a non-technical interviewer
- **Promotion audit trail** — you can point to specific dates where the model improved or was rejected and explain why

Run it live for a few weeks before any interview so the logs are populated with real history.
