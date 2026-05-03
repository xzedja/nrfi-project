"""
backend/api/routers/dashboard.py

Enriched dashboard endpoint — returns all data the UI needs in one call.

GET /api/dashboard/today
"""

from __future__ import annotations

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from backend.db.models import Game, GamePitchers, GameUmpire, NrfiFeatures, Odds
from backend.db.session import get_db

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

_ET = ZoneInfo("America/New_York")
_CT = ZoneInfo("America/Chicago")
_PT = ZoneInfo("America/Los_Angeles")

_VALUE_THRESH = float(os.environ.get("VALUE_PLAY_THRESHOLD_PP", "2")) / 100
_YRFI_THRESH  = float(os.environ.get("YRFI_SIGNAL_THRESHOLD", "0.60"))
_EDGE_ZERO    = 0.001

_SIGNAL_ORDER = {
    "nrfi_strong": 0,
    "nrfi_lean":   1,
    "yrfi_signal": 2,
    "yrfi_slight": 3,
    "yrfi_lean":   4,
    "no_edge":     5,
}

_BOOK_NAMES: dict[str, str] = {
    "draftkings":     "DraftKings",
    "fanduel":        "FanDuel",
    "betmgm":         "BetMGM",
    "caesars":        "Caesars",
    "pointsbet":      "PointsBet",
    "betrivers":      "BetRivers",
    "bovada":         "Bovada",
    "mybookie":       "MyBookie",
    "williamhill_us": "William Hill",
    "barstool":       "Barstool",
    "unibet":         "Unibet",
    "betonlineag":    "BetOnline",
    "lowvig":         "LowVig",
    "pinnacle":       "Pinnacle",
}


def _fmt_time(utc_str: str | None, tz: ZoneInfo) -> str | None:
    if not utc_str:
        return None
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        return dt.astimezone(tz).strftime("%-I:%M %p")
    except Exception:
        return None


def _signal(p_market: float | None, edge: float | None) -> str:
    if p_market is None or edge is None or abs(edge) < _EDGE_ZERO:
        return "no_edge"
    if p_market >= _YRFI_THRESH:
        return "yrfi_signal"
    if edge >= _VALUE_THRESH:
        return "nrfi_strong"
    if edge > _EDGE_ZERO:
        return "nrfi_lean"
    if edge <= -_VALUE_THRESH:
        return "yrfi_lean"
    if edge < -_EDGE_ZERO:
        return "yrfi_slight"
    return "no_edge"


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class PitcherDetail(BaseModel):
    name: str | None
    throws: str | None
    last5_era: float | None
    last5_whip: float | None
    first_inn_era: float | None
    hold_rate: float | None
    avg_velo: float | None
    velo_trend: float | None
    days_rest: float | None
    first_inn_k_pct: float | None
    first_inn_bb_pct: float | None
    first_inn_hard_pct: float | None


class BookmakerLine(BaseModel):
    source: str
    display_name: str
    nrfi_odds: int | None
    yrfi_odds: int | None
    total: float | None
    home_ml: int | None
    away_ml: int | None
    is_best_nrfi: bool
    is_best_yrfi: bool


