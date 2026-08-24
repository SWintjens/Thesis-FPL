"""
Sanitises `playermatchstats` rows before they are written to CSV.

Three defects were found in the 2026/27 pre-season (GW0 friendlies) export.
All three originate upstream, in the Supabase `playermatchstats` table - the
CSVs mirror it faithfully - so they are corrected here, on the way out, and
the correction is re-applied on every export run.

1. Phantom appearances (36 rows). A player is attached to a fixture that
   neither of his clubs played in, e.g. Gabriel (Arsenal) in
   `manchester-united-vs-leeds-united-2026-08-12`. Every affected player has
   a common surname and 39 of the 43 cross-club rows are in matches against
   non-Premier-League opposition whose squads are absent from the FPL player
   list, which points at surname-based player matching upstream: an
   opponent's player - usually an unused substitute, hence the blank stat
   line - gets bound to whichever FPL id shares his surname.

   Three are provably impossible: the same player appears in two different
   matches on the same day (Gabriel 12 Aug, George 25 Jul, N.Williams
   22 Jul). The 36th was found outside the friendlies, in the UEFA Super
   Cup, so this is not a pre-season-only defect.

   Cross-club rows are *not* all wrong. FPL only ever exposes a player's
   current club, so a player who moved during the window legitimately has
   pre-season minutes for his old club (Guessand for Villa, Johnson for
   Palace, McNeil for Everton, Welbeck for Brighton, Lukic for Fulham - 8
   rows). Those are kept. Removal is therefore driven by an explicit,
   hand-verified list rather than by the rule, and `find_cross_club_rows`
   exists to surface anything new for review instead of silently dropping it.

2. Non-appearances carry a null `minutes_played` (54 rows). An unused
   substitute is stored with `minutes_played = NULL` and an empty stat line
   instead of the `0` used everywhere else in the dataset (2025/26 GW31, for
   instance, has 100 zero-minute rows and no nulls). A consumer that falls
   back to `finish_min - start_min` when minutes are missing then renders the
   player as having played a full match. This is what put "121 minutes"
   against players who never came on.

3. `finish_min = 121` in four friendlies that ended at ~90, stamped on every
   player still on the pitch at the final whistle - the same rows'
   `minutes_played` proves the true length. (121 is legitimate elsewhere:
   2025/26 Forest v Midtjylland and Palace v AEK Larnaca really did go to
   extra time, and there the columns agree.) These four have a sound
   timeline otherwise, so `finish_min` is recomputed from it.

`minutes_played` is treated as authoritative throughout - it is the field
that agrees with the match reports, and the one FPL itself is scored on.

Not addressed here: `start_min` / `finish_min` are unreliable far more
widely than point 3. Whole matches carry no substitution timeline at all
(every player starting at 0), and much of 2025/26 stores 90-minute players
against a `finish_min` of 0 or 6. That is long-standing, leaves
`minutes_played` correct, and needs its own verification pass - so it is
reported rather than quietly rewritten.
"""

import argparse
import glob
import os
import re

import pandas as pd

