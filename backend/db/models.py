"""
backend/db/models.py

SQLAlchemy ORM models for the NRFI analytics database.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship

# Note: UniqueConstraint is still used by TeamStatsDaily below


class Base(DeclarativeBase):
    pass


class Game(Base):
    __tablename__ = "games"

    id = Column(Integer, primary_key=True)
    external_id = Column(Integer, unique=True, nullable=True, index=True)  # MLB game_pk
    game_date = Column(Date, nullable=False, index=True)
    game_time = Column(String(30), nullable=True)  # ISO UTC datetime string, e.g. "2026-04-01T23:10:00Z"
    home_team = Column(String(10), nullable=False)
    away_team = Column(String(10), nullable=False)
    inning_1_home_runs = Column(Integer, nullable=True)
    inning_1_away_runs = Column(Integer, nullable=True)
    nrfi = Column(Boolean, nullable=True)
    park = Column(String(100), nullable=True)
    game_number = Column(Integer, nullable=False, default=1)  # 1 or 2 for doubleheaders

    pitchers = relationship("GamePitchers", back_populates="game", uselist=False)
    odds = relationship("Odds", back_populates="game")
    features = relationship("NrfiFeatures", back_populates="game", uselist=False)


class Pitcher(Base):
    __tablename__ = "pitchers"

    id = Column(Integer, primary_key=True)
    external_id = Column(Integer, unique=True, nullable=False, index=True)  # MLB pitcher ID
    name = Column(String(100), nullable=True)
    throws = Column(String(1), nullable=True)  # "L" or "R"


class GamePitchers(Base):
    __tablename__ = "game_pitchers"

    id = Column(Integer, primary_key=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False, unique=True, index=True)
    home_sp_id = Column(Integer, ForeignKey("pitchers.id"), nullable=True)
    away_sp_id = Column(Integer, ForeignKey("pitchers.id"), nullable=True)

    game = relationship("Game", back_populates="pitchers")
    home_sp = relationship("Pitcher", foreign_keys=[home_sp_id])
    away_sp = relationship("Pitcher", foreign_keys=[away_sp_id])


class TeamStatsDaily(Base):
    __tablename__ = "team_stats_daily"

    id = Column(Integer, primary_key=True)
    team = Column(String(10), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    obp = Column(Float, nullable=True)
    slg = Column(Float, nullable=True)
    ops = Column(Float, nullable=True)
    first_inning_runs_scored_per_game = Column(Float, nullable=True)
    first_inning_runs_allowed_per_game = Column(Float, nullable=True)

    __table_args__ = (
        UniqueConstraint("team", "date", name="uq_team_stats_team_date"),
    )


class Odds(Base):
    __tablename__ = "odds"

    id = Column(Integer, primary_key=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False, index=True)
    source = Column(String(50), nullable=True)       # e.g. "draftkings"
    market = Column(String(20), nullable=True)        # e.g. "ml", "total", "nrfi"
    home_ml = Column(Integer, nullable=True)          # American odds
    away_ml = Column(Integer, nullable=True)
    total = Column(Float, nullable=True)
    total_over_odds = Column(Integer, nullable=True)
    total_under_odds = Column(Integer, nullable=True)
    first_inn_over_odds = Column(Integer, nullable=True)   # YRFI (Over 0.5)
    first_inn_under_odds = Column(Integer, nullable=True)  # NRFI (Under 0.5)
    fetched_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    game = relationship("Game", back_populates="odds")


class GameUmpire(Base):
    __tablename__ = "game_umpires"

    id = Column(Integer, primary_key=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False, unique=True, index=True)
    ump_id = Column(Integer, nullable=False, index=True)   # MLB umpire person ID
    ump_name = Column(String(100), nullable=True)

    game = relationship("Game")


class NrfiFeatures(Base):
    __tablename__ = "nrfi_features"

    id = Column(Integer, primary_key=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False, unique=True, index=True)

    # Starter features (home SP)
    home_sp_era = Column(Float, nullable=True)
    home_sp_whip = Column(Float, nullable=True)
    home_sp_k_pct = Column(Float, nullable=True)
    home_sp_bb_pct = Column(Float, nullable=True)
    home_sp_hr9 = Column(Float, nullable=True)

    # Starter features (away SP)
    away_sp_era = Column(Float, nullable=True)
    away_sp_whip = Column(Float, nullable=True)
    away_sp_k_pct = Column(Float, nullable=True)
    away_sp_bb_pct = Column(Float, nullable=True)
    away_sp_hr9 = Column(Float, nullable=True)

    # Team offense features
    home_team_first_inn_runs_per_game = Column(Float, nullable=True)
    away_team_first_inn_runs_per_game = Column(Float, nullable=True)

    # Park factor
    park_factor = Column(Float, nullable=True)

    # Weather features (None for dome parks)
    temperature_f = Column(Float, nullable=True)
    wind_speed_mph = Column(Float, nullable=True)
    wind_out_mph = Column(Float, nullable=True)   # positive = blowing toward CF
    is_dome = Column(Float, nullable=True)        # 1.0 = dome/closed roof, 0.0 = open

    # Umpire tendency (HP umpire's historical NRFI rate minus league avg, regressed)
    ump_nrfi_rate_above_avg = Column(Float, nullable=True)

    # Rolling recent-form features (last 5 starts, within-season, pre-game only)
    home_sp_last5_era = Column(Float, nullable=True)    # ERA proxy over last 5 starts
    home_sp_last5_whip = Column(Float, nullable=True)   # WHIP proxy over last 5 starts
    home_sp_first_inn_era = Column(Float, nullable=True) # First-inning ERA (season-to-date)
    home_sp_avg_velo = Column(Float, nullable=True)     # Avg fastball velo, last 5 starts
    home_sp_velo_trend = Column(Float, nullable=True)   # Last-start velo minus 5-start avg

    away_sp_last5_era = Column(Float, nullable=True)
    away_sp_last5_whip = Column(Float, nullable=True)
    away_sp_first_inn_era = Column(Float, nullable=True)
    away_sp_avg_velo = Column(Float, nullable=True)
    away_sp_velo_trend = Column(Float, nullable=True)

    # Pitcher rest (days since last start, None if first start of season)
    home_sp_days_rest = Column(Float, nullable=True)
    away_sp_days_rest = Column(Float, nullable=True)

    # Target and market probability
    nrfi_label = Column(Boolean, nullable=True)
    p_nrfi_model = Column(Float, nullable=True)
    p_nrfi_market = Column(Float, nullable=True)

    game = relationship("Game", back_populates="features")
