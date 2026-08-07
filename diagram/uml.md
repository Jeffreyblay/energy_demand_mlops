# ⚡ GridVision — UML Diagrams (Mermaid)

Unified Modeling Language views of the GridVision energy-demand MLOps pipeline.
Every fenced ` ```mermaid ` block below is **self-contained** — copy one block
at a time into [mermaid.live](https://mermaid.live) to render/export it.

UML diagrams included (structural + behavioral):

| # | UML diagram | Kind | Answers |
|---|---|---|---|
| 1 | [Use Case](#1-use-case-diagram) | behavioral | Who uses the system and for what |
| 2 | [Activity](#2-activity-diagram--daily-retrain-workflow) | behavioral | The workflow / control flow of the DAG |
| 3 | [Component](#3-component-diagram) | structural | How the services fit together |
| 4 | [Class](#4-class-diagram) | structural | The pipeline objects and their relations |
| 5 | [Sequence — retrain](#5-sequence-diagram--daily-retrain) | behavioral | Message order during a scheduled run |
| 6 | [Sequence — serving](#6-sequence-diagram--forecast-serving) | behavioral | Message order on an API request |
| 7 | [State Machine](#7-state-machine-diagram--model-lifecycle) | behavioral | Lifecycle of a model version |
| 8 | [Deployment](#8-deployment-diagram) | structural | Runtime nodes / Docker topology |

---

## 1. Use Case Diagram

Actors and the use cases the system exposes. (Mermaid has no native use-case
type; this is the conventional flowchart rendering — actors on the sides, use
cases as ovals inside the system boundary.)

```mermaid
flowchart LR
    analyst(["👤 Grid Analyst"])
    engineer(["👤 Data / MLOps Engineer"])
    scheduler(["⏰ GitHub Actions (cron)"])

    subgraph SYS["GridVision System"]
        uc1(["View regional demand forecast"])
        uc2(["Inspect P10/P90 intervals"])
        uc3(["Review promotion / rejection history"])
        uc4(["Trigger daily retrain"])
        uc5(["Evaluate & gate candidate model"])
        uc6(["Promote model to production"])
        uc7(["Configure API keys & connections"])
        uc8(["Monitor pipeline notifications"])
    end

    analyst --- uc1
    analyst --- uc2
    analyst --- uc3
    engineer --- uc7
    engineer --- uc8
    engineer --- uc3
    scheduler --- uc4
    uc4 -.->|«include»| uc5
    uc5 -.->|«extend»| uc6
```

---

## 2. Activity Diagram — daily retrain workflow

The control flow of `demand_retrain_dag`, in UML activity notation: filled
initial node, a **fork/join** for the parallel ingestion, a decision diamond for
the gate, and a final node. This is the "workflow" view.

```mermaid
flowchart TD
    START((●)) --> FORK[" "]
    FORK --> FD["fetch_demand_data"]
    FORK --> FW["fetch_weather_data"]
    FD --> JOIN[" "]
    FW --> JOIN
    JOIN --> BF["build_features"]
    BF --> AP["append_to_store"]
    AP --> RT["retrain_model"]
    RT --> BT["backtest_candidate"]
    BT --> DEC{"beats production<br/>AND baseline?"}
    DEC -->|yes| PM["promote_model"]
    DEC -->|no| LR["log_rejection"]
    PM --> GF["generate_forecast"]
    GF --> WD["write_dashboard_data"]
    WD --> NOT["notify"]
    LR --> NOT
    NOT --> END(((●)))

    classDef bar fill:#111827,stroke:#111827,color:#111827;
    class FORK,JOIN bar;
    classDef decision fill:#7c3aed,stroke:#4c1d95,color:#fff;
    class DEC decision;
