"""
backend/api/routers/games.py

Game listing endpoints.

GET /games/today       — all games in the DB scheduled for today
GET /games/{game_id}   — detail for a single game by internal DB id
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.models import Game
from backend.db.session import get_db

router = APIRouter(prefix="/games", tags=["games"])


class GameResponse(BaseModel):
    game_id: int
    game_date: str
    home_team: str
    away_team: str
    inning_1_home_runs: int | None
    inning_1_away_runs: int | None
    nrfi: bool | None

    class Config:
        from_attributes = True


def _to_response(game: Game) -> GameResponse:
    return GameResponse(
        game_id=game.id,
        game_date=str(game.game_date),
        home_team=game.home_team,
        away_team=game.away_team,
        inning_1_home_runs=game.inning_1_home_runs,
        inning_1_away_runs=game.inning_1_away_runs,
        nrfi=game.nrfi,
    )


@router.get("/today", response_model=list[GameResponse])
def games_today(db: Session = Depends(get_db)):
    """
    Return all games in the database scheduled for today.
    Returns an empty list if no games are found — this is expected until
    the daily schedule pipeline populates today's games.
    """
    today = date.today()
    games = db.query(Game).filter(Game.game_date == today).order_by(Game.id).all()
    return [_to_response(g) for g in games]


@router.get("/{game_id}", response_model=GameResponse)
def game_detail(game_id: int, db: Session = Depends(get_db)):
    """Return detail for a single game by internal DB id."""
    game = db.query(Game).filter(Game.id == game_id).first()
    if game is None:
        raise HTTPException(status_code=404, detail=f"Game {game_id} not found.")
    return _to_response(game)
