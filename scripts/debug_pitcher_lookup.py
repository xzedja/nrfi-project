"""Debug: find the correct player ID column name in pitching_stats."""
import sys
sys.path.insert(0, ".")

import pybaseball
pybaseball.cache.enable()

fg_df = pybaseball.pitching_stats(2022, 2022, qual=1)
print("All columns:")
for col in fg_df.columns:
    print(f"  {col!r}")

print(f"\nFirst row sample:")
print(fg_df[["Name", "Team", "ERA", "WHIP", "K%", "BB%"]].head(3).to_string())