class DashboardGame(BaseModel):
    game_id: int
    game_date: str
    game_time_utc: str | None
    game_time_et: str | None
    game_time_ct: str | None
    game_time_pt: str | None
    home_team: str
    away_team: str
    park: str | None
    home_sp: PitcherDetail
    away_sp: PitcherDetail
    p_nrfi_model: float | None
    p_nrfi_market: float | None
    edge: float | None
    signal: str
    is_high_disagreement: bool
    temperature_f: float | None
    wind_speed_mph: float | None
    wind_out_mph: float | None
    is_dome: bool | None
    park_factor: float | None
    ump_name: str | None
    ump_nrfi_rate_above_avg: float | None
    bookmakers: list[BookmakerLine]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pitcher_detail(gp: GamePitchers | None, side: str, feat: NrfiFeatures) -> PitcherDetail:
    pitcher = (gp.home_sp if side == "home" else gp.away_sp) if gp else None
    p = f"{side}_sp_"
    return PitcherDetail(
        name=pitcher.name if pitcher else None,
        throws=pitcher.throws if pitcher else None,
        last5_era=getattr(feat, p + "last5_era", None),
        last5_whip=getattr(feat, p + "last5_whip", None),
        first_inn_era=getattr(feat, p + "first_inn_era", None),
        hold_rate=getattr(feat, p + "hold_rate", None),
        avg_velo=getattr(feat, p + "avg_velo", None),
        velo_trend=getattr(feat, p + "velo_trend", None),
        days_rest=getattr(feat, p + "days_rest", None),
        first_inn_k_pct=getattr(feat, p + "first_inn_k_pct", None),
        first_inn_bb_pct=getattr(feat, p + "first_inn_bb_pct", None),
        first_inn_hard_pct=getattr(feat, p + "first_inn_hard_pct", None),
    )


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get("/today", response_model=list[DashboardGame])
def dashboard_today(db: Session = Depends(get_db)):
    """Return enriched game data for today's dashboard."""
    today = date.today()

    games = (
        db.query(Game)
        .options(
            joinedload(Game.features),
            joinedload(Game.pitchers).joinedload(GamePitchers.home_sp),
            joinedload(Game.pitchers).joinedload(GamePitchers.away_sp),
            joinedload(Game.odds),
        )
        .filter(Game.game_date == today)
        .all()
    )

    ump_by_game: dict[int, GameUmpire] = {
        u.game_id: u
        for u in db.query(GameUmpire).filter(
            GameUmpire.game_id.in_([g.id for g in games])
        ).all()
    }

    result: list[DashboardGame] = []
    for game in games:
        feat: NrfiFeatures | None = game.features
        if feat is None:
            continue

        gp: GamePitchers | None = game.pitchers
        ump: GameUmpire | None = ump_by_game.get(game.id)

        odds_rows: list[Odds] = [
            o for o in game.odds
            if o.first_inn_under_odds is not None or o.first_inn_over_odds is not None
        ]

        nrfi_vals = [o.first_inn_under_odds for o in odds_rows if o.first_inn_under_odds is not None]
        yrfi_vals = [o.first_inn_over_odds  for o in odds_rows if o.first_inn_over_odds  is not None]
        best_nrfi = max(nrfi_vals) if nrfi_vals else None
        best_yrfi = max(yrfi_vals) if yrfi_vals else None

        bookmakers = sorted(
            [
                BookmakerLine(
                    source=o.source or "",
                    display_name=_BOOK_NAMES.get((o.source or "").lower(), (o.source or "").title()),
                    nrfi_odds=o.first_inn_under_odds,
                    yrfi_odds=o.first_inn_over_odds,
                    total=o.total,
                    home_ml=o.home_ml,
                    away_ml=o.away_ml,
                    is_best_nrfi=o.first_inn_under_odds is not None and o.first_inn_under_odds == best_nrfi,
                    is_best_yrfi=o.first_inn_over_odds  is not None and o.first_inn_over_odds  == best_yrfi,
                )
                for o in odds_rows
            ],
            key=lambda b: (0 if b.source == "draftkings" else 1, -(b.nrfi_odds or -9999)),
        )

        edge = (
            round(feat.p_nrfi_model - feat.p_nrfi_market, 4)
            if feat.p_nrfi_model is not None and feat.p_nrfi_market is not None
            else None
        )

        result.append(DashboardGame(
            game_id=game.id,
            game_date=str(game.game_date),
            game_time_utc=game.game_time,
            game_time_et=_fmt_time(game.game_time, _ET),
            game_time_ct=_fmt_time(game.game_time, _CT),
            game_time_pt=_fmt_time(game.game_time, _PT),
            home_team=game.home_team,
            away_team=game.away_team,
            park=game.park,
            home_sp=_pitcher_detail(gp, "home", feat),
            away_sp=_pitcher_detail(gp, "away", feat),
            p_nrfi_model=feat.p_nrfi_model,
            p_nrfi_market=feat.p_nrfi_market,
            edge=edge,
            signal=_signal(feat.p_nrfi_market, edge),
            is_high_disagreement=edge is not None and abs(edge) >= 0.07,
            temperature_f=feat.temperature_f,
            wind_speed_mph=feat.wind_speed_mph,
            wind_out_mph=feat.wind_out_mph,
            is_dome=bool(feat.is_dome) if feat.is_dome is not None else None,
            park_factor=feat.park_factor,
            ump_name=ump.ump_name if ump else None,
            ump_nrfi_rate_above_avg=feat.ump_nrfi_rate_above_avg,
            bookmakers=bookmakers,
        ))

    result.sort(key=lambda g: (_SIGNAL_ORDER.get(g.signal, 5), g.game_time_utc or ""))
    return result