# Rows removed by `drop_phantom_appearances`, as (player_id, match_id).
#
# Derived by taking every row whose player's club is absent from the fixture,
# then setting aside the ones explained by a transfer. FPL allocates player
# ids in per-club blocks when the season list is first published, so a
# player's id block records the club he was at when the window opened; a
# cross-club row is legitimate when the fixture involves that original club.
# Those below survive that test - the player was at neither club.
PHANTOM_APPEARANCES = frozenset({
    # Anthony (Brentford) -> Newcastle
    (105, '26-27-friendly-bristol-city-vs-newcastle-united-2026-07-29'),
    (105, '26-27-friendly-gateshead-fc-vs-newcastle-united-2026-07-25'),
    # Esse (Crystal Palace) -> Brighton
    (216, '26-27-friendly-brighton-hove-albion-vs-roma-2026-08-08'),
    # Gabriel (Arsenal) -> Man Utd; 12 Aug also has him at Arsenal v Como
    (4, '26-27-friendly-manchester-united-vs-atletico-madrid-2026-08-01'),
    (4, '26-27-friendly-manchester-united-vs-leeds-united-2026-08-12'),
    (4, '26-27-friendly-rosenborg-vs-manchester-united-2026-07-24'),
    # George (Everton) -> Palace; 25 Jul also has him at Bolton v Everton
    (242, '26-27-friendly-bromley-vs-crystal-palace-2026-07-25'),
    (242, '26-27-friendly-crystal-palace-vs-swindon-town-2026-07-18'),
    # Hall (Newcastle) -> Man City, Spurs
    (449, '26-27-friendly-manchester-city-vs-atletico-madrid-2026-08-09'),
    (449, '26-27-friendly-manchester-city-vs-inter-2026-08-01'),
    (449, '26-27-friendly-tottenham-hotspur-vs-milton-keynes-dons-2026-07-22'),
    # Henry (Brentford) -> Newcastle
    (89, '26-27-friendly-everton-vs-newcastle-united-2026-08-12'),
    (89, '26-27-friendly-valencia-vs-newcastle-united-2026-08-08'),
    # Jacob (Hull City) -> Man Utd
    (283, '26-27-friendly-manchester-united-vs-wrexham-2026-07-18'),
    (283, '26-27-friendly-rosenborg-vs-manchester-united-2026-07-24'),
    # Munoz (Crystal Palace) -> Liverpool
    (201, '26-27-friendly-liverpool-vs-monaco-2026-08-09'),
    # N.Williams (Nott'm Forest) -> Man Utd, Spurs; 22 Jul also has him at
    # Forest v Blackburn
    (469, '26-27-friendly-manchester-united-vs-atletico-madrid-2026-08-01'),
    (469, '26-27-friendly-manchester-united-vs-wrexham-2026-07-18'),
    (469, '26-27-friendly-rosenborg-vs-manchester-united-2026-07-24'),
    (469, '26-27-friendly-tottenham-hotspur-vs-milton-keynes-dons-2026-07-22'),
    # Ndiaye (Everton) -> Liverpool
    (237, '26-27-friendly-liverpool-vs-leeds-united-2026-08-02'),
    (237, '26-27-friendly-liverpool-vs-wrexham-2026-07-29'),
    # Sangare (Brentford) -> Man City
    (565, '26-27-friendly-manchester-city-vs-atletico-madrid-2026-08-09'),
    (565, '26-27-friendly-manchester-city-vs-inter-2026-08-01'),
    # Smith (Bournemouth) -> Palace
    (64, '26-27-friendly-bromley-vs-crystal-palace-2026-07-25'),
    (64, '26-27-friendly-crystal-palace-vs-swindon-town-2026-07-18'),
    # Thomas (Coventry City) -> Brighton
    (173, '26-27-friendly-brighton-hove-albion-vs-roma-2026-08-08'),
    # Watson (Brighton) -> Chelsea
    (133, '26-27-friendly-chelsea-vs-juventus-2026-08-05'),
    (133, '26-27-friendly-chelsea-vs-milan-2026-08-08'),
    (133, "26-27-friendly-johor-darul-ta'zim-vs-chelsea-2026-08-09"),
    # Wright (Coventry City) -> Liverpool, Villa
    (193, '26-27-friendly-bayern-münchen-vs-aston-villa-2026-08-07'),
    (193, '26-27-friendly-liverpool-vs-leeds-united-2026-08-02'),
    (193, '26-27-friendly-liverpool-vs-wrexham-2026-07-29'),
    # Xavi (Spurs) -> Man City
    (513, '26-27-friendly-manchester-city-vs-atletico-madrid-2026-08-09'),
    (513, '26-27-friendly-manchester-city-vs-inter-2026-08-01'),
    # Wright again, outside the friendlies: the same defect reached the UEFA
    # Super Cup, so this is not a pre-season-only problem.
    (193, '26-27-uefa-super-cup-paris-saint-germain-vs-aston-villa-2026-08-12'),
})

# Columns that describe the match or the player's team rather than his own
# involvement. A row can carry these while still being a non-appearance, so
# they do not count as evidence that the player took the field.
_NON_ACTIVITY_COLS = {
    'player_id', 'match_id', 'minutes_played', 'start_min', 'finish_min',
    'team_goals_conceded', 'penalties_scored', 'penalties_missed',
}

# start_min + minutes_played is allowed to differ from finish_min by this much
# before the timeline is treated as broken. Stoppage time is reported
# inconsistently between the two, and a minute either way is routine.
_TIMELINE_TOLERANCE = 2

# Matches that stamp finish_min = 121 on every player still on the pitch at
# the final whistle, despite having ended at ~90 - the same rows'
# minutes_played proves the true length, and the rest of each match's timeline
# is sound, so finish_min is recomputed inside these fixtures only.
#
# Scoped to an explicit list on purpose. start_min / finish_min are unreliable
# far more widely than this - much of 2025/26 stores 90-minute players against
# a finish_min of 0, and whole matches have no substitution timeline at all -
# but that is long-standing, affects minutes nowhere (minutes_played stays
# correct), and repairing it is a separate piece of work with its own
# verification. Widening this set silently restates history.
MISTIMED_MATCHES = frozenset({
    '26-27-friendly-arsenal-vs-borussia-dortmund-2026-08-09',
    '26-27-friendly-arsenal-vs-como-2026-08-12',
    '26-27-friendly-manchester-city-vs-inter-2026-08-01',
    '26-27-friendly-manchester-united-vs-leeds-united-2026-08-12',
})


