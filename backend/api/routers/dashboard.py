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
from sqlalchemy import extract, or_
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

class NrfiRecord(BaseModel):
    year: int
    nrfi_wins: int
    total: int
    nrfi_rate: float | None


# Alias used in DashboardGame fields (keeps API field names clear)
TeamNrfiRecord = NrfiRecord


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
    nrfi_current: NrfiRecord | None
    nrfi_prior: NrfiRecord | None


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
    implied_nrfi_pct: float | None
    implied_yrfi_pct: float | None


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
    home_team_first_inn_rpg: float | None
    away_team_first_inn_rpg: float | None
    home_team_nrfi_current: TeamNrfiRecord | None
    home_team_nrfi_prior: TeamNrfiRecord | None
    away_team_nrfi_current: TeamNrfiRecord | None
    away_team_nrfi_prior: TeamNrfiRecord | None
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


class SignalRecord(BaseModel):
    wins: int
    losses: int
    total: int
    win_pct: float | None
    roi_at_110: float | None


class YearStats(BaseModel):
    year: int
    total_games: int
    model_picks: SignalRecord
    yrfi_signal: SignalRecord


class SeasonStatsResponse(BaseModel):
    current_year: YearStats
    prior_year: YearStats


# ── Helpers ───────────────────────────────────────────────────────────────────

def _implied_pct(american_odds: int | None) -> float | None:
    if american_odds is None:
        return None
    if american_odds < 0:
        return round(-american_odds / (-american_odds + 100), 4)
    return round(100 / (american_odds + 100), 4)


def _batch_team_nrfi(
    db: Session, teams: set[str], years: list[int]
) -> dict[tuple[str, int], TeamNrfiRecord]:
    rows = (
        db.query(Game.home_team, Game.away_team, Game.nrfi, Game.game_date)
        .filter(
            extract("year", Game.game_date).in_(years),
            Game.nrfi.isnot(None),
            or_(Game.home_team.in_(list(teams)), Game.away_team.in_(list(teams))),
        )
        .all()
    )
    counts: dict[tuple[str, int], list[int]] = {}
    for home, away, nrfi, game_date in rows:
        year = game_date.year
        for team in (home, away):
            if team in teams:
                key = (team, year)
                if key not in counts:
                    counts[key] = [0, 0]
                counts[key][1] += 1
                if nrfi:
                    counts[key][0] += 1
    return {
        (team, year): TeamNrfiRecord(
            year=year,
            nrfi_wins=wins,
            total=total,
            nrfi_rate=round(wins / total, 4) if total > 0 else None,
        )
        for (team, year), (wins, total) in counts.items()
    }


def _batch_pitcher_nrfi(
    db: Session, pitcher_ids: set[int], years: list[int]
) -> dict[tuple[int, int], NrfiRecord]:
    rows = (
        db.query(
            GamePitchers.home_sp_id,
            GamePitchers.away_sp_id,
            Game.game_date,
            NrfiFeatures.nrfi_label,
        )
        .join(Game, GamePitchers.game_id == Game.id)
        .join(NrfiFeatures, NrfiFeatures.game_id == Game.id)
        .filter(
            extract("year", Game.game_date).in_(years),
            NrfiFeatures.nrfi_label.isnot(None),
            or_(
                GamePitchers.home_sp_id.in_(list(pitcher_ids)),
                GamePitchers.away_sp_id.in_(list(pitcher_ids)),
            ),
        )
        .all()
    )
    counts: dict[tuple[int, int], list[int]] = {}
    for home_sp_id, away_sp_id, game_date, nrfi_label in rows:
        year = game_date.year
        for pid in (home_sp_id, away_sp_id):
            if pid is not None and pid in pitcher_ids:
                key = (pid, year)
                if key not in counts:
                    counts[key] = [0, 0]
                counts[key][1] += 1
                if nrfi_label:
                    counts[key][0] += 1
    return {
        (pid, year): NrfiRecord(
            year=year,
            nrfi_wins=wins,
            total=total,
            nrfi_rate=round(wins / total, 4) if total > 0 else None,
        )
        for (pid, year), (wins, total) in counts.items()
    }


