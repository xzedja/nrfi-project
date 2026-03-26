"""
backend/modeling/model_classes.py

Picklable model classes used by train_model.py and loaded by model_store.py.

Keeping these in a stable module (not __main__) ensures pickle can always
resolve the class path regardless of which script is the entry point.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.impute import SimpleImputer
from xgboost import XGBClassifier


class XGBModel(BaseEstimator, ClassifierMixin):
    """
    Sklearn-compatible wrapper around (SimpleImputer + XGBClassifier).

    Kept separate from Pipeline so we can pass a validation eval_set for early
    stopping — something Pipeline makes awkward.
    """

    def __init__(self) -> None:
        self.imputer_: SimpleImputer | None = None
        self.clf_: XGBClassifier | None = None
        self.classes_ = np.array([0, 1])

    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        X_val: pd.DataFrame | None = None,
        y_val: pd.Series | None = None,
    ) -> "XGBModel":
        self.imputer_ = SimpleImputer(strategy="median")
        X_imp = self.imputer_.fit_transform(X)

        eval_set = None
        if X_val is not None and y_val is not None:
            X_val_imp = self.imputer_.transform(X_val)
            eval_set = [(X_val_imp, y_val)]

        self.clf_ = XGBClassifier(
            n_estimators=2000,
            max_depth=3,
            learning_rate=0.005,
            subsample=0.7,
            colsample_bytree=0.6,
            min_child_weight=100,
            gamma=1.0,
            reg_alpha=0.5,
            reg_lambda=5.0,
            eval_metric="logloss",
            early_stopping_rounds=50 if eval_set else None,
            use_label_encoder=False,
            random_state=42,
            verbosity=0,
        )
        self.clf_.fit(X_imp, y, eval_set=eval_set, verbose=False)
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        X_imp = self.imputer_.transform(X)
        return self.clf_.predict_proba(X_imp)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)


class CalibratedModel:
    """
    Platt scaling wrapper: fits a 2-parameter logistic regression on raw model
    scores from a held-out val set.
    """

    def __init__(self, base_model: Any, calibrator: Any) -> None:
        self.base_model = base_model
        self.calibrator = calibrator

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        raw = self.base_model.predict_proba(X)[:, 1].reshape(-1, 1)
        return self.calibrator.predict_proba(raw)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)
