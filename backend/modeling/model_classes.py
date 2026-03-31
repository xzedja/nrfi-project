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
from sklearn.base import BaseEstimator, ClassifierMixin, TransformerMixin
from sklearn.impute import SimpleImputer
from xgboost import XGBClassifier


class SeasonStartImputer(BaseEstimator, TransformerMixin):
    """
    Two-pass imputer that handles start-of-season NULLs intelligently.

    Pass 1 — pitcher-specific proxy fill (row-level):
      NULL rolling features are filled with the same pitcher's prior-season
      equivalent from the same row, rather than the league median.
      e.g. home_sp_last5_era = NULL → use home_sp_era
           home_sp_velo_trend = NULL → use 0.0 (no trend = neutral)

    Pass 2 — median fill for anything still NULL after pass 1.

    This ensures start-of-season games show pitcher-specific predictions
    rather than collapsing every game to the league average.
    """

    # (null_col, proxy_col) — proxy is from the same row
    PROXY_MAP = [
        ("home_sp_last5_era",     "home_sp_era"),
        ("home_sp_last5_whip",    "home_sp_whip"),
        ("home_sp_first_inn_era", "home_sp_era"),
        ("away_sp_last5_era",     "away_sp_era"),
        ("away_sp_last5_whip",    "away_sp_whip"),
        ("away_sp_first_inn_era", "away_sp_era"),
        # Lineup OBP fallback: use prior-season team OBP if game-specific lineup is unavailable
        ("home_lineup_obp",            "home_team_obp"),
        ("away_lineup_obp",            "away_team_obp"),
        # First-inning K%/BB% fallback: use full-game prior-season rates if no in-season starts yet
        ("home_sp_first_inn_k_pct",    "home_sp_k_pct"),
        ("home_sp_first_inn_bb_pct",   "home_sp_bb_pct"),
        ("away_sp_first_inn_k_pct",    "away_sp_k_pct"),
        ("away_sp_first_inn_bb_pct",   "away_sp_bb_pct"),
    ]
    # Velocity trend: no starts yet → neutral (0 = no change)
    ZERO_COLS = ["home_sp_velo_trend", "away_sp_velo_trend"]

    def fit(self, X: pd.DataFrame, y=None) -> "SeasonStartImputer":
        self.feature_names_in_ = list(X.columns)
        X_pass1 = self._proxy_fill(X.copy())
        # Replace NaN medians (all-NULL columns) with 0.0 so transform never emits NaN
        self.medians_ = X_pass1.median().fillna(0.0)
        return self

    def transform(self, X: pd.DataFrame) -> np.ndarray:
        X_out = self._proxy_fill(X.copy())
        # Pass 2: fill remaining NULLs with training medians
        for col in X_out.columns:
            if col in self.medians_.index:
                X_out[col] = X_out[col].fillna(self.medians_[col])
        # Safety net: convert to float and fill any remaining NaN with 0
        X_arr = X_out.astype(float).values
        np.nan_to_num(X_arr, nan=0.0, copy=False)
        return X_arr

    def _proxy_fill(self, X: pd.DataFrame) -> pd.DataFrame:
        cols = set(X.columns)
        for null_col, proxy_col in self.PROXY_MAP:
            if null_col in cols and proxy_col in cols:
                mask = X[null_col].isna() & X[proxy_col].notna()
                if mask.any():
                    X[null_col] = X[null_col].where(~mask, X[proxy_col])
        for col in self.ZERO_COLS:
            if col in cols:
                X[col] = X[col].fillna(0.0)
        return X


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
        self.imputer_ = SeasonStartImputer()
        X_imp = self.imputer_.fit_transform(X)

        eval_set = None
        if X_val is not None and y_val is not None:
            X_val_imp = self.imputer_.transform(X_val)
            eval_set = [(X_val_imp, y_val)]

        self.clf_ = XGBClassifier(
            n_estimators=2000,
            max_depth=4,
            learning_rate=0.005,
            subsample=0.7,
            colsample_bytree=0.6,
            min_child_weight=30,
            gamma=0.3,
            reg_alpha=0.3,
            reg_lambda=2.0,
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