def _fixture_sides(match_id: str) -> list[str]:
    """
    The home and away portions of a match_id.

    A match_id is `<season>-<tournament>-<home>-vs-<away>-<date>`, so the away
    side comes back clean but the home side still carries the tournament
    prefix - `26-27-community-shield-arsenal-vs-manchester-city-...` yields
    `community-shield-arsenal`. Rather than maintain a list of tournament
    slugs to strip, callers compare with `_side_is`, which tolerates it.
    """
    if not isinstance(match_id, str):
        return []
    body = re.sub(r'^\d{2}-\d{2}-', '', match_id)
    body = re.sub(r'-\d{4}-\d{2}-\d{2}(-\d+)?$', '', body)
    sides = body.split('-vs-')
    return sides if len(sides) == 2 else []


def _side_is(side: str, club_slug: str) -> bool:
    """Whether a match_id side refers to `club_slug`, prefix or not."""
    return side == club_slug or side.endswith('-' + club_slug)


def _team_code_to_slug(matches_df: pd.DataFrame) -> dict:
    """
    Maps FPL team codes to the slug used for that club in match_ids.

    Learnt from the data rather than hardcoded: `matches` carries home_team /
    away_team as FPL team codes, populated only for the Premier League side,
    and the match_id names both sides in order. Promotion and relegation
    therefore need no maintenance here.

    Only away sides are used to *learn* the mapping, since those are the ones
    a tournament prefix never contaminates.
    """
    votes: dict = {}
    for _, row in matches_df.iterrows():
        sides = _fixture_sides(row.get('match_id'))
        if not sides:
            continue
        code = row.get('away_team')
        if pd.isna(code):
            continue
        counts = votes.setdefault(int(code), {})
        counts[sides[1]] = counts.get(sides[1], 0) + 1
    return {code: max(counts, key=counts.get) for code, counts in votes.items()}


def drop_phantom_appearances(df: pd.DataFrame):
    """Removes the verified phantom rows. Returns (kept, removed)."""
    if df.empty or 'player_id' not in df.columns:
        return df, df.iloc[0:0]
    keys = list(zip(df['player_id'], df['match_id']))
    mask = pd.Series([k in PHANTOM_APPEARANCES for k in keys], index=df.index)
    return df[~mask].copy(), df[mask].copy()


def find_cross_club_rows(df: pd.DataFrame, players_df: pd.DataFrame,
                         matches_df: pd.DataFrame) -> pd.DataFrame:
    """
    Rows whose player's current club is absent from the fixture.

    Run *after* `drop_phantom_appearances`, so the known-bad rows are already
    gone and the known-good pre-transfer rows are what remains. Anything else
    it returns is a new occurrence of the upstream matching bug and wants a
    human look before it is added to PHANTOM_APPEARANCES.
    """
    empty = df.iloc[0:0]
    if df.empty or players_df.empty or matches_df.empty:
        return empty
    if 'team_code' not in players_df.columns:
        return empty

    code_to_slug = _team_code_to_slug(matches_df)
    if not code_to_slug:
        return empty

    merged = df.merge(players_df[['player_id', 'web_name', 'team_code']],
                      on='player_id', how='left')
    merged.index = df.index

    def is_cross_club(row):
        slug = code_to_slug.get(row['team_code']) if pd.notna(row['team_code']) else None
        if slug is None:
            return False  # club never seen in a fixture - cannot judge
        sides = _fixture_sides(row['match_id'])
        if not sides:
            return False  # unparseable match_id - do not guess
        return not any(_side_is(side, slug) for side in sides)

    return merged[merged.apply(is_cross_club, axis=1)]


def normalise_non_appearances(df: pd.DataFrame):
    """
    Stores an unused substitute as 0 minutes with no timeline.

    A null `minutes_played` alongside a completely empty stat line means the
    player was named but did not come on. Recording that as 0 - the
    convention everywhere else in the dataset - stops consumers falling back
    to `finish_min` and crediting him with a full match.
    """
    if df.empty or 'minutes_played' not in df.columns:
        return df, 0
    activity_cols = [c for c in df.columns if c not in _NON_ACTIVITY_COLS]
    mask = df['minutes_played'].isna()
    if activity_cols:
        mask &= df[activity_cols].isna().all(axis=1)
    if not mask.any():
        return df, 0
    df = df.copy()
    df.loc[mask, 'minutes_played'] = 0
    for col in ('start_min', 'finish_min'):
        if col in df.columns:
            df.loc[mask, col] = pd.NA
    return df, int(mask.sum())


