"""
scripts/backtest.py

Flat-stake historical backtest of NRFI model predictions vs market.

For each game where we have p_nrfi_model, p_nrfi_market, and nrfi_label:
  - Edge = p_nrfi_model - p_nrfi_market
  - A "bet" is placed when edge >= threshold (default: any positive edge)
  - Win = we bet NRFI and outcome was NRFI

Outputs:
  1. Overall record and ROI
  2. Results bucketed by edge size (1-2%, 2-3%, 3-4%, 4%+)
  3. Calibration check: empirical NRFI rate vs model probability buckets

ROI assumes -110 juice on NRFI bets (standard US book pricing) unless
actual NRFI odds are available in the odds table (then uses real odds).

Usage:
    python scripts/backtest.py
    python scripts/backtest.py --start 2022 --end 2025
    python scripts/backtest.py --min-edge 0.02
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from datetime import date

sys.path.insert(0, ".")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

from backend.data.fetch_odds import american_to_implied, remove_vig
from backend.db.models import Game, NrfiFeatures, Odds
from backend.db.session import SessionLocal
from backend.modeling.model_store import DEFAULT_MODEL_PATH, load_model
from backend.modeling.train_model import FEATURE_COLS


# Default vig assumption when no actual NRFI odds are stored
# -110 is standard US book juice → implied ~52.4% → payout $0.909 per $1 risked
_DEFAULT_NRFI_AMERICAN_ODDS = -110


def _payout_multiplier(american_odds: int) -> float:
    """
    Return the net profit per $1 staked for a winning bet.
    e.g. -110 → 0.909,  +120 → 1.20
    """
    if american_odds >= 0:
        return american_odds / 100.0
    return 100.0 / abs(american_odds)


def run_backtest(
    start_year: int = 2022,
    end_year: int = 2025,
    min_edge: float = 0.0,
) -> None:
    import pandas as pd

    # Load the current trained model
    model = load_model(DEFAULT_MODEL_PATH)

    db = SessionLocal()
    try:
        rows = (
            db.query(Game, NrfiFeatures)
            .join(NrfiFeatures, NrfiFeatures.game_id == Game.id)
            .filter(
                Game.game_date >= date(start_year, 1, 1),
                Game.game_date <= date(end_year, 12, 31),
                NrfiFeatures.nrfi_label.isnot(None),
            )
            .order_by(Game.game_date)
            .all()
        )

        # Build odds lookup: game_id → NRFI american odds
        game_ids = [game.id for game, _ in rows]
        odds_rows = (
            db.query(Odds)
            .filter(
                Odds.game_id.in_(game_ids),
                Odds.first_inn_under_odds.isnot(None),
            )
            .all()
        )
        nrfi_odds_map: dict[int, int] = {o.game_id: o.first_inn_under_odds for o in odds_rows}

    finally:
        db.close()

    logger.info(
        "Backtest: %d–%d  |  %d labeled games  |  %d with actual NRFI odds",
        start_year, end_year, len(rows), len(nrfi_odds_map),
    )

    # -----------------------------------------------------------------------
    # Batch predict using current model on stored features
    # Interaction features are derived the same way as train_model.py
    # -----------------------------------------------------------------------
    _BASE_COLS = [c for c in FEATURE_COLS if c not in (
        "park_x_wind_out", "home_sp_era_minus_away", "lineup_obp_diff"
    )]

    records = []
    for game, feat in rows:
        rec: dict = {}
        for col in _BASE_COLS:
            rec[col] = getattr(feat, col, None)
        records.append(rec)

    feat_df = pd.DataFrame(records)
    feat_df["park_x_wind_out"]        = feat_df["park_factor"] * feat_df["wind_out_mph"]
    feat_df["home_sp_era_minus_away"] = feat_df["home_sp_era"] - feat_df["away_sp_era"]
    feat_df["lineup_obp_diff"]        = feat_df["away_lineup_obp"] - feat_df["home_lineup_obp"]

    p_model_arr = model.predict_proba(feat_df[FEATURE_COLS])[:, 1]

    # -----------------------------------------------------------------------
    # Per-game edge computation and bet simulation
    # -----------------------------------------------------------------------
    bets: list[dict] = []
    no_market = 0

    for i, (game, feat) in enumerate(rows):
        p_model = float(p_model_arr[i])

        # Resolve market probability
        p_market = feat.p_nrfi_market
        if p_market is None:
            odds_row_raw = nrfi_odds_map.get(game.id)
            if odds_row_raw is None:
                no_market += 1
                continue
            p_nrfi_raw = american_to_implied(odds_row_raw)
            p_yrfi_raw = 1.0 - p_nrfi_raw + 0.04  # approximate vig
            _, p_market = remove_vig(p_yrfi_raw, p_nrfi_raw)

        edge = p_model - p_market
        if edge < min_edge:
            continue

        # Use actual stored NRFI odds if available, else -110 default
        nrfi_american = nrfi_odds_map.get(game.id, _DEFAULT_NRFI_AMERICAN_ODDS)
        payout = _payout_multiplier(nrfi_american)
        won = bool(feat.nrfi_label)

        bets.append({
            "date":     game.game_date,
            "edge":     edge,
            "p_model":  p_model,
            "p_market": p_market,
            "won":      won,
            "payout":   payout,
            "profit":   payout if won else -1.0,
        })

    if no_market:
        logger.info("Skipped %d games with no market probability.", no_market)

    if not bets:
        logger.info("No bets placed with min_edge=%.1f%%.", min_edge * 100)
        return

    # -----------------------------------------------------------------------
    # Overall results
    # -----------------------------------------------------------------------
    total_bets  = len(bets)
    total_wins  = sum(1 for b in bets if b["won"])
    total_profit = sum(b["profit"] for b in bets)
    roi = total_profit / total_bets * 100

    logger.info("")
    logger.info("=" * 55)
    logger.info("OVERALL  (%d–%d, edge ≥ %.1f%%)", start_year, end_year, min_edge * 100)
    logger.info("  Bets:   %d", total_bets)
    logger.info("  Record: %d-%d  (%.1f%%)", total_wins, total_bets - total_wins,
                total_wins / total_bets * 100)
    logger.info("  ROI:    %+.2f%%  (flat $1 stake)", roi)
    logger.info("=" * 55)

    # -----------------------------------------------------------------------
    # Results by edge bucket
    # -----------------------------------------------------------------------
    buckets = [
        ("0–1%",   0.00, 0.01),
        ("1–2%",   0.01, 0.02),
        ("2–3%",   0.02, 0.03),
        ("3–4%",   0.03, 0.04),
        ("4–5%",   0.04, 0.05),
        ("5%+",    0.05, 1.00),
    ]

    logger.info("")
    logger.info("RESULTS BY EDGE BUCKET")
    logger.info("  %-8s  %6s  %10s  %8s  %8s", "Edge", "Bets", "Record", "Hit%", "ROI")
    logger.info("  " + "-" * 50)

    for label, lo, hi in buckets:
        bucket_bets = [b for b in bets if lo <= b["edge"] < hi]
        if not bucket_bets:
            continue
        n = len(bucket_bets)
        w = sum(1 for b in bucket_bets if b["won"])
        bucket_roi = sum(b["profit"] for b in bucket_bets) / n * 100
        logger.info(
            "  %-8s  %6d  %5d-%-4d  %7.1f%%  %+7.2f%%",
            label, n, w, n - w, w / n * 100, bucket_roi,
        )

    # -----------------------------------------------------------------------
    # Calibration check: empirical NRFI rate vs model probability bucket
    # -----------------------------------------------------------------------
    logger.info("")
    logger.info("CALIBRATION CHECK (all games with market, not just bets)")

    cal_buckets: dict[str, list] = defaultdict(list)
    for i, (game, feat) in enumerate(rows):
        p_model = float(p_model_arr[i])
        actual = int(feat.nrfi_label)
        bucket_label = f"{int(p_model * 100 // 5) * 5}-{int(p_model * 100 // 5) * 5 + 5}%"
        cal_buckets[bucket_label].append((p_model, actual))

    logger.info("  %-10s  %6s  %10s  %8s", "Model%", "Games", "Empirical%", "Avg Model%")
    logger.info("  " + "-" * 40)
    for bucket_label in sorted(cal_buckets.keys()):
        data = cal_buckets[bucket_label]
        empirical = sum(a for _, a in data) / len(data) * 100
        avg_model = sum(p for p, _ in data) / len(data) * 100
        logger.info("  %-10s  %6d  %9.1f%%  %9.1f%%", bucket_label, len(data), empirical, avg_model)

    # -----------------------------------------------------------------------
    # Results by year
    # -----------------------------------------------------------------------
    logger.info("")
    logger.info("RESULTS BY YEAR")
    logger.info("  %-6s  %6s  %10s  %8s  %8s", "Year", "Bets", "Record", "Hit%", "ROI")
    logger.info("  " + "-" * 48)

    year_bets: dict[int, list] = defaultdict(list)
    for b in bets:
        year_bets[b["date"].year].append(b)

    for year in sorted(year_bets):
        yb = year_bets[year]
        n = len(yb)
        w = sum(1 for b in yb if b["won"])
        y_roi = sum(b["profit"] for b in yb) / n * 100
        logger.info(
            "  %-6d  %6d  %5d-%-4d  %7.1f%%  %+7.2f%%",
            year, n, w, n - w, w / n * 100, y_roi,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest NRFI model predictions.")
    parser.add_argument("--start", type=int, default=2022, help="Start year (default: 2022)")
    parser.add_argument("--end",   type=int, default=2025, help="End year (default: 2025)")
    parser.add_argument("--min-edge", type=float, default=0.0,
                        help="Minimum edge to place a bet, as decimal (default: 0.0 = all positive edges)")
    args = parser.parse_args()
    run_backtest(start_year=args.start, end_year=args.end, min_edge=args.min_edge)


if __name__ == "__main__":
    main()
