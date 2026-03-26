import sys
sys.path.insert(0, '.')

from backend.db.session import SessionLocal
from backend.data.fetch_odds import fetch_and_store_odds

db = SessionLocal()
n = fetch_and_store_odds('2026-03-26', db)
print(f'Stored odds for {n} games')
db.close()

# Check what was stored
from backend.db.models import Odds, Game, NrfiFeatures
from backend.db.session import SessionLocal

db = SessionLocal()
rows = (
    db.query(Odds, Game)
    .join(Game, Odds.game_id == Game.id)
    .all()
)
for odds, game in rows:
    feat = db.query(NrfiFeatures).filter_by(game_id=game.id).first()
    p_market = feat.p_nrfi_market if feat else None
    print(f"{game.away_team} @ {game.home_team} | total={odds.total} | home_ml={odds.home_ml} | p_nrfi_market={p_market}")
db.close()
