"""
backend/modeling/train_model.py

Trains an XGBoost model to predict NRFI probability and compares it against
a logistic regression baseline.

Features used (all pre-game, no leakage):
  Prior-season Fangraphs stats:
    home_sp_era, home_sp_fip, home_sp_whip, home_sp_k_pct, home_sp_bb_pct, home_sp_hr9
    away_sp_era, away_sp_fip, away_sp_whip, away_sp_k_pct, away_sp_bb_pct, away_sp_hr9
  Within-season rolling stats (last 5 starts):
    home_sp_last5_era, home_sp_last5_whip, home_sp_first_inn_era
    home_sp_avg_velo, home_sp_velo_trend, home_sp_days_rest
    away_sp_last5_era, away_sp_last5_whip, away_sp_first_inn_era
    away_sp_avg_velo, away_sp_velo_trend, away_sp_days_rest
  Team offense:
    home_team_first_inn_runs_per_game, away_team_first_inn_runs_per_game
    home_team_obp, away_team_obp, home_team_slg, away_team_slg
  Game-specific lineup strength (prior-season avg OBP of starting 9):
    home_lineup_obp, away_lineup_obp
  Park:
    park_factor
  Weather (None for dome parks, imputed to median):
    temperature_f, wind_speed_mph, wind_out_mph, is_dome
  Umpire:
    ump_nrfi_rate_above_avg

Split strategy: chronological (no shuffling) — prevents future leakage.

Usage:
    DATABASE_URL=postgresql://... python -m backend.modeling.train_model
    DATABASE_URL=postgresql://... python -m backend.modeling.train_model --output models/nrfi_model.pkl
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression as _PlattLR
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

sys.path.insert(0, ".")

from backend.db.models import Game, NrfiFeatures
from backend.db.session import SessionLocal
from backend.modeling.model_classes import CalibratedModel, DeltaModel, SeasonStartImputer, XGBDeltaModel, XGBModel
from backend.modeling.model_store import DEFAULT_MODEL_PATH, save_model

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

FEATURE_COLS = [
    # Prior-season Fangraphs pitcher stats
    "home_sp_era",
    "home_sp_fip",
    "home_sp_whip",
    "home_sp_k_pct",
    "home_sp_bb_pct",
    "home_sp_hr9",
    "away_sp_era",
    "away_sp_fip",
    "away_sp_whip",
    "away_sp_k_pct",
    "away_sp_bb_pct",
    "away_sp_hr9",
    # Within-season rolling (last 5 starts)
    "home_sp_last5_era",
    "home_sp_last5_whip",
    "home_sp_first_inn_era",
    "home_sp_avg_velo",
    "home_sp_velo_trend",
    "home_sp_days_rest",
    "away_sp_last5_era",
    "away_sp_last5_whip",
    "away_sp_first_inn_era",
    "away_sp_avg_velo",
    "away_sp_velo_trend",
    "away_sp_days_rest",
    # Team offense
    "home_team_first_inn_runs_per_game",
    "away_team_first_inn_runs_per_game",
    "home_team_obp",
    "away_team_obp",
    "home_team_slg",
    "away_team_slg",
    # Park
    "park_factor",
    # Weather
    "temperature_f",
    "wind_speed_mph",
    "wind_out_mph",
    "is_dome",
    # Umpire
    "ump_nrfi_rate_above_avg",
    # Game-specific lineup strength (prior-season avg OBP of starting 9)
    "home_lineup_obp",
    "away_lineup_obp",
    # Interaction features (derived at load time)
    "park_x_wind_out",        # park_factor × wind_out_mph  — park + wind together
    "home_sp_era_minus_away", # home_sp_era − away_sp_era  — relative pitcher quality
    "lineup_obp_diff",        # away_lineup_obp − home_lineup_obp — net offensive matchup
    # First-inning specific Statcast features (season-to-date prior starts)
    "home_sp_first_inn_k_pct",
    "home_sp_first_inn_bb_pct",
    "home_sp_first_inn_hard_pct",
    "away_sp_first_inn_k_pct",
    "away_sp_first_inn_bb_pct",
    "away_sp_first_inn_hard_pct",
    # Market prior — vig-removed implied P(NRFI) from bookmaker line (NULL → imputed to median)
    "p_nrfi_market",
]

# Date boundaries for train/val/test split
# 2020+ = modern baseball era (opener usage, shifted offenses, post-COVID)
_TRAIN_START_YEAR = 2023
_TRAIN_END_YEAR   = 2024   # train on 2023–2024 (real NRFI odds available)
_VAL_YEAR         = 2025   # validate on 2025
_TEST_START_YEAR  = 2026   # test on 2026–present


def load_feature_dataframe() -> pd.DataFrame:
    """
    Load NrfiFeatures joined with Game.game_date from the DB.
    Returns a DataFrame sorted chronologically with interaction features added.
    """
    # Base DB columns (exclude derived interaction features)
    _DERIVED = {"park_x_wind_out", "home_sp_era_minus_away", "lineup_obp_diff"}
    _BASE_COLS = [c for c in FEATURE_COLS if c not in _DERIVED]

    db = SessionLocal()
    try:
        rows = (
            db.query(NrfiFeatures, Game.game_date)
            .join(Game, NrfiFeatures.game_id == Game.id)
            .filter(
                NrfiFeatures.nrfi_label.isnot(None),
                Game.game_date >= f"{_TRAIN_START_YEAR}-01-01",
            )
            .order_by(Game.game_date)
            .all()
        )
    finally:
        db.close()

    records = []
    for feat, game_date in rows:
        record: dict[str, Any] = {"game_date": game_date, "nrfi_label": feat.nrfi_label}
        for col in _BASE_COLS:
            record[col] = getattr(feat, col, None)
        records.append(record)

    df = pd.DataFrame(records)

    # Derived interaction features (NaN-safe — NaN propagates when either input is NaN)
    df["park_x_wind_out"]        = df["park_factor"] * df["wind_out_mph"]
    df["home_sp_era_minus_away"] = df["home_sp_era"] - df["away_sp_era"]
    df["lineup_obp_diff"]        = df["away_lineup_obp"] - df["home_lineup_obp"]

    return df


def _audit_nrfi_rates(df: pd.DataFrame) -> None:
    """Log NRFI rate by season — sanity check that labels look correct."""
    df = df.copy()
    df["year"] = pd.to_datetime(df["game_date"]).dt.year
    logger.info("--- NRFI Rate Audit by Season ---")
    for year, grp in df.groupby("year"):
        rate = grp["nrfi_label"].mean()
        n = len(grp)
        logger.info("  %d:  %.1f%% NRFI  (%d games)", year, rate * 100, n)
    overall = df["nrfi_label"].mean()
    logger.info("  Overall: %.1f%% NRFI  (%d games)", overall * 100, len(df))


def date_based_split(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Split by fixed year boundaries to match realistic forward-in-time deployment.

    Train : 2020–2022  (modern era only)
    Val   : 2023
    Test  : 2024–present
    """
    years = pd.to_datetime(df["game_date"]).dt.year
    train = df[(years >= _TRAIN_START_YEAR) & (years <= _TRAIN_END_YEAR)]
    val   = df[years == _VAL_YEAR]
    test  = df[years >= _TEST_START_YEAR]
    return train, val, test