def repair_timelines(df: pd.DataFrame):
    """
    Recomputes finish_min where it contradicts the authoritative minutes_played.

    Confined to MISTIMED_MATCHES, where the defect is verified and the rest of
    the timeline is sound. See that constant for why this is not applied
    dataset-wide.
    """
    needed = {'minutes_played', 'start_min', 'finish_min', 'match_id'}
    if df.empty or not needed.issubset(df.columns):
        return df, 0

    in_scope = df['match_id'].isin(MISTIMED_MATCHES)
    if not in_scope.any():
        return df, 0

    df = df.copy()
    # Only rows for players who actually took the field have a timeline worth
    # checking. An unused substitute is stored as 0 minutes against the match
    # length (start 0, finish 90) throughout the dataset - that is the
    # established convention, not a contradiction.
    played = (df['minutes_played'].fillna(0) > 0) & df['start_min'].notna() & df['finish_min'].notna()
    drift = (df['start_min'] + df['minutes_played'] - df['finish_min']).abs()
    recomputed = in_scope & played & (drift > _TIMELINE_TOLERANCE)
    if not recomputed.any():
        return df, 0

    df.loc[recomputed, 'finish_min'] = (
        df.loc[recomputed, 'start_min'] + df.loc[recomputed, 'minutes_played']
    )
    return df, int(recomputed.sum())


def _restore_integer_dtypes(df: pd.DataFrame, original_dtypes: dict) -> pd.DataFrame:
    """
    Keeps columns that arrived as integers serialising as `90`, not `90.0`.

    Clearing a value turns a plain int column into a float one, which would
    rewrite every untouched row in the file and bury the real change in
    cosmetic diff noise. The nullable integer dtype holds both a value and a
    blank. Columns that were already floats are left alone, so this never
    reformats data it did not otherwise touch.
    """
    for col, dtype in original_dtypes.items():
        if col not in df.columns or not pd.api.types.is_integer_dtype(dtype):
            continue
        try:
            df[col] = df[col].astype('Int64')
        except (TypeError, ValueError):
            pass
    return df


def sanitize(df: pd.DataFrame, players_df: pd.DataFrame, matches_df: pd.DataFrame,
             logger=None) -> pd.DataFrame:
    """Applies every correction. Safe to call on an empty frame."""
    def say(msg):
        if logger:
            logger.info(msg)

    if df.empty:
        return df

    original_dtypes = {c: df[c].dtype for c in ('start_min', 'finish_min') if c in df.columns}

    df, removed = drop_phantom_appearances(df)
    if len(removed):
        say(f"  > Removed {len(removed)} phantom appearance(s) "
            f"({removed['player_id'].nunique()} players).")

    df, zeroed = normalise_non_appearances(df)
    if zeroed:
        say(f"  > Set {zeroed} non-appearance row(s) to 0 minutes.")

    df, recomputed = repair_timelines(df)
    if recomputed:
        say(f"  > Recomputed finish_min on {recomputed} contradictory row(s).")

    unexplained = find_cross_club_rows(df, players_df, matches_df)
    if len(unexplained):
        say(f"  > {len(unexplained)} cross-club row(s) remain (expected 8 "
            f"pre-transfer appearances; review anything beyond that).")

    if not (len(removed) or zeroed or recomputed):
        return df  # untouched - do not disturb its dtypes or formatting
    return _restore_integer_dtypes(df, original_dtypes)


# --- CLI: apply the same corrections to CSVs already committed ----------------

def _clean_csv_tree(season_dir: str, apply_changes: bool) -> int:
    players_path = os.path.join(season_dir, 'players.csv')
    matches_path = os.path.join(season_dir, 'matches.csv')
    players_df = pd.read_csv(players_path) if os.path.exists(players_path) else pd.DataFrame()
    if os.path.exists(matches_path):
        matches_df = pd.read_csv(matches_path)
    else:
        found = glob.glob(os.path.join(season_dir, '**', 'matches.csv'), recursive=True)
        matches_df = pd.concat([pd.read_csv(f) for f in found], ignore_index=True) if found else pd.DataFrame()

    touched = 0
    for path in sorted(glob.glob(os.path.join(season_dir, '**', 'playermatchstats.csv'),
                                 recursive=True)):
        before = pd.read_csv(path)
        after = sanitize(before.copy(), players_df, matches_df)
        if after.equals(before):
            continue
        touched += 1
        print(f"{'updated' if apply_changes else 'would update'}: {path} "
              f"({len(before)} -> {len(after)} rows)")
        if apply_changes:
            after.to_csv(path, index=False)
    return touched


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season', default=None,
                        help='Season folder, e.g. 2026-2027. Defaults to all seasons.')
    parser.add_argument('--apply', action='store_true',
                        help='Write the corrections. Without it, only reports.')
    args = parser.parse_args()

    seasons = ([os.path.join('data', args.season)] if args.season
               else sorted(glob.glob(os.path.join('data', '*-*'))))
    total = sum(_clean_csv_tree(s, args.apply) for s in seasons if os.path.isdir(s))
    print(f"\n{total} file(s) {'updated' if args.apply else 'would change'}.")


if __name__ == '__main__':
    main()