```

> The two `[" "]` bars are the UML fork (split to parallel ingestion) and join
> (synchronize before feature build).

---

## 3. Component Diagram

Structural view of the deployable components and the interfaces between them.

```mermaid
flowchart TB
    subgraph EXT["«external systems»"]
        EIA[["EIA API v2"]]
        OM[["Open-Meteo API"]]
    end

    subgraph ORCH["«component» GitHub Actions (cron)"]
        DAG["run_pipeline.py"]
    end

    subgraph REGC["«component» Git Model Store"]
        REG["models/production/*<br/>(committed by the workflow)"]
    end

    subgraph DATA["«component» Neon Postgres"]
        FS[("Feature Store")]
        OUT[("Forecast + Summaries + Promotion Log")]
    end

    subgraph SRV["«component» FastAPI (Render)"]
        API["REST: /forecast /regions /history /health"]
    end

    subgraph WEB["«component» React + MapLibre (GitHub Pages)"]
        DASH["3D Dashboard"]
    end

    EIA -->|"HTTP"| DAG
    OM -->|"HTTP"| DAG
    DAG -->|"read/write features"| FS
    DAG -->|"load production model"| REG
    DAG -->|"git commit + push on promotion"| REG
    DAG -->|"write forecasts"| OUT
    API -->|"SELECT"| OUT
    DASH -->|"HTTP GET"| API
```

---

## 4. Class Diagram

Domain and pipeline objects, their operations, and relationships. (Conceptual —
refine as Phase 1 code lands.)

```mermaid
classDiagram
    class Config {
        +List~str~ regions
        +str eia_api_key
        +str postgres_dsn
        +float gate_threshold
    }

    class DemandFetcher {
        +fetch(date, regions) DemandFrame
    }
    class WeatherFetcher {
        +fetch(date, regions) WeatherFrame
    }
    class FeatureBuilder {
        +build(demand, weather) FeatureFrame
        -add_lags(df) DataFrame
        -add_calendar(df) DataFrame
        -add_rolling(df) DataFrame
    }
    class DataValidator {
        +validate(FeatureFrame) ValidationResult
    }
    class Trainer {
        +train(FeatureFrame) CandidateModel
    }
    class Backtester {
        +walk_forward(model, window) Metrics
    }
    class PromotionGate {
        +float threshold
        +decide(cand, prod, baseline) Decision
    }
    class Forecaster {
        +forecast(model, horizon) ForecastFrame
    }

    class FeatureFrame {
        +demand_lag_24h
        +demand_lag_168h
        +temperature
        +hour_of_day
        +day_of_week
        +is_holiday
        +demand_rolling_7d
    }
    class Metrics {
        +float mape
        +float rmse
    }
    class Decision {
        +bool promote
        +str reason
    }

    DemandFetcher ..> FeatureBuilder : feeds
    WeatherFetcher ..> FeatureBuilder : feeds
    FeatureBuilder --> FeatureFrame : produces
    FeatureBuilder ..> DataValidator : checked by
    FeatureFrame --> Trainer : trains
    Trainer --> Backtester : evaluated by
    Backtester --> Metrics : yields
    Metrics --> PromotionGate : judged by
    PromotionGate --> Decision : returns
    Trainer --> Forecaster : model used by
    Config ..> Trainer
    Config ..> DemandFetcher
    Config ..> PromotionGate
```

---

## 5. Sequence Diagram — daily retrain

Message order between the scheduler, external APIs, the git model store, and
Postgres for one scheduled run.

```mermaid
sequenceDiagram
    autonumber
    participant GHA as GitHub Actions
    participant EIA as EIA API
    participant OM as Open-Meteo
    participant FS as Feature Store (Neon)
    participant MS as Git Model Store
    participant PG as Postgres (Neon)

    par parallel ingestion
        GHA->>EIA: fetch yesterday's demand (9 regions)
        GHA->>OM: fetch matching hourly temperature
    end
    GHA->>FS: build_features + append (keep ~2yr)
    GHA->>GHA: train candidate LightGBM (local joblib bundle)
    GHA->>MS: read current production model + metadata
    GHA->>GHA: backtest candidate vs production vs baseline (7d)
    alt candidate beats production AND baseline
        GHA->>MS: copy candidate → production, bump version
        GHA->>GHA: git commit + push models/production/
        GHA->>PG: write forecast + region summaries + MAPE history
    else candidate fails gate
        GHA->>PG: write rejection record (date, MAPE)
    end
    GHA-->>GHA: print retrain summary (Actions run log)
