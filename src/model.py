"""
GridVision — QuantileForecaster (MLflow "models from code" definition).

Wraps the three trained LightGBM quantile boosters (P10/P50/P90) behind a single
MLflow pyfunc model, so the registry tracks ONE logical model whose predict()
returns all three quantiles as a DataFrame.

This file is logged to MLflow as the model definition (via `python_model=` path),
which avoids class-pickling / import-path issues. The trained boosters are passed
alongside as an artifact ("bundle") and loaded in `load_context`.
"""
from __future__ import annotations

import joblib
import mlflow.models
import mlflow.pyfunc
import pandas as pd

QUANTILE_KEYS = ("p10", "p50", "p90")


class QuantileForecaster(mlflow.pyfunc.PythonModel):
    # Loads the joblib bundle of quantile boosters when MLflow initializes the model.
    def load_context(self, context) -> None:
        bundle = joblib.load(context.artifacts["bundle"])
        self._models = {q: bundle[q] for q in QUANTILE_KEYS}
        self._features = bundle["features"]

    # Predicts all three quantiles for the given input and returns them as a DataFrame.
    def predict(self, context, model_input, params=None) -> pd.DataFrame:
        X = model_input[self._features]
        out = pd.DataFrame(index=model_input.index)
        for q in QUANTILE_KEYS:
            out[q] = self._models[q].predict(X)
        return out


# Registered as the model when this file is logged via models-from-code.
mlflow.models.set_model(QuantileForecaster())
