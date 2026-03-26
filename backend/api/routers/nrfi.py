"""
backend/api/routers/nrfi.py

NRFI prediction endpoints.

GET /nrfi/today        — predictions for all of today's games
GET /nrfi/{game_id}    — prediction for a single game by internal DB id

NOTE: Route order matters — /nrfi/today must be registered before
/nrfi/{game_id} so FastAPI does not try to parse "today" as an integer.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.modeling.predict import predict_for_game, predict_for_today

router = APIRouter(prefix="/nrfi", tags=["nrfi"])


class NrfiPrediction(BaseModel):
    game_id: int
    game_date: str
    home_team: str
    away_team: str
    p_nrfi_model: float
    p_nrfi_market: float | None
    edge: float | None


@router.get("/today", response_model=list[NrfiPrediction])
def nrfi_today(db: Session = Depends(get_db)):
    """
    Return NRFI predictions for all of today's games that have feature rows.

    Returns an empty list when:
      - No games are scheduled today in the DB (expected until the daily
        schedule pipeline is built), or
      - Games exist but features haven't been built yet.
    """
    return predict_for_today(db)


@router.get("/{game_id}", response_model=NrfiPrediction)
def nrfi_for_game(game_id: int, db: Session = Depends(get_db)):
    """
    Return the NRFI prediction for a single game.

    Returns 404 if the game doesn't exist or has no feature row yet.
    """
    result = predict_for_game(game_id, db)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Game {game_id} not found or has no feature data yet.",
        )
    return result