```

---

## 6. Sequence Diagram — forecast serving

`GET /forecast?region=ERCOT`. The API only reads pre-computed forecasts — it
never recomputes on request.

```mermaid
sequenceDiagram
    autonumber
    participant UI as Dashboard (MapLibre)
    participant API as FastAPI
    participant PG as Postgres

    UI->>API: GET /regions
    API->>PG: SELECT region summaries
    PG-->>API: rows (demand, delta, temp, version)
    API-->>UI: GeoJSON region summaries
    Note over UI: extrude blocks by GW, color by intensity

    UI->>API: GET /forecast?region=ERCOT
    API->>PG: SELECT forecast WHERE region=ERCOT
    PG-->>API: next 24-48h rows (p10/p50/p90)
    API-->>UI: hourly forecast + intervals
    Note over UI: refreshes every 15 min
```

---

## 7. State Machine Diagram — model lifecycle

Lifecycle of a single model version in the git-committed model store
(`models/production/`).

```mermaid
stateDiagram-v2
    [*] --> Candidate: retrain_model
    Candidate --> Backtested: backtest_candidate
    Backtested --> Production: passes double gate
    Backtested --> Rejected: fails gate
    Production --> Archived: newer version promoted
    Rejected --> [*]
    Archived --> [*]

    note right of Production
        Exactly one version tagged
        "production" at a time.
        FastAPI serves from it
        (indirectly, via Postgres).
    end note
```

---

## 8. Deployment Diagram

**Live deployment** — no VM. Four independent, free-tier nodes; GitHub itself
is both the CI runner and the model's persistence layer (git).

```mermaid
flowchart TB
    subgraph GHA["«node» GitHub Actions (ephemeral runner)"]
        P1["run_pipeline.py<br/>(cron 0 6 * * *)"]
    end
    subgraph REPO["«node» GitHub repo"]
        MS[("models/production/*<br/>git-committed on promotion")]
    end
    subgraph NEON["«node» Neon (managed Postgres)"]
        DB[("features · forecasts ·<br/>region_summary · promotion_log")]
    end
    subgraph RENDER["«node» Render (free web service)"]
        API["FastAPI :443"]
    end
    subgraph PAGES["«node» GitHub Pages (static)"]
        DASH["React + MapLibre dashboard"]
    end

    P1 -->|"checkout / commit+push"| MS
    P1 -->|"SQL"| DB
    API -->|"SQL (read-only)"| DB
    DASH -->|"HTTPS GET"| API
```

**Local dev / demo** — the Docker Compose stack (unchanged, still useful for
showing the Airflow skill locally; not what drives the live deployment above).

```mermaid
flowchart TB
    subgraph HOST["«device» Docker Host"]
        subgraph C1["«container» airflow"]
            A1["Scheduler + Webserver<br/>:8080"]
        end
        subgraph C2["«container» mlflow"]
            A2["Tracking + Registry<br/>:5000"]
        end
        subgraph C3["«container» postgres"]
            A3[("DB :5432<br/>features · forecasts · log")]
        end
        subgraph C4["«container» backend"]
            A4["FastAPI :8000"]
        end
        subgraph C5["«container» dashboard"]
            A5["React + MapLibre :5173"]
        end
    end

    A1 -->|"JDBC/SQLAlchemy"| A3
    A1 -->|"HTTP"| A2
    A4 -->|"SQL"| A3
    A5 -->|"HTTP"| A4
    A2 -->|"metadata"| A3
```

---

*UML planning artifact for GridVision. Each block renders standalone on
mermaid.live — keep them in sync with the implementation as it evolves.*
