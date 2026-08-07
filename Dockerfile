# GridVision — Airflow image (scheduler + webserver).
# Layers the ML stack (mlflow-SKINNY client only, LightGBM, pandas, etc.) onto
# the official Airflow image. Full MLflow runs as its own service (see
# Dockerfile.mlflow) because MLflow 3.x needs Flask>=3, which conflicts with
# Airflow 2.10's Flask<2.3 pin.
FROM apache/airflow:2.10.5-python3.12

USER root
# lightgbm's Linux wheel dynamically links libgomp at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

USER airflow
COPY requirements-airflow.txt /requirements-airflow.txt
RUN pip install --no-cache-dir -r /requirements-airflow.txt