def _pitcher_detail(
    gp: GamePitchers | None,
    side: str,
    feat: NrfiFeatures,
    pitcher_nrfi: dict[tuple[int, int], NrfiRecord],
    current_year: int,
    prior_year: int,
) -> PitcherDetail:
    pitcher = (gp.home_sp if side == "home" else gp.away_sp) if gp else None
    p = f"{side}_sp_"
    pid = pitcher.id if pitcher else None
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
        nrfi_current=pitcher_nrfi.get((pid, current_year)) if pid is not None else None,
        nrfi_prior=pitcher_nrfi.get((pid, prior_year)) if pid is not None else None,
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

    current_year = today.year
    prior_year = current_year - 1
    teams = {g.home_team for g in games} | {g.away_team for g in games}
    nrfi_records = _batch_team_nrfi(db, teams, [prior_year, current_year])

    pitcher_ids: set[int] = set()
    for g in games:
        if g.pitchers:
            if g.pitchers.home_sp_id is not None:
                pitcher_ids.add(g.pitchers.home_sp_id)
            if g.pitchers.away_sp_id is not None:
                pitcher_ids.add(g.pitchers.away_sp_id)
    pitcher_nrfi = _batch_pitcher_nrfi(db, pitcher_ids, [prior_year, current_year]) if pitcher_ids else {}

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

        edge = (
            round(feat.p_nrfi_model - feat.p_nrfi_market, 4)
            if feat.p_nrfi_model is not None and feat.p_nrfi_market is not None
            else None
        )
        sig = _signal(feat.p_nrfi_market, edge)
        is_yrfi_sig = sig in ("yrfi_signal", "yrfi_slight", "yrfi_lean")

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
                    implied_nrfi_pct=_implied_pct(o.first_inn_under_odds),
                    implied_yrfi_pct=_implied_pct(o.first_inn_over_odds),
                )
                for o in odds_rows
            ],
            key=lambda b: (
                0 if (is_yrfi_sig and b.is_best_yrfi) or (not is_yrfi_sig and b.is_best_nrfi) else 1,
                -(b.nrfi_odds or -9999),
            ),
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
            home_sp=_pitcher_detail(gp, "home", feat, pitcher_nrfi, current_year, prior_year),
            away_sp=_pitcher_detail(gp, "away", feat, pitcher_nrfi, current_year, prior_year),
            home_team_first_inn_rpg=feat.home_team_first_inn_runs_per_game,
            away_team_first_inn_rpg=feat.away_team_first_inn_runs_per_game,
            home_team_nrfi_current=nrfi_records.get((game.home_team, current_year)),
            home_team_nrfi_prior=nrfi_records.get((game.home_team, prior_year)),
            away_team_nrfi_current=nrfi_records.get((game.away_team, current_year)),
            away_team_nrfi_prior=nrfi_records.get((game.away_team, prior_year)),
            p_nrfi_model=feat.p_nrfi_model,
            p_nrfi_market=feat.p_nrfi_market,
            edge=edge,
            signal=sig,
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


def _signal_record(wins: int, losses: int) -> SignalRecord:
    total = wins + losses
    win_pct = round(wins / total, 4) if total > 0 else None
    roi = round((wins * 100 - losses * 110) / (total * 110), 4) if total > 0 else None
    return SignalRecord(wins=wins, losses=losses, total=total, win_pct=win_pct, roi_at_110=roi)


def _year_stats(db: Session, year: int) -> YearStats:
    rows = (
        db.query(NrfiFeatures, Game)
        .join(Game, NrfiFeatures.game_id == Game.id)
        .filter(
            extract("year", Game.game_date) == year,
            NrfiFeatures.nrfi_label.isnot(None),
            NrfiFeatures.p_nrfi_model.isnot(None),
            NrfiFeatures.p_nrfi_market.isnot(None),
        )
        .all()
    )

    model_wins = model_losses = 0
    yrfi_wins = yrfi_losses = 0

    for feat, _game in rows:
        edge = feat.p_nrfi_model - feat.p_nrfi_market
        actual_nrfi = bool(feat.nrfi_label)

        if edge > 0:
            if actual_nrfi:
                model_wins += 1
            else:
                model_losses += 1

        if feat.p_nrfi_market >= _YRFI_THRESH:
            if not actual_nrfi:
                yrfi_wins += 1
            else:
                yrfi_losses += 1

    return YearStats(
        year=year,
        total_games=len(rows),
        model_picks=_signal_record(model_wins, model_losses),
        yrfi_signal=_signal_record(yrfi_wins, yrfi_losses),
    )


@router.get("/season-stats", response_model=SeasonStatsResponse)
def season_stats(db: Session = Depends(get_db)):
    """Return season W-L records for model picks and YRFI signal for current and prior year."""
    current_year = date.today().year
    return SeasonStatsResponse(
        current_year=_year_stats(db, current_year),
        prior_year=_year_stats(db, current_year - 1),
    )