def evaluate(label: str, model: Any, X: pd.DataFrame, y: pd.Series) -> dict[str, float]:
    """Log and return AUC, log loss, and Brier score for a split."""
    probs = model.predict_proba(X)[:, 1]
    auc = roc_auc_score(y, probs)
    ll = log_loss(y, probs)
    brier = brier_score_loss(y, probs)
    logger.info(
        "%s — AUC: %.4f  |  Log Loss: %.4f  |  Brier: %.4f", label, auc, ll, brier
    )
    return {"auc": auc, "log_loss": ll, "brier": brier}





def _build_logistic_pipeline() -> Pipeline:
    return Pipeline([
        ("imputer", SeasonStartImputer()),
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(max_iter=1000, random_state=42)),
    ])


def train(output_path: str = DEFAULT_MODEL_PATH) -> Pipeline:
    df = load_feature_dataframe()
    logger.info("Loaded %d labeled rows from DB", len(df))

    if len(df) < 100:
        raise ValueError("Not enough labeled data to train. Run the backfill first.")

    _audit_nrfi_rates(df)

    train_df, val_df, test_df = date_based_split(df)
    logger.info(
        "Split — train: %d (%d–%d)  |  val: %d (%d)  |  test: %d (%d–%d)",
        len(train_df), _TRAIN_START_YEAR, _TRAIN_END_YEAR,
        len(val_df),   _VAL_YEAR,
        len(test_df),  _TEST_START_YEAR, pd.to_datetime(df["game_date"]).dt.year.max(),
    )

    X_train = train_df[FEATURE_COLS]
    y_train = train_df["nrfi_label"].astype(int)
    X_val = val_df[FEATURE_COLS]
    y_val = val_df["nrfi_label"].astype(int)
    X_test = test_df[FEATURE_COLS]
    y_test = test_df["nrfi_label"].astype(int)

    # -----------------------------------------------------------------------
    # Baseline: logistic regression
    # -----------------------------------------------------------------------
    logger.info("--- Logistic Regression (baseline) ---")
    lr_model = _build_logistic_pipeline()
    lr_model.fit(X_train, y_train)
    evaluate("LR  Train", lr_model, X_train, y_train)
    lr_val = evaluate("LR  Val  ", lr_model, X_val, y_val)
    lr_test = evaluate("LR  Test ", lr_model, X_test, y_test)

    coefs = lr_model.named_steps["clf"].coef_[0]
    logger.info("LR feature coefficients (positive = increases P(NRFI)):")
    for feat, coef in sorted(zip(FEATURE_COLS, coefs), key=lambda x: -abs(x[1])):
        logger.info("  %-45s  %+.4f", feat, coef)

    # -----------------------------------------------------------------------
    # XGBoost with early stopping on validation set
    # -----------------------------------------------------------------------
    logger.info("--- XGBoost (early stopping on val set) ---")
    xgb_model = XGBModel()
    xgb_model.fit(X_train, y_train, X_val=X_val, y_val=y_val)
    evaluate("XGB Train", xgb_model, X_train, y_train)
    xgb_val = evaluate("XGB Val  ", xgb_model, X_val, y_val)
    xgb_test = evaluate("XGB Test ", xgb_model, X_test, y_test)

    importances = xgb_model.clf_.feature_importances_
    logger.info("XGBoost feature importances (gain):")
    for feat, imp in sorted(zip(FEATURE_COLS, importances), key=lambda x: -x[1]):
        logger.info("  %-45s  %.4f", feat, imp)

    # -----------------------------------------------------------------------
    # Delta model: XGBRegressor trained on y' = nrfi_label - p_nrfi_market
    # Only uses rows where p_nrfi_market is available (real or Poisson).
    # When features are uninformative the predicted delta ≈ 0, leaving the
    # market probability intact — naturally handling early-season sparsity.
    # -----------------------------------------------------------------------
    logger.info("--- Delta Model (XGBRegressor on residual vs market) ---")
    train_d = train_df[train_df["p_nrfi_market"].notna()].copy()
    val_d   = val_df[val_df["p_nrfi_market"].notna()].copy()
    test_d  = test_df[test_df["p_nrfi_market"].notna()].copy()
    logger.info(
        "Delta split — train: %d  |  val: %d  |  test: %d",
        len(train_d), len(val_d), len(test_d),
    )

    delta_model_obj: DeltaModel | None = None
    delta_val: dict[str, float]  = {"auc": 0.0, "log_loss": 999.0, "brier": 999.0}
    delta_test: dict[str, float] = {"auc": 0.0, "log_loss": 999.0, "brier": 999.0}

    if len(train_d) >= 50 and len(val_d) >= 20:
        X_train_d = train_d[FEATURE_COLS]
        y_train_d = train_d["nrfi_label"].astype(float) - train_d["p_nrfi_market"]
        X_val_d   = val_d[FEATURE_COLS]
        y_val_d   = val_d["nrfi_label"].astype(float) - val_d["p_nrfi_market"]
        X_test_d  = test_d[FEATURE_COLS]

        xgb_delta = XGBDeltaModel()
        xgb_delta.fit(X_train_d, y_train_d, X_val=X_val_d, y_val=y_val_d)
        delta_model_obj = DeltaModel(xgb_delta)

        evaluate("Delta Train", delta_model_obj, X_train_d, train_d["nrfi_label"].astype(int))
        delta_val  = evaluate("Delta Val  ", delta_model_obj, X_val_d,  val_d["nrfi_label"].astype(int))
        if len(test_d) > 0:
            delta_test = evaluate("Delta Test ", delta_model_obj, X_test_d, test_d["nrfi_label"].astype(int))

        delta_importances = xgb_delta.feature_importances_
        logger.info("Delta model feature importances (gain):")
        for feat_name, imp in sorted(zip(FEATURE_COLS, delta_importances), key=lambda x: -x[1]):
            logger.info("  %-45s  %.4f", feat_name, imp)
    else:
        logger.warning("Not enough market-odds rows for delta model — skipping.")

    # -----------------------------------------------------------------------
    # Summary comparison
    # -----------------------------------------------------------------------
    logger.info("--- Comparison (Val set) ---")
    logger.info(
        "  Logistic Regression — AUC: %.4f  |  Brier: %.4f",
        lr_val["auc"], lr_val["brier"],
    )
    logger.info(
        "  XGBoost             — AUC: %.4f  |  Brier: %.4f",
        xgb_val["auc"], xgb_val["brier"],
    )
    if delta_model_obj is not None:
        logger.info(
            "  Delta Model         — AUC: %.4f  |  Brier: %.4f",
            delta_val["auc"], delta_val["brier"],
        )

    # -----------------------------------------------------------------------
    # Pick winner on val AUC
    # -----------------------------------------------------------------------
    candidates = [
        ("Logistic Regression", lr_model,  lr_val["auc"]),
        ("XGBoost",             xgb_model, xgb_val["auc"]),
    ]
    if delta_model_obj is not None:
        candidates.append(("Delta Model", delta_model_obj, delta_val["auc"]))

    winner_name, winner, winner_auc = max(candidates, key=lambda c: c[2])
    logger.info("Winner: %s (val AUC %.4f)", winner_name, winner_auc)

    # -----------------------------------------------------------------------
    # Calibrate winner (Platt scaling on val set).
    # DeltaModel already outputs calibrated probabilities — skip Platt.
    # -----------------------------------------------------------------------
    if isinstance(winner, DeltaModel):
        calibrated = winner
        logger.info("Delta Model selected — skipping Platt calibration (outputs probabilities directly).")
        cal_val  = delta_val
        cal_test = delta_test
    else:
        logger.info("Calibrating %s on val set...", winner_name)
        raw_val_probs = winner.predict_proba(X_val)[:, 1].reshape(-1, 1)
        platt = _PlattLR(C=1.0, max_iter=1000)
        platt.fit(raw_val_probs, y_val)
        calibrated = CalibratedModel(winner, platt)
        cal_val  = evaluate("Calibrated Val ", calibrated, X_val,  y_val)
        cal_test = evaluate("Calibrated Test", calibrated, X_test, y_test)
        logger.info(
            "Calibration effect on Brier (test): %.4f → %.4f",
            (xgb_test if winner_name == "XGBoost" else lr_test)["brier"],
            cal_test["brier"],
        )

    save_model(calibrated, output_path)
    logger.info("Saved %s to %s", winner_name, output_path)
    return calibrated


def main() -> None:
    parser = argparse.ArgumentParser(description="Train NRFI model (XGBoost vs LogReg comparison).")
    parser.add_argument("--output", default=DEFAULT_MODEL_PATH)
    args = parser.parse_args()
    train(output_path=args.output)


if __name__ == "__main__":
    main()
