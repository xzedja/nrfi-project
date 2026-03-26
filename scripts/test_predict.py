"""Quick smoke test for predict_for_game."""
import sys
sys.path.insert(0, ".")

from backend.db.models import Game
from backend.db.session import SessionLocal
from backend.modeling.predict import predict_for_game

db = SessionLocal()

# Grab the first game that has a features row
game = (
    db.query(Game)
    .join(Game.features)
    .order_by(Game.game_date)
    .first()
)

if game is None:
    print("No games with features found — run build_features first.")
    sys.exit(1)

print(f"Testing on: {game.away_team} @ {game.home_team} ({game.game_date})\n")

result = predict_for_game(game.id, db)
db.close()

for k, v in result.items():
    print(f"  {k}: {v}")
