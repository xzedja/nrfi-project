"""
backend/modeling/predict.py

Serves NRFI predictions for individual games or a full day of games.

Primary functions:
  - predict_for_game(game_id, db)  → prediction dict for one game
  - predict_for_today(db)          → list of prediction dicts for today's games
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from backend.db.models import Game, NrfiFeatures, Odds
from backend.modeling.model_classes import DeltaModel
from backend.modeling.model_store import load_model
from backend.modeling.train_model import FEATURE_COLS

logger = logging.getLogger(__name__)

# Module-level model cache — loaded once on first prediction call
_model = None


def _get_model():
    global _model
    if _model is None:
        _model = load_model()
    return _model


def _features_to_series(feat: NrfiFeatures) -> pd.DataFrame:
    """Convert a NrfiFeatures ORM row into a single-row DataFrame for the model."""
    _DERIVED = {"park_x_wind_out", "home_sp_era_minus_away", "lineup_obp_diff"}
    # All other FEATURE_COLS are DB columns on NrfiFeatures (including p_nrfi_market)
    row = {col: getattr(feat, col, None) for col in FEATURE_COLS if col not in _DERIVED}

    # Compute interaction features (same logic as train_model.load_feature_dataframe)
    row["park_x_wind_out"]        = (feat.park_factor or 0) * (feat.wind_out_mph or 0) if feat.park_factor is not None and feat.wind_out_mph is not None else None
    row["home_sp_era_minus_away"] = (feat.home_sp_era - feat.away_sp_era) if feat.home_sp_era is not None and feat.away_sp_era is not None else None
    row["lineup_obp_diff"]        = (feat.away_lineup_obp - feat.home_lineup_obp) if feat.away_lineup_obp is not None and feat.home_lineup_obp is not None else None

    return pd.DataFrame([row])


def predict_for_game(game_id: int, db: Session) -> dict[str, Any] | None:
    """
    Return a prediction dict for a single game, or None if the game or its
    features are not found.

    Return shape:
      {
        "game_id":        int,
        "game_date":      str,        # YYYY-MM-DD
        "home_team":      str,
        "away_team":      str,
        "p_nrfi_model":   float,      # model probability (0–1)
        "p_nrfi_market":  float|None, # implied market probability if available
        "edge":           float|None, # p_nrfi_model - p_nrfi_market
      }
    """
    game = db.query(Game).filter(Game.id == game_id).first()
    if game is None:
        logger.warning("Game id=%d not found.", game_id)
        return None

    feat = db.query(NrfiFeatures).filter(NrfiFeatures.game_id == game_id).first()
    if feat is None:
        logger.warning("No NrfiFeatures found for game id=%d.", game_id)
        return None

    model = _get_model()
    X = _features_to_series(feat)
    p_model = float(model.predict_proba(X)[0, 1])

    p_market = feat.p_nrfi_market
    if p_market is None:
        odds_row = db.query(Odds).filter(Odds.game_id == game_id).first()
        if odds_row and odds_row.first_inn_under_odds and odds_row.first_inn_over_odds:
            from backend.data.fetch_odds import american_to_implied, remove_vig
            p_yrfi_raw = american_to_implied(odds_row.first_inn_over_odds)
            p_nrfi_raw = american_to_implied(odds_row.first_inn_under_odds)
            _, p_market = remove_vig(p_yrfi_raw, p_nrfi_raw)
            p_market = round(p_market, 4)

    # Fix 1: Market anchor blend for CalibratedModel.
    # When neither pitcher has in-season starts yet, the XGB/LR model collapses
    # to the same league-median prediction for every game. Blend toward the market
    # probability proportional to how much in-season data we actually have.
    # DeltaModel handles this internally (delta ≈ 0 when features uninformative).
    if p_market is not None and not isinstance(model, DeltaModel):
        h_has_data = feat.home_sp_last5_era is not None
        a_has_data = feat.away_sp_last5_era is not None
        in_season_coverage = (int(h_has_data) + int(a_has_data)) / 2.0
        if in_season_coverage < 1.0:
            p_model = in_season_coverage * p_model + (1.0 - in_season_coverage) * p_market
            logger.debug(
                "Game %d: market anchor blend (coverage=%.1f%%) → p_model=%.4f",
                game_id, in_season_coverage * 100, p_model,
            )

    edge = round(p_model - p_market, 4) if p_market is not None else None

    return {
        "game_id": game.id,
        "game_date": str(game.game_date),
        "home_team": game.home_team,
        "away_team": game.away_team,
        "p_nrfi_model": round(p_model, 4),
        "p_nrfi_market": round(p_market, 4) if p_market is not None else None,
        "edge": edge,
    }


def predict_for_today(db: Session) -> list[dict[str, Any]]:
    """
    Return predictions for all games scheduled today that have feature rows.
    Games without features are silently skipped.
    """
    today = date.today()
    games = db.query(Game).filter(Game.game_date == today).all()

    if not games:
        logger.info("No games found for %s.", today)
        return []

    results = []
    for game in games:
        pred = predict_for_game(game.id, db)
        if pred is not None:
            results.append(pred)

    logger.info("Predictions generated for %d / %d games on %s.", len(results), len(games), today)
    return results
