"""
scripts/market_analysis.py

Deep-dive into market inefficiency patterns to identify where the YRFI
heavy-favorite signal is strong, weak, or broken — and find new edges.

Sections:
  1. YRFI signal: threshold sweep (50%–75% market NRFI implied)
  2. YRFI signal: conditioning on park factor, weather, umpire, park type
  3. YRFI signal: time-of-season effect (early/mid/late)
  4. YRFI signal: model agreement/disagreement (does model lean NRFI or YRFI?)
  5. NRFI model picks: calibration by market tier
  6. Combined signal analysis

Usage:
    docker exec -it nrfi-backend-1 python scripts/market_analysis.py
    docker exec -it nrfi-backend-1 python scripts/market_analysis.py --start 2023 --end 2025
    docker exec -it nrfi-backend-1 python scripts/market_analysis.py --real-odds-only
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
from backend.db.models import Game, GameUmpire, NrfiFeatures, Odds
from backend.db.session import SessionLocal
from backend.modeling.model_store import DEFAULT_MODEL_PATH, load_model
from backend.modeling.train_model import FEATURE_COLS


def _payout(american_odds: int) -> float:
    if american_odds >= 0:
        return american_odds / 100.0
    return 100.0 / abs(american_odds)


def _roi_str(wins: int, total: int, profit: float) -> str:
    if total == 0:
        return "—"
    return f"{wins}-{total-wins}  {wins/total*100:.1f}%  {profit/total*100:+.1f}%"


def _section(title: str) -> None:
    logger.info("")
    logger.info("=" * 65)
    logger.info("  %s", title)
    logger.info("=" * 65)


def run_analysis(
    start_year: int = 2023,
    end_year: int = 2025,
    real_odds_only: bool = False,
) -> None:
    import pandas as pd
    import numpy as np

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

        game_ids = [g.id for g, _ in rows]

        odds_rows = (
            db.query(Odds)
            .filter(
                Odds.game_id.in_(game_ids),
                Odds.first_inn_under_odds.isnot(None),
            )
            .all()
        )
        nrfi_odds_map: dict[int, int] = {o.game_id: o.first_inn_under_odds for o in odds_rows}
        yrfi_odds_map: dict[int, int] = {
            o.game_id: o.first_inn_over_odds
            for o in odds_rows
            if o.first_inn_over_odds is not None
        }

        ump_rows = db.query(GameUmpire).filter(GameUmpire.game_id.in_(game_ids)).all()
        ump_map: dict[int, str] = {u.game_id: u.ump_name for u in ump_rows}

    finally:
        db.close()

    logger.info(
        "Loaded %d labeled games (%d–%d)  |  %d with actual NRFI odds",
        len(rows), start_year, end_year, len(nrfi_odds_map),
    )

    # -----------------------------------------------------------------------
    # Build records dataframe
    # -----------------------------------------------------------------------
    records = []
    for game, feat in rows:
        rec: dict = {col: getattr(feat, col, None) for col in FEATURE_COLS}
        records.append(rec)

    feat_df = pd.DataFrame(records)
    p_model_arr = model.predict_proba(feat_df[FEATURE_COLS])[:, 1]

    # Assemble analysis rows
    data = []
    for i, (game, feat) in enumerate(rows):
        has_real = game.id in nrfi_odds_map
        if real_odds_only and not has_real:
            continue

        p_market = feat.p_nrfi_market
        if p_market is None:
            raw = nrfi_odds_map.get(game.id)
            if raw is None:
                continue
            p_nrfi_r = american_to_implied(raw)
            p_yrfi_r = 1.0 - p_nrfi_r + 0.04
            _, p_market = remove_vig(p_yrfi_r, p_nrfi_r)

        p_model = float(p_model_arr[i])
        nrfi_label = bool(feat.nrfi_label)
        month = game.game_date.month

        data.append({
            "game_id":    game.id,
            "date":       game.game_date,
            "year":       game.game_date.year,
            "month":      month,
            "home_team":  game.home_team,
            "away_team":  game.away_team,
            "park":       game.park,
            "p_market":   p_market,
            "p_model":    p_model,
            "edge":       p_model - p_market,
            "nrfi":       nrfi_label,
            "park_factor":    feat.park_factor,
            "temperature_f":  feat.temperature_f,
            "wind_out_mph":   feat.wind_out_mph,
            "is_dome":        feat.is_dome,
            "ump_nrfi_above": feat.ump_nrfi_rate_above_avg,
            "ump_name":       ump_map.get(game.id),
            "nrfi_american":  nrfi_odds_map.get(game.id, -110),
            "yrfi_american":  yrfi_odds_map.get(game.id, -110),
            "has_real_odds":  has_real,
        })

    df = pd.DataFrame(data)
    if df.empty:
        logger.error("No data rows after filtering. Aborting.")
        return

    logger.info("Analysis rows: %d  (real-odds only: %s)", len(df), real_odds_only)

    # -----------------------------------------------------------------------
    # YRFI signal helper
    # -----------------------------------------------------------------------
    def yrfi_signal_stats(mask, label: str = ""):
        sub = df[mask]
        if len(sub) == 0:
            return
        wins = int((~sub["nrfi"]).sum())
        total = len(sub)
        profit = sum(
            _payout(int(row["yrfi_american"])) if not row["nrfi"] else -1.0
            for _, row in sub.iterrows()
        )
        roi = profit / total * 100
        act_nrfi_pct = sub["nrfi"].mean() * 100
        avg_mkt = sub["p_market"].mean() * 100
        logger.info(
            "  %-40s  %5d bets  %s  ActNRFI%.0f%%  MktNRFI%.0f%%",
            label, total, _roi_str(wins, total, profit), act_nrfi_pct, avg_mkt,
        )

    # -----------------------------------------------------------------------
    # Section 1: YRFI threshold sweep
    # -----------------------------------------------------------------------
    _section("1. YRFI SIGNAL — THRESHOLD SWEEP (bet YRFI when market NRFI% ≥ threshold)")
    logger.info("  %-40s  %5s  %-25s  %-8s  %-8s", "Threshold", "Bets", "Record W-L%  ROI", "ActNRFI%", "MktNRFI%")
    logger.info("  " + "-" * 95)
    for thresh in [0.50, 0.53, 0.55, 0.57, 0.58, 0.60, 0.62, 0.63, 0.65, 0.67, 0.70, 0.73, 0.75]:
        yrfi_signal_stats(df["p_market"] >= thresh, f"p_market ≥ {thresh:.0%}")

    # -----------------------------------------------------------------------
    # Section 2: YRFI signal conditioned on park/weather/umpire
    # -----------------------------------------------------------------------
    _section("2. YRFI SIGNAL (≥60%) — CONDITIONING VARIABLES")
    base_mask = df["p_market"] >= 0.60

    logger.info("  --- By Dome vs Open ---")
    yrfi_signal_stats(base_mask & (df["is_dome"] == 1.0), "dome park")
    yrfi_signal_stats(base_mask & (df["is_dome"] == 0.0), "open park")
    yrfi_signal_stats(base_mask & df["is_dome"].isna(),   "is_dome unknown")

    logger.info("  --- By Park Factor (open parks only) ---")
    open_mask = base_mask & (df["is_dome"] == 0.0)
    yrfi_signal_stats(open_mask & (df["park_factor"] < 0.95),              "park_factor < 0.95 (pitcher-friendly)")
    yrfi_signal_stats(open_mask & (df["park_factor"] >= 0.95) & (df["park_factor"] < 1.05), "park_factor 0.95–1.05 (neutral)")
    yrfi_signal_stats(open_mask & (df["park_factor"] >= 1.05),             "park_factor ≥ 1.05 (hitter-friendly)")
    yrfi_signal_stats(open_mask & df["park_factor"].isna(),                "park_factor unknown")

    logger.info("  --- By Temperature (open parks only) ---")
    yrfi_signal_stats(open_mask & (df["temperature_f"] < 55),              "temp < 55°F (cold)")
    yrfi_signal_stats(open_mask & (df["temperature_f"] >= 55) & (df["temperature_f"] < 72), "temp 55–72°F (mild)")
    yrfi_signal_stats(open_mask & (df["temperature_f"] >= 72),             "temp ≥ 72°F (warm)")
    yrfi_signal_stats(open_mask & df["temperature_f"].isna(),              "temp unknown")

    logger.info("  --- By Wind (open parks only) ---")
    yrfi_signal_stats(open_mask & (df["wind_out_mph"] < -3),               "wind_out < -3 (wind in)")
    yrfi_signal_stats(open_mask & (df["wind_out_mph"] >= -3) & (df["wind_out_mph"] < 3), "wind_out -3 to +3 (calm)")
    yrfi_signal_stats(open_mask & (df["wind_out_mph"] >= 3),               "wind_out ≥ +3 (wind out)")
    yrfi_signal_stats(open_mask & df["wind_out_mph"].isna(),               "wind unknown")

    logger.info("  --- By Umpire tendency ---")
    yrfi_signal_stats(base_mask & (df["ump_nrfi_above"] < -0.01),          "ump below avg NRFI (calls strikes)")
    yrfi_signal_stats(base_mask & (df["ump_nrfi_above"] >= -0.01) & (df["ump_nrfi_above"] < 0.01), "ump avg NRFI")
    yrfi_signal_stats(base_mask & (df["ump_nrfi_above"] >= 0.01),          "ump above avg NRFI (hitter-friendly)")
    yrfi_signal_stats(base_mask & df["ump_nrfi_above"].isna(),             "ump unknown")

    # -----------------------------------------------------------------------
    # Section 3: YRFI signal — time of season
    # -----------------------------------------------------------------------
    _section("3. YRFI SIGNAL (≥60%) — TIME OF SEASON")
    logger.info("  %-40s  %5s  %-25s  %-8s  %-8s", "Period", "Bets", "Record W-L%  ROI", "ActNRFI%", "MktNRFI%")
    logger.info("  " + "-" * 95)
    yrfi_signal_stats(base_mask & df["month"].isin([3, 4]),       "Mar–Apr (early season)")
    yrfi_signal_stats(base_mask & df["month"].isin([5, 6]),       "May–Jun")
    yrfi_signal_stats(base_mask & df["month"].isin([7, 8]),       "Jul–Aug")
    yrfi_signal_stats(base_mask & df["month"].isin([9, 10]),      "Sep–Oct (late season)")

    # By year
    logger.info("  --- By Year ---")
    for yr in sorted(df["year"].unique()):
        yrfi_signal_stats(base_mask & (df["year"] == yr), f"  {yr}")

    # -----------------------------------------------------------------------
    # Section 4: YRFI signal — model agreement
    # -----------------------------------------------------------------------
    _section("4. YRFI SIGNAL (≥60%) — MODEL AGREEMENT")
    logger.info("  Does fading the model improve the YRFI signal?")
    logger.info("  %-40s  %5s  %-25s  %-8s  %-8s", "Model stance", "Bets", "Record W-L%  ROI", "ActNRFI%", "MktNRFI%")
    logger.info("  " + "-" * 95)
    # When model also says NRFI (edge > 0) — both agree NRFI → weakens YRFI signal?
    yrfi_signal_stats(base_mask & (df["edge"] > 0.02),   "model says NRFI (edge > +2%)")
    yrfi_signal_stats(base_mask & (df["edge"] >= -0.02) & (df["edge"] <= 0.02), "model neutral (edge ±2%)")
    yrfi_signal_stats(base_mask & (df["edge"] < -0.02),  "model also says YRFI (edge < -2%)")

    # Threshold sweep at different model-alignment combinations
    logger.info("  --- YRFI signal ≥60% × model also says YRFI (edge < 0) ---")
    for thresh in [0.58, 0.60, 0.62, 0.65, 0.68, 0.70]:
        yrfi_signal_stats(
            (df["p_market"] >= thresh) & (df["edge"] < 0),
            f"mkt ≥ {thresh:.0%} AND edge < 0",
        )

    # -----------------------------------------------------------------------
    # Section 5: Model NRFI picks — calibration and ROI by edge tier
    # -----------------------------------------------------------------------
    _section("5. MODEL NRFI PICKS — ROI BY EDGE TIER")
    logger.info("  %-12s  %6s  %10s  %8s  %8s", "Edge tier", "Bets", "Record", "Hit%", "ROI")
    logger.info("  " + "-" * 56)

    for lo, hi, label in [
        (0.01, 0.02, "1–2%"),
        (0.02, 0.03, "2–3%"),
        (0.03, 0.04, "3–4%"),
        (0.04, 0.05, "4–5%"),
        (0.05, 0.07, "5–7%"),
        (0.07, 1.00, "7%+"),
    ]:
        sub = df[(df["edge"] >= lo) & (df["edge"] < hi)]
        if len(sub) == 0:
            continue
        wins = int(sub["nrfi"].sum())
        total = len(sub)
        profit = sum(
            _payout(int(row["nrfi_american"])) if row["nrfi"] else -1.0
            for _, row in sub.iterrows()
        )
        roi = profit / total * 100
        logger.info("  %-12s  %6d  %5d-%-4d  %7.1f%%  %+7.2f%%",
                    label, total, wins, total - wins, wins / total * 100, roi)

    # -----------------------------------------------------------------------
    # Section 6: Combined signal — YRFI market signal AND other factors
    # -----------------------------------------------------------------------
    _section("6. COMBINED SIGNAL ANALYSIS")

    logger.info("  --- YRFI signal ≥60%, open park, warm weather (≥65°F) ---")
    combined_mask = (
        (df["p_market"] >= 0.60) &
        (df["is_dome"] == 0.0) &
        (df["temperature_f"] >= 65)
    )
    yrfi_signal_stats(combined_mask, "warm open park ≥60%")

    logger.info("  --- YRFI signal ≥60%, open park, cold weather (<60°F) ---")
    cold_mask = (
        (df["p_market"] >= 0.60) &
        (df["is_dome"] == 0.0) &
        (df["temperature_f"] < 60)
    )
    yrfi_signal_stats(cold_mask, "cold open park ≥60%")

    logger.info("  --- YRFI signal ≥62%, non-pitcher-friendly park (pf ≥ 0.98) ---")
    hitter_mask = (
        (df["p_market"] >= 0.62) &
        (df["park_factor"] >= 0.98)
    )
    yrfi_signal_stats(hitter_mask, "≥62% mkt, pf ≥ 0.98")

    logger.info("  --- YRFI signal ≥60%, model edge < -1% (both signals agree YRFI) ---")
    double_yrfi = (df["p_market"] >= 0.60) & (df["edge"] < -0.01)
    yrfi_signal_stats(double_yrfi, "≥60% mkt + model edge < -1%")

    logger.info("  --- YRFI signal ≥60% in April only (small sample) ---")
    april_mask = (df["p_market"] >= 0.60) & (df["month"] == 4)
    yrfi_signal_stats(april_mask, "≥60% mkt in April")

    logger.info("  --- YRFI signal ≥65% any conditions ---")
    yrfi_signal_stats(df["p_market"] >= 0.65, "≥65% mkt (all conditions)")

    # -----------------------------------------------------------------------
    # Section 7: Top/bottom teams in YRFI signal universe
    # -----------------------------------------------------------------------
    _section("7. TEAM-LEVEL PATTERNS IN YRFI SIGNAL (≥60%)")
    yrfi_df = df[df["p_market"] >= 0.60].copy()

    logger.info("  --- Teams most often in the YRFI signal universe (as home team) ---")
    home_counts = yrfi_df.groupby("home_team").apply(
        lambda g: pd.Series({
            "bets": len(g),
            "yrfi_wins": int((~g["nrfi"]).sum()),
            "nrfi_rate": g["nrfi"].mean(),
        })
    ).sort_values("bets", ascending=False)

    for team, row in home_counts.head(15).iterrows():
        if row["bets"] < 5:
            continue
        logger.info("  HOME %-5s  %3d bets  NRFI hit %.0f%%  (YRFI wins %d)",
                    team, int(row["bets"]), row["nrfi_rate"] * 100, int(row["yrfi_wins"]))

    logger.info("  --- Teams most often in the YRFI signal universe (as away team) ---")
    away_counts = yrfi_df.groupby("away_team").apply(
        lambda g: pd.Series({
            "bets": len(g),
            "yrfi_wins": int((~g["nrfi"]).sum()),
            "nrfi_rate": g["nrfi"].mean(),
        })
    ).sort_values("bets", ascending=False)

    for team, row in away_counts.head(15).iterrows():
        if row["bets"] < 5:
            continue
        logger.info("  AWAY %-5s  %3d bets  NRFI hit %.0f%%  (YRFI wins %d)",
                    team, int(row["bets"]), row["nrfi_rate"] * 100, int(row["yrfi_wins"]))

    # -----------------------------------------------------------------------
    # Section 8: Market calibration — how well does market predict NRFI?
    # -----------------------------------------------------------------------
    _section("8. MARKET CALIBRATION — ActualNRFI% vs ImpliedNRFI%")
    logger.info("  %-14s  %6s  %10s  %10s  %8s", "Market bucket", "Games", "MktNRFI%", "ActNRFI%", "Market Err")
    logger.info("  " + "-" * 58)

    edges_list = []
    for lo, hi in [(0.40, 0.45), (0.45, 0.50), (0.50, 0.55), (0.55, 0.60),
                   (0.60, 0.65), (0.65, 0.70), (0.70, 1.00)]:
        sub = df[(df["p_market"] >= lo) & (df["p_market"] < hi)]
        if len(sub) == 0:
            continue
        avg_mkt = sub["p_market"].mean() * 100
        act = sub["nrfi"].mean() * 100
        err = avg_mkt - act  # positive = market overestimates NRFI
        label = f"{lo:.0%}–{hi:.0%}"
        logger.info("  %-14s  %6d  %9.1f%%  %9.1f%%  %+8.1f%%",
                    label, len(sub), avg_mkt, act, err)
        edges_list.append((label, len(sub), avg_mkt, act, err))

    logger.info("")
    logger.info("  NOTE: positive 'Market Err' means market OVER-estimates NRFI")
    logger.info("  (i.e. games priced ≥60%% NRFI actually go NRFI <60%% of the time)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=2023)
    parser.add_argument("--end",   type=int, default=2025)
    parser.add_argument("--real-odds-only", action="store_true")
    args = parser.parse_args()
    run_analysis(start_year=args.start, end_year=args.end, real_odds_only=args.real_odds_only)


if __name__ == "__main__":
    main()
