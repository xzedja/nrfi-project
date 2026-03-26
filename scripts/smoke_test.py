import sys
sys.path.insert(0, '.')

import pybaseball
pybaseball.cache.enable()

df = pybaseball.statcast('2023-04-03', '2023-04-07', verbose=False)
print(f'Raw rows: {len(df)}')

expected_cols = ['game_pk', 'inning', 'inning_topbot', 'post_bat_score', 'pitcher', 'p_throws']
present = [c for c in expected_cols if c in df.columns]
missing = [c for c in expected_cols if c not in df.columns]

print(f'Columns present: {present}')
if missing:
    print(f'MISSING columns: {missing}')
else:
    print('All required columns present.')
