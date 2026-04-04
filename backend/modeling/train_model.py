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
import json
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
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
from backend.modeling.model_classes import CalibratedModel, SeasonStartImputer, XGBModel
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

# Earliest season included — 2023+ has real NRFI odds data for p_nrfi_market feature
_DATA_START_YEAR = 2023

# Rolling validation window: most recent K days held out for model selection (LR vs XGB).
_VAL_WINDOW_DAYS = 7

# Calibration window: the 90 days immediately before the val window, carved out of
# training, used exclusively for Platt scaling. Needs ~900 games for a stable fit —
# large enough to cover a wide range of game contexts, recent enough to reflect
# current-season conditions.
_CALIB_WINDOW_DAYS = 90


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
                Game.game_date >= f"{_DATA_START_YEAR}-01-01",
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
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Expanding-window split with separate calibration and model-selection sets.

    Fit   : all completed games from _DATA_START_YEAR up to (today - val - calib days)
            — used to fit model weights (LR / XGB)
    Calib : the _CALIB_WINDOW_DAYS immediately before the val window
            — used only for Platt scaling; large enough (~900 games) to learn a
              proper probability mapping across diverse game contexts
    Val   : the most recent _VAL_WINDOW_DAYS of completed games
            — used only for model selection (LR vs XGB AUC comparison)
    Test  : today and future games (empty at train time — live evaluation only)
    """
    today = date.today()
    val_cutoff   = today - timedelta(days=_VAL_WINDOW_DAYS)
    calib_cutoff = val_cutoff - timedelta(days=_CALIB_WINDOW_DAYS)
    game_dates   = pd.to_datetime(df["game_date"]).dt.date

    fit   = df[game_dates <= calib_cutoff]
    calib = df[(game_dates > calib_cutoff) & (game_dates <= val_cutoff)]
    val   = df[(game_dates > val_cutoff)   & (game_dates <  today)]
    test  = df[game_dates >= today]
    return fit, calib, val, test


def evaluate(label: str, model: Any, X: pd.DataFrame, y: pd.Series) -> dict[str, float]:
    """Log and return AUC, log loss, and Brier score for a split. Returns zeros if empty."""
    if len(X) == 0:
        logger.info("%s — (empty split, skipped)", label)
        return {"auc": 0.0, "log_loss": 0.0, "brier": 0.0}
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

    fit_df, calib_df, val_df, test_df = date_based_split(df)
    today = date.today()
    val_cutoff   = today - timedelta(days=_VAL_WINDOW_DAYS)
    calib_cutoff = val_cutoff - timedelta(days=_CALIB_WINDOW_DAYS)
    logger.info(
        "Split — fit: %d games (through %s)  |  calib: %d games (%s – %s)"
        "  |  val: %d games (last %d days)  |  test (live): %d",
        len(fit_df),   calib_cutoff,
        len(calib_df), calib_cutoff + timedelta(days=1), val_cutoff,
        len(val_df),   _VAL_WINDOW_DAYS,
        len(test_df),
    )
    if len(calib_df) < 100:
        logger.warning("Calib set has only %d games — Platt scaling may be unstable.", len(calib_df))
    if len(val_df) < 20:
        logger.warning("Val set has only %d games — model selection may be unreliable.", len(val_df))

    X_fit   = fit_df[FEATURE_COLS]
    y_fit   = fit_df["nrfi_label"].astype(int)
    X_calib = calib_df[FEATURE_COLS]
    y_calib = calib_df["nrfi_label"].astype(int)
    X_val   = val_df[FEATURE_COLS]
    y_val   = val_df["nrfi_label"].astype(int)
    X_test  = test_df[FEATURE_COLS]
    y_test  = test_df["nrfi_label"].astype(int)

    # -----------------------------------------------------------------------
    # Baseline: logistic regression (fit on fit set, evaluate on calib + val)
    # -----------------------------------------------------------------------
    logger.info("--- Logistic Regression (baseline) ---")
    lr_model = _build_logistic_pipeline()
    lr_model.fit(X_fit, y_fit)
    evaluate("LR  Fit  ", lr_model, X_fit,   y_fit)
    evaluate("LR  Calib", lr_model, X_calib, y_calib)
    lr_val  = evaluate("LR  Val  ", lr_model, X_val,  y_val)
    evaluate("LR  Test ", lr_model, X_test,  y_test)

    coefs = lr_model.named_steps["clf"].coef_[0]
    logger.info("LR feature coefficients (positive = increases P(NRFI)):")
    for feat, coef in sorted(zip(FEATURE_COLS, coefs), key=lambda x: -abs(x[1])):
        logger.info("  %-45s  %+.4f", feat, coef)

    # -----------------------------------------------------------------------
    # XGBoost with early stopping on calib set
    # -----------------------------------------------------------------------
    logger.info("--- XGBoost (early stopping on calib set) ---")
    xgb_model = XGBModel()
    xgb_model.fit(X_fit, y_fit, X_val=X_calib, y_val=y_calib)
    evaluate("XGB Fit  ", xgb_model, X_fit,   y_fit)
    evaluate("XGB Calib", xgb_model, X_calib, y_calib)
    xgb_val = evaluate("XGB Val  ", xgb_model, X_val, y_val)
    evaluate("XGB Test ", xgb_model, X_test,  y_test)

    importances = xgb_model.clf_.feature_importances_
    logger.info("XGBoost feature importances (gain):")
    for feat, imp in sorted(zip(FEATURE_COLS, importances), key=lambda x: -x[1]):
        logger.info("  %-45s  %.4f", feat, imp)

    # -----------------------------------------------------------------------
    # Summary comparison (val set — most recent 7 days)
    # -----------------------------------------------------------------------
    logger.info("--- Comparison (Val set — last %d days) ---", _VAL_WINDOW_DAYS)
    logger.info(
        "  Logistic Regression — AUC: %.4f  |  Brier: %.4f",
        lr_val["auc"], lr_val["brier"],
    )
    logger.info(
        "  XGBoost             — AUC: %.4f  |  Brier: %.4f",
        xgb_val["auc"], xgb_val["brier"],
    )

    # -----------------------------------------------------------------------
    # Pick winner on val AUC
    # -----------------------------------------------------------------------
    if xgb_val["auc"] >= lr_val["auc"]:
        winner_name, winner = "XGBoost", xgb_model
    else:
        winner_name, winner = "Logistic Regression", lr_model
    logger.info("Winner: %s (val AUC %.4f)", winner_name, (xgb_val if winner_name == "XGBoost" else lr_val)["auc"])

    # -----------------------------------------------------------------------
    # Calibrate winner with Platt scaling on calib set (~900 diverse games)
    # -----------------------------------------------------------------------
    logger.info("Calibrating %s on calib set (%d games)...", winner_name, len(calib_df))
    raw_calib_probs = winner.predict_proba(X_calib)[:, 1].reshape(-1, 1)
    platt = _PlattLR(C=1.0, max_iter=1000)
    platt.fit(raw_calib_probs, y_calib)
    calibrated = CalibratedModel(winner, platt)
    cal_calib = evaluate("Calibrated Calib", calibrated, X_calib, y_calib)
    cal_val   = evaluate("Calibrated Val  ", calibrated, X_val,   y_val)

    save_model(calibrated, output_path)
    logger.info("Saved %s to %s", winner_name, output_path)

    # Write metadata so picks can always be traced to the model version that made them
    winner_val = xgb_val if winner_name == "XGBoost" else lr_val
    meta = {
        "trained_at": datetime.now().isoformat(),
        "winner": winner_name,
        "val_window_days": _VAL_WINDOW_DAYS,
        "calib_window_days": _CALIB_WINDOW_DAYS,
        "fit_start": str(fit_df["game_date"].min()),
        "fit_end": str(fit_df["game_date"].max()),
        "fit_games": len(fit_df),
        "calib_start": str(calib_df["game_date"].min()) if len(calib_df) else None,
        "calib_end": str(calib_df["game_date"].max()) if len(calib_df) else None,
        "calib_games": len(calib_df),
        "val_start": str(val_df["game_date"].min()) if len(val_df) else None,
        "val_end": str(val_df["game_date"].max()) if len(val_df) else None,
        "val_games": len(val_df),
        "val_auc": round(winner_val["auc"], 4),
        "calib_auc_calibrated": round(cal_calib["auc"], 4),
        "calib_brier_calibrated": round(cal_calib["brier"], 4),
        "val_auc_calibrated": round(cal_val["auc"], 4),
        "val_brier_calibrated": round(cal_val["brier"], 4),
    }
    meta_path = Path(output_path).with_suffix(".meta.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    logger.info("Metadata saved to %s", meta_path)

    return calibrated


def main() -> None:
    parser = argparse.ArgumentParser(description="Train NRFI model (XGBoost vs LogReg comparison).")
    parser.add_argument("--output", default=DEFAULT_MODEL_PATH)
    args = parser.parse_args()
    train(output_path=args.output)


if __name__ == "__main__":
    main()
