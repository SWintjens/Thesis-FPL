# 2025/26 Football Data Integration Review

This document records the data added, changed, cleaned, validated, and deliberately excluded on the `codex/data-integration-review` branch.

It is intended to let reviewers inspect the proposed output as though the detailed match data had been merged into the normal data pipeline. It does not add a production ingestion job, database migration, API credential, or external-source provenance layer.

## Review snapshot

| Item | Value |
|---|---|
| Review branch | `codex/data-integration-review` |
| Main-branch comparison point | `f7512476` |
| Full-season data commit | `4f12bc10` |
| Main refresh/merge commit | `49dcd7e6` |
| Final integration and cleaning commit | `b18f816f` |
| Primary validated scope | 2025/26 Premier League |
| Premier League gameweeks | GW1-GW38 |
| Premier League matches | 380 |
| Integration content | Data-only CSV outputs under `data/` |
| Quality-hardening content | Cleaned CSVs, one supplemental quarantine CSV, and this review document |

Row counts in this document use the canonical files under:

```text
data/2025-2026/By Tournament/Premier League/GW*/
```

The same Premier League records are also projected into:

```text
data/2025-2026/By Gameweek/GW*/
```

The `By Gameweek` files can also contain rows from other competitions, so they must not be added to the tournament totals again.

## Executive summary

The review branch contains a complete 380-match Premier League detail layer for 2025/26, with the identified timestamp, incident, and own-goal defects made explicit or removed.

| Dataset | Premier League rows | Match coverage | What it provides |
|---|---:|---:|---|
| `fixtures.csv` / `matches.csv` | 380 | 380/380 | Existing match-level results and aggregate statistics |
| `match_enrichment.csv` | 380 | 380/380 | Match context, shot-model xG totals, and data-quality flags |
| `playermatchstats.csv` | 12,754 | 380/380 | Core player-match statistics |
| `player_match_enrichment.csv` | 11,462 | 380/380 | Additional player-match totals and ratings |
| `xg_by_minute.csv` | 7,651 | 380/380 | Per-minute and cumulative shot-model xG |
| `momentum.csv` | 34,954 | 380/380 | Minute-indexed signed momentum values |
| `shots.csv` | 9,504 | 380/380 | Individual shots, xG, xGOT, outcomes, and locations |
| `incidents.csv` | 6,455 | 380/380 | Canonical goals, cards, substitutions, VAR, and period markers |
| `lineups.csv` | 15,153 | 380/380 | Confirmed starters and substitutes |
| `average_positions.csv` | 11,448 | 380/380 | Player average-position coordinates |

The main integration work was:

1. Adding the detailed match tables across the season.
2. Linking their player records to the repository's FPL player IDs.
3. Keeping FPL authoritative for FPL-owned fields such as minutes and availability.
4. Making the detailed match source authoritative for the reviewed technical statistics.
5. Recalculating technical percentages from internally consistent numerator/denominator pairs.
6. Removing unsupported columns rather than publishing permanently empty fields.
7. Preserving non-Premier-League data while updating the combined gameweek files.
8. Replacing placeholder or stale kickoff values and normalizing every nonblank 2025/26 kickoff to explicit UTC.
9. Quarantining invalid incident placeholders, removing duplicate own-goal pseudo-shots, and exposing shot-model xG separately from summary xG.

## Competition coverage

Detailed files were added outside the Premier League where the captured data supported them. Only the Premier League received the complete identity, authority, formula, and preservation validation described later in this document.

| Competition | Fixture rows | Matches with detailed files | Shots | Incidents | Lineups | Average positions | xG-minute rows | Momentum rows | Player enrichment rows |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Premier League | 380 | 380 | 9,504 | 6,455 | 15,153 | 11,448 | 7,651 | 34,954 | 11,462 |
| Champions League | 64 | 48 | 1,257 | 900 | 2,092 | 1,471 | 1,042 | 4,415 | 551 |
| EFL Cup | 40 | 37 | 1,035 | 582 | 1,479 | 1,157 | 851 | 3,404 | 626 |
| Europa League | 28 | 14 | 333 | 266 | 613 | 437 | 281 | 1,288 | 178 |
| Conference League | 14 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **Total** | **526** | **479** | **12,129** | **8,203** | **19,337** | **14,513** | **9,825** | **44,061** | **12,817** |

This means:

- Premier League detailed coverage is complete.
- The other competitions are useful additions but are not complete-season replacements for their existing data.
- Conference League retained its existing fixture and player-match data but received no new event-detail tables.
- Production adoption should treat non-Premier-League coverage separately rather than assuming the Premier League guarantees apply globally.

## New detailed datasets

### `xg_by_minute.csv`

Schema:

```text
match_id
minute
home_xg
away_xg
home_cumulative_xg
away_cumulative_xg
```

Premier League coverage:

- 7,651 rows.
- 380 matches.
- 7,651 unique `match_id`/`minute` keys.
- No blank cells.

Each row represents xG added during a match minute and the resulting cumulative xG for both teams. This is not a complete minute 1-90 grid: it contains only minutes with at least one retained shot, and multiple shots in the same minute are aggregated. Stoppage-time shots retain their added-time value in `shots.csv`, while their xG is folded into minute 45 or 90 here.

The timeline was reconciled after own-goal cleanup. Its key set exactly matches the cleaned shot table, cumulative values never decrease, and every minute/final total agrees with the four-decimal shot data within the expected 0.0005 tolerance of the timeline's three-decimal representation. Nineteen minutes containing only removed pseudo-shots consequently disappeared.

This is the detailed shot model's timeline. It is deliberately not presented as the same xG measure as the pre-existing summary xG in `matches.csv`; the model boundary is documented below.

### `momentum.csv`

Schema:

```text
match_id
minute
value
```

Premier League coverage:

- 34,954 rows.
- 380 matches.
- No blank cells.

The data stores the detailed source's signed momentum value at each recorded minute. It is a source-defined indicator, not a physical-tracking measurement and not an internally trained FPL model output.

### `shots.csv`

Schema:

```text
match_id
shot_index
minute
added_time
is_home
player_id
player_name
outcome
situation
body_part
xg
xgot
start_x
start_y
goal_mouth_y
goal_mouth_z
goal_mouth_location
```

Premier League coverage:

- 9,504 shots across 380 matches.
- 9,504 unique `match_id`/`shot_index` keys.
- Every shot has a linked `player_id`, xG, and start/goal-mouth coordinates.
- `added_time` is populated for 1,146 stoppage-time shots and structurally blank otherwise.
- xGOT is populated for 3,078 shots: 2,073 saves, 1,003 goals, and both retained own-goal attempts.
- xGOT is correctly inapplicable to misses, blocked shots, and shots off the post. It is additionally unavailable for 106 saved shots, which is a genuine source limitation.

Premier League shot outcomes:

| Outcome | Rows |
|---|---:|
| Miss | 3,308 |
| Block | 2,801 |
| Save | 2,179 |
| Goal | 1,003 |
| Post | 211 |
| `ownGoal` | 2 |

Premier League shot situations:

| Situation | Rows |
|---|---:|
| Assisted | 4,548 |
| Corner | 1,668 |
| Regular | 1,234 |
| Fast break | 660 |
| Set piece | 563 |
| Throw-in set piece | 488 |
| Free kick | 251 |
| Penalty | 92 |

Body-part coverage:

| Body part | Rows |
|---|---:|
| Right foot | 4,738 |
| Left foot | 2,958 |
| Head | 1,770 |
| Other | 38 |

Own goals required a specific cleanup. All 42 own-goal incidents remain in `incidents.csv`, but 40 defender-attributed rows that duplicated those own goals as shots were removed. Two genuine initiating attempts remain in `shots.csv` and are explicitly labelled `ownGoal` rather than being counted as normal goals.

### `incidents.csv`

Schema:

```text
match_id
incident_index
incident_type
minute
added_time
team_side
player_id
player_name
secondary_player_id
secondary_player_name
assist_player_id
assist_player_name
card_type
goal_type
home_score
away_score
text
```

Premier League incident breakdown:

| Incident type | Rows | Meaning |
|---|---:|---|
| Substitution | 3,132 | Player-off/player-on pair, team, and minute |
| Card | 1,470 | Yellow, straight red, or second-yellow red |
| Goal | 1,043 | Scorer, assist where supplied, goal type, and score state |
| Period | 382 | Primarily half-time and full-time score markers |
| Injury time | 378 | A stoppage-time announcement marker |
| VAR decision | 50 | A VAR marker linked to a player/team where supplied |
| **Total** | **6,455** | |

Card breakdown:

| Card type | Rows |
|---|---:|
| Yellow | 1,428 |
| Red | 28 |
| Second-yellow red | 14 |

Goal breakdown:

| Goal type | Rows |
|---|---:|
| Regular | 924 |
| Penalty | 77 |
| Own goal | 42 |

Coverage and quality:

| Timing coverage | Matches | Incident rows | Available event types |
|---|---:|---:|---|
| `available` | 191 | 3,688 | Goals, cards, substitutions, periods, injury time, and VAR |
| `limited` | 189 | 2,767 | Goals, cards, and substitutions only |

Important interpretation notes:

- Incidents are key timeline events, not every pass, tackle, foul, corner, or offside.
- Substitutions use primary and secondary player fields to retain both players; 3,127 of 3,132 contain the named and mapped secondary player.
- Period markers comprise 191 half-time, 146 full-time, and 45 second-half markers. Period and injury-time markers correctly have no player IDs.
- GW13-GW31 are structurally limited: all 189 matches lack period, injury-time, VAR, added-time, and descriptive-text rows. These absences were flagged rather than fabricated.
- Forty-eight `Unknown` card placeholders with the invalid minute `-5` were removed from canonical incidents and retained in `data/2025-2026/supplemental/incidents_quarantined.csv`. They comprise 46 yellows, one red, and one second-yellow red.
- Six named and safely mapped yellow-card records also arrived with minute `-5`. Their disciplinary events remain canonical, but their unusable minute is blank and counted in `unlocated_card_count`.
- Canonical incidents contain no negative minutes and no `Unknown` actor placeholders.

The supplemental quarantine has 48 unique rows across 44 matches. It preserves the original incident fields plus `gameweek` and `quarantine_reason`, but those rows are excluded from canonical counts and minute-based analysis.

### `lineups.csv`

Schema:

```text
match_id
team_side
team_code
player_id
player_name
position
jersey_number
is_starting
formation
lineup_status
```

Premier League coverage:

- 15,153 confirmed lineup rows.
- 8,360 starters, which is exactly 22 starters per match.
- 6,793 substitute/bench rows.
- No blank values in the final Premier League files.
- All player records have repository/FPL player IDs.

The formation is repeated on player rows so each lineup export remains independently usable.

### `average_positions.csv`

Schema:

```text
match_id
team_side
player_id
player_name
jersey_number
position
x
y
```

Premier League coverage:

- 11,448 player-position rows.
- All records have a player ID, player name, position, and x/y coordinates.
- 11,198 jersey numbers are populated.
- 250 jersey numbers remain blank because no same-match lineup evidence supported a safe value.

These are average coordinates, not full player movement or physical-tracking histories.

### `match_enrichment.csv`

Schema:

```text
match_id
travel_distance_km
weather_description
temperature_c
wind_speed
pitch_condition
is_local_derby
is_neutral_ground
lineup_status
home_shot_model_xg
away_shot_model_xg
incident_timing_coverage
unlocated_card_count
quarantined_incident_count
```

Premier League completeness:

| Column | Populated rows | Total rows |
|---|---:|---:|
| `match_id` | 380 | 380 |
| `travel_distance_km` | 48 | 380 |
| `weather_description` | 36 | 380 |
| `temperature_c` | 48 | 380 |
| `wind_speed` | 48 | 380 |
| `pitch_condition` | 48 | 380 |
| `is_local_derby` | 380 | 380 |
| `is_neutral_ground` | 380 | 380 |
| `lineup_status` | 380 | 380 |
| `home_shot_model_xg` | 380 | 380 |
| `away_shot_model_xg` | 380 | 380 |
| `incident_timing_coverage` | 380 | 380 |
| `unlocated_card_count` | 380 | 380 |
| `quarantined_incident_count` | 380 | 380 |

The five added fields make the two xG models and the incident limitations machine-readable. Shot-model totals equal the cleaned shot sums for all 760 team-match sides. Incident timing is `available` for 191 matches and `limited` for 189; `unlocated_card_count` sums to six and `quarantined_incident_count` sums to 48.

The weather, travel, and pitch fields are retained because genuine data exists, but they are sparse and should not be treated as complete-season analytical features.

### `player_match_enrichment.csv`

Schema:

```text
player_id
match_id
player_name
rating
possession_lost
attacking_shots_blocked
total_passes
total_long_balls
total_crosses
total_dribbles
ground_duels_lost
aerial_duels_lost
yellow_cards
red_cards
goalkeeper_punches
```

Premier League coverage:

- 11,462 player-match rows.
- 11,235 ratings.
- 227 ratings remain blank.
- Every other enrichment column is populated on every enrichment row, including genuine zero values.
- 11,461 of 11,492 positive-minute player-match appearances were accepted for detailed-source enrichment: 99.73% coverage.
- One additional record is a zero-minute, booking-only bench appearance.

The total-attempt and lost-duel columns provide the denominators needed to audit the technical percentages stored in `playermatchstats.csv`.

## Existing match files changed

### `fixtures.csv` and `matches.csv`

No new columns were added to these existing files. The final schema has 103 columns, and the 380 Premier League rows have no blank cells after unsupported columns were removed. The same schema is now used in the tournament and combined-gameweek projections; the 12 entirely empty historical physical-tracking columns no longer survive in `By Gameweek`.

The earlier integration filled or recalculated:

| Column | Premier League cells filled |
|---|---:|
| `kickoff_time` | 48 |
| `home_tackles_won_pct` | 379 |
| `away_tackles_won_pct` | 379 |

The later kickoff audit then checked the complete season, not only previously blank values:

- All 380 Premier League match times were matched to a complete finished-match fixture map.
- Against the pre-audit branch, 27 logical timestamps required a date/time correction: six in GW26/GW30/GW31, eight in GW32, and all 13 GW33 records.
- Another 305 Premier League values represented the correct instant but lacked an explicit UTC offset; 48 were already canonical.
- Every nonblank kickoff in every 2025/26 `fixtures.csv` and `matches.csv` now uses one timezone-aware `+00:00` representation.
- The two small GW26/GW31 changes record delayed actual starts; scheduled time would need a separate field if it becomes analytically useful.

`fixtures.csv` and `matches.csv` remain synchronized. Their existing statistics include possession, shots, summary xG, xGOT, big chances, passing, crossing, long balls, tackles, duels, dribbling, cards, saves, and box-location totals.

## xG model boundaries

The audit confirmed two internally valid but non-interchangeable xG measures:

- `matches.csv.home_expected_goals_xg` / `away_expected_goals_xg` are the existing match-summary values.
- `shots.csv` contains the detailed shot-model values; `xg_by_minute.csv` is its timeline, and `match_enrichment.csv.home_shot_model_xg` / `away_shot_model_xg` expose its match totals.

Across 760 Premier League team-match sides, the absolute summary-versus-shot-model difference is:

| Difference threshold | Team-match sides |
|---|---:|
| Greater than 0.01 | 392 (51.58%) |
| Greater than 0.05 | 235 (30.92%) |
| Greater than 0.08 | 173 (22.76%) |
| Greater than 0.10 | 149 (19.61%) |
| Greater than 1.00 | 2 (0.26%) |

The largest differences are Burnley-Newcastle's away side (summary 2.01, shot model 3.0736) and West Ham-Newcastle's home side (summary 1.75, shot model 2.7637).

The branch does not overwrite one xG universe with the other. That would hide a real model-definition difference. Detailed shot analysis should use the explicitly named shot-model fields; consumers of the legacy match aggregate can continue to use the summary fields.

Detailed shot counts agree with `matches.csv` for 758 of 760 team-match sides. The two residual exceptions are Fulham at West Ham in GW18 (17 detailed versus 15 summary) and Leeds at Tottenham in GW36 (12 versus 11). These are documented rather than silently forced to agree.

## Player-match authority policy

### What remains FPL-authoritative

The integration deliberately keeps FPL authoritative for the repository's established FPL-owned data, including:

- Player availability.
- Minutes played.
- Goals and assists.
- Start and finish intervals.
- Team goals conceded.
- Defensive-contribution fields.
- Every other `playermatchstats.csv` field not explicitly listed as detailed-source mutable below.

The detailed source is allowed to support a player-match link when its minute total differs, but it is not allowed to overwrite FPL minutes.

The exact 36 protected columns are:

```text
player_id
match_id
minutes_played
goals
assists
total_shots
xg
shots_on_target
big_chances_missed
touches_opposition_box
touches
chances_created
final_third_passes
interceptions
recoveries
blocks
clearances
headed_clearances
dribbled_past
was_fouled
fouls_committed
saves
goals_conceded
xgot_faced
goals_prevented
sweeper_actions
gk_accurate_passes
gk_accurate_long_balls
dispossessed
high_claim
saves_inside_box
offsides
start_min
finish_min
team_goals_conceded
defensive_contributions
```

### What is detailed-source authoritative

The following existing `playermatchstats.csv` columns are reconciled from the accepted detailed player-match record:

```text
xa
accurate_passes
accurate_crosses
accurate_long_balls
successful_dribbles
tackles_won
tackles
duels_won
duels_lost
ground_duels_won
aerial_duels_won
xgot
penalties_scored
penalties_missed
```

The following derived percentage columns are also detailed-source authoritative:

```text
accurate_passes_percent
accurate_crosses_percent
accurate_long_balls_percent
successful_dribbles_percent
tackles_won_percent
ground_duels_won_percent
aerial_duels_won_percent
```

Player-match `xg` is not indiscriminately overwritten. Detailed shot-level xG is stored in `shots.csv`, and the match progression is stored in `xg_by_minute.csv`. Existing player-match xG is preserved unless the integration has safe evidence for filling a genuine blank.

### Technical changes compared with the main-branch base

The Premier League `playermatchstats.csv` files increased from 12,461 to 12,754 rows, adding 293 safely linked player-match records and removing none.

The table below counts cells whose numeric value differs from the main-branch base on rows present in both versions. Large xA and xGOT counts include additional precision as well as genuine source differences.

| Column | Changed cells |
|---|---:|
| `xa` | 10,877 |
| `accurate_passes_percent` | 8,429 |
| `ground_duels_won_percent` | 6,007 |
| `tackles_won_percent` | 4,668 |
| `accurate_long_balls_percent` | 4,632 |
| `tackles_won` | 4,332 |
| `aerial_duels_won_percent` | 4,010 |
| `successful_dribbles_percent` | 3,259 |
| `minutes_played` | 2,782 |
| `xgot` | 2,357 |
| `accurate_passes` | 2,207 |
| `tackles` | 2,089 |
| `accurate_crosses_percent` | 1,433 |
| `successful_dribbles` | 1,192 |
| `accurate_long_balls` | 761 |
| `duels_lost` | 745 |
| `duels_won` | 726 |
| `ground_duels_won` | 470 |
| `aerial_duels_won` | 319 |
| `assists` | 247 |
| `accurate_crosses` | 48 |
| `penalties_scored` | 1 |
| **Total existing-row cell differences** | **61,591** |

The 3,029 minute and assist differences are FPL reconciliation corrections. The other 58,562 cells are the technical differences described above.

`penalties_missed` is in the authority set but did not require a numeric change against the comparison base.

The single `penalties_scored` correction was a player-match containing one penalty goal and one normal goal; the former value had incorrectly counted both goals as penalties.

### Changes made by the final authority pass

The comparison above measures the complete review branch against its main-branch base. The table below uses the later, post-recovery snapshot and therefore isolates only the final decision that the detailed source should win for the reviewed technical fields.

| Column | Changed | Existing values replaced | Blanks filled |
|---|---:|---:|---:|
| `xa` | 8,076 | 8,076 | 0 |
| `accurate_passes` | 1,963 | 1,963 | 0 |
| `accurate_crosses` | 34 | 34 | 0 |
| `accurate_long_balls` | 462 | 462 | 0 |
| `successful_dribbles` | 149 | 149 | 0 |
| `tackles_won` | 1,205 | 1,205 | 0 |
| `tackles` | 151 | 151 | 0 |
| `duels_won` | 756 | 719 | 37 |
| `duels_lost` | 758 | 727 | 31 |
| `ground_duels_won` | 508 | 457 | 51 |
| `aerial_duels_won` | 394 | 302 | 92 |
| `accurate_passes_percent` | 928 | 926 | 2 |
| `accurate_crosses_percent` | 140 | 36 | 104 |
| `accurate_long_balls_percent` | 374 | 314 | 60 |
| `successful_dribbles_percent` | 104 | 12 | 92 |
| `tackles_won_percent` | 96 | 12 | 84 |
| `ground_duels_won_percent` | 453 | 426 | 27 |
| `aerial_duels_won_percent` | 274 | 220 | 54 |
| `xgot` | 2,357 | 2,357 | 0 |
| `penalties_scored` | 69 | 1 | 68 |
| `penalties_missed` | 69 | 0 | 69 |
| **Total** | **19,320** | **18,549** | **771** |

The same final pass reconciled 122 existing `ground_duels_lost` values in `player_match_enrichment.csv`, giving 19,442 authoritative technical changes across the two canonical player-match tables.

Compared with main, the branch adds 293 `playermatchstats.csv` rows: 160 during the earlier recovery and 133 during the completeness repair. Separately, the final authority operation added 260 `player_match_enrichment.csv` rows before the completeness repair added another 133.

### Player-match completeness repair

A later season-wide audit found valid records in the captured 380-match player-stat stream that had not joined to FPL players. The repair used exact, match-constrained identity evidence from average positions and reviewed lineups; it did not use unconstrained fuzzy matching.

The repair:

- Added 133 `playermatchstats.csv` rows and 133 `player_match_enrichment.csv` rows, removing none.
- Restored rows in GW16, GW17, and GW25-GW38; GW29 received 19 player-match rows and 19 enrichment rows.
- Corrected 2,845 stale match-level minute values and 251 assist values on rows already present in the review branch.
- Filled 91 `xg`, three `xa`, 119 `xgot`, 91 `penalties_scored`, and 91 `penalties_missed` blanks on existing rows where safe evidence was available.
- Corrected 93 stale `player_stats_processed` flags, leaving all 380 Premier League matches marked as processed.

These current-repair changes affected 3,491 existing player-match cells. The final 11,361 positive FPL player-gameweeks now reconcile exactly to 748,552 minutes, 1,005 goals, and 942 assists. All 11,461 positive player-stat rows supplied by the detailed stream resolve to repository/FPL player IDs.

“Existing value replaced” does not automatically mean that the earlier value was a large error. Many xA and xGOT differences are additional decimal precision. It means the nonblank value did not numerically equal the selected authoritative value.

## Percentage recalculation

There are seven technical percentage columns, not tens of thousands of separate columns.

The current audit covers 53,761 player-match **cells** with a valid numerator and a non-zero denominator.

The formulas are:

| Stored column | Formula |
|---|---|
| `accurate_passes_percent` | `accurate_passes / total_passes * 100` |
| `accurate_crosses_percent` | `accurate_crosses / total_crosses * 100` |
| `accurate_long_balls_percent` | `accurate_long_balls / total_long_balls * 100` |
| `successful_dribbles_percent` | `successful_dribbles / total_dribbles * 100` |
| `tackles_won_percent` | `tackles_won / tackles * 100` |
| `ground_duels_won_percent` | `ground_duels_won / (ground_duels_won + ground_duels_lost) * 100` |
| `aerial_duels_won_percent` | `aerial_duels_won / (aerial_duels_won + aerial_duels_lost) * 100` |

Percentages use consistent whole-number, half-up rounding. For example:

```text
35 accurate passes / 40 total passes = 87.5% -> 88
```

The validation process:

1. Took the accepted numerator and denominator from the same detailed player-match record.
2. Recomputed the expected percentage.
3. Repaired a stored value where it did not equal the expected result.
4. Exact-checked all 53,761 eligible non-zero-denominator cells.
5. Separately checked 26,466 mapped zero-denominator cases and retained them as zero.

This does not mean all 53,761 values changed. It means all 53,761 were independently calculated and checked.

## Player identity integration

The new detail tables use the repository/FPL `player_id` wherever a safe identity link exists. This is separate from FPL player availability and does not replace the availability fields.

Final identity reconciliation filled 1,067 previously missing player-ID cells:

| Table/role | IDs filled |
|---|---:|
| Lineups | 493 |
| Shots | 142 |
| Average positions | 178 |
| Incident primary player | 156 |
| Incident secondary/substitution player | 94 |
| Incident assist player | 4 |
| **Total** | **1,067** |

Identity rules used:

- Exact repository/FPL IDs where already available.
- Reviewed source-ID crosswalks.
- Reviewed team-constrained player-name aliases.
- Same-match lineup and substitution evidence.
- No unconstrained fuzzy player matching.

All 11,461 positive player-stat records supplied by the detailed stream now resolve. No actionable positive identity remains unresolved, and unsafe identities were not forced into the output.

Final identity state:

- All shot player IDs are populated.
- All lineup player IDs are populated.
- All average-position player IDs are populated.
- All actionable incident player roles are populated.
- Canonical incidents contain no `Unknown` actor placeholders. The 48 unsafe rows remain inspectable only in the supplemental quarantine, and six safely identified cards retain a blank minute.

## Minute reconciliation and quarantine

FPL minutes remain authoritative.

Detailed player rows were accepted when:

- The match and player identity were safely linked.
- Minute totals matched exactly; or
- A mismatch was supported by same-match lineup/substitution evidence.

Validation totals:

| Result | Rows |
|---|---:|
| Positive FPL player-gameweeks | 11,361 |
| Positive FPL player-match appearances | 11,492 |
| Player-gameweeks exactly reconciled for minutes/goals/assists | 11,361 |
| Accepted for enrichment | 11,461 |
| Quarantined | 31 |

FPL remains authoritative for minutes, goals, and assists. The detailed stream supplies match identity and technical statistics; FPL totals are reconciled at player-gameweek level and, in double gameweeks, against match-grain FPL records.

The 31 quarantined records have zero or blank detailed-stream minutes and all-zero placeholder statistics despite a positive FPL appearance. Their FPL-owned fields are present and reconciled in `playermatchstats.csv`, but the placeholders are not used to manufacture detailed enrichment.

## Unsupported columns removed

Columns that were unavailable, unsupported, or outside the agreed analytical scope were removed rather than left permanently empty.

### Removed from `fixtures.csv` and `matches.csv`

```text
home_distance_covered
away_distance_covered
home_walking_distance
away_walking_distance
home_running_distance
away_running_distance
home_sprinting_distance
away_sprinting_distance
home_number_of_sprints
away_number_of_sprints
home_top_speed
away_top_speed
```

These columns are absent from both tournament-specific and combined-gameweek match schemas. The final audit confirmed they had no value in any of the 525 combined-gameweek match rows.

### Removed from `playermatchstats.csv`

```text
corners
top_speed
distance_covered
walking_distance
running_distance
sprinting_distance
number_of_sprints
```

### Removed from `match_enrichment.csv`

```text
attendance
lineup_confidence
```

### Removed from `player_match_enrichment.csv`

```text
penalties_won
penalties_conceded
penalties_faced
penalties_saved
```

### Removed from `lineups.csv`

```text
confidence
```

After this cleanup, `playermatchstats.csv` has 57 retained columns and no wholly empty column. Partially blank fields and their reasons are documented below.

## Data deliberately not integrated

The following data was reviewed but deliberately left out of the 2025/26 integration dataset:

- New betting and historical-odds integration.
- TV-channel information.
- League standings.
- Attendance.
- Historical physical-tracking fields.
- Source/API provenance columns such as `data_source`, `source_event_id`, `source_player_id`, and `retrieved_at`.
- API keys or credentials.
- Raw API responses.
- Capture, ingestion, or transformation scripts.
- Supabase migrations or production pipeline changes.

The branch therefore demonstrates the final merged data shape without committing the private collection mechanism or changing production infrastructure.

Repository-scope qualifications:

- An existing, unrelated `data/2026-2027/By Tournament/Friendlies/GW0/odds.csv` file remains from the main repository. It contains 354 rows across 16 friendlies and was not added by this integration.
- Existing external availability remains isolated in `data/2026-2027/supplemental/player_availability_external.csv`; it was not blended into FPL availability.

## Completeness and known limitations

### Expected blanks

Some blank cells are structurally correct:

- `shots.added_time` is blank outside stoppage time.
- `shots.xgot` is blank where a post-shot on-target model is inapplicable and for 106 saved shots where it was unavailable.
- Incident player, assist, score, card, and goal fields are populated only for event types that use them.
- Period and injury-time markers do not have player IDs.
- Six named card events have a blank minute because their source minute was invalid.
- The 189 limited-timing matches correctly have no fabricated period, injury-time, VAR, added-time, or descriptive-text rows.

### Remaining Premier League gaps

| Area | Remaining gap |
|---|---|
| Player enrichment rating | 227 of 11,462 rows blank |
| Average-position jersey number | 250 of 11,448 rows blank |
| `playermatchstats.xg` | 0 of 12,754 rows blank |
| `playermatchstats.xa` | 0 of 12,754 rows blank |
| `playermatchstats.xgot` | 1 of 12,754 rows blank |
| Penalty fields | 0 of 12,754 rows blank |
| Incident timing | 189 matches have limited incident types |
| Named card timing | 6 mapped cards have no reliable minute |
| Unknown card actors | 48 invalid placeholders excluded from canonical incidents and retained in quarantine |
| Match versus shot-model xG | Separate measures; 173 of 760 sides differ by more than 0.08 |
| Detailed versus summary shot count | 2 of 760 team-match sides disagree |
| Match weather/travel/pitch context | Available for only 36-48 of 380 matches, depending on field |

The 293 `playermatchstats.csv` rows added relative to main do not have values for 18 legacy FPL-owned columns that the detailed stream cannot safely supply. These cells remain blank rather than being manufactured.

The single remaining `xgot` blank is Pascal Gross in GW33: he recorded one shot on target, but no reliable post-shot xG value was available.

One `player_match_enrichment.csv` record is intentionally not represented in `playermatchstats.csv`: it is a zero-minute, booking-only bench record. The other 11,461 enrichment keys join to player-match statistics.

### Non-Premier-League limitations

- Detailed coverage is partial for the Champions League, EFL Cup, and Europa League.
- No new detailed event tables exist for the Conference League.
- The strict authority, identity, and quality guarantees in this document apply to the Premier League only.
- A pre-existing Conference League defect remains out of scope: AEK Larnaca-Crystal Palace appears in canonical `matches.csv` under both GW8 and GW30 with the same `match_id` but conflicting scores and event IDs. Consequently the 526 all-competition match rows contain 525 unique match IDs. The detailed shots, incidents, timelines, and enrichment tables themselves have no duplicate canonical keys.

## Validation results

The current CSVs passed a local read-only data audit. The audit helper was deliberately not committed because this is a data-only review branch.

| Validation | Result |
|---|---|
| Premier League matches / unique match IDs | 380 / 380 |
| Premier League `matches.csv` versus `fixtures.csv` mismatches | 0 |
| Premier League kickoff-map matches | 380/380 |
| Nonblank 2025/26 kickoff cells with explicit UTC | 1,942/1,942 |
| Tournament/combined-gameweek PL projection mismatches | 0 |
| PL shots / unique keys | 9,504 / 9,504 |
| PL incidents / unique keys | 6,455 / 6,455 |
| Canonical negative incident minutes | 0 |
| Quarantined invalid incident rows | 48 |
| Retained named cards with unknown minute | 6 |
| PL xG-minute rows / unique keys | 7,651 / 7,651 |
| Shot-minute versus timeline key mismatches | 0 |
| Maximum timeline-versus-shot rounding error | 0.0005 |
| Cumulative xG decreases | 0 |
| Match-enrichment shot totals matching cleaned shots | 760/760 team sides |
| Incident coverage flags | 191 `available`; 189 `limited` |
| Own-goal incidents preserved | 42 |
| Duplicate own-goal pseudo-shots removed | 40 |
| Genuine initiating attempts retained as `ownGoal` | 2 |
| Detailed versus summary shot-count agreement | 758/760 team sides |
| Current Premier League player-match rows | 12,754 |
| Current Premier League enrichment rows | 11,462 |
| FPL-positive player-gameweeks reconciled | 11,361/11,361 (100%) |
| Processed Premier League matches | 380/380 |
| Eligible raw-formula percentage cells | 53,761 |
| Exact raw-formula matches | 53,761 |
| Zero-denominator cases checked separately | 26,466 |
| Accepted positive-minute enrichment coverage | 11,461/11,492 (99.73%) |
| Actionable unresolved identities | 0 |
| Remaining technical percentage formula conflicts | 0 |

Validation also confirmed:

- FPL remains authoritative for minutes, goals, assists, and the other protected FPL-owned fields; repaired match rows aggregate exactly to the FPL player-gameweek totals.
- Every canonical event-detail key in shots, incidents, xG timelines, and match enrichment is unique across all included competitions.
- The tournament-specific Premier League rows and their combined-gameweek projections agree in schema and value.
- Quarantined incident placeholders are not used in canonical totals, timelines, or enrichment.
- All 42 own-goal incidents remain available even though duplicate shot representations were removed.
- No unsupported physical-tracking columns remain in the match schemas.

This audit verifies the current data invariants; it is not a byte-for-byte inventory of every unrelated repository file.

## Reviewer guidance

Reviewers should concentrate on:

1. Whether the source-authority split is appropriate:
   - FPL for FPL-owned gameplay and availability fields.
   - Detailed match records for the named technical fields and their denominators.
2. Which explicitly named xG universe each downstream feature should use; summary xG and shot-model xG must not be silently mixed.
3. Whether `limited` incident coverage for GW13-GW31 is acceptable for the intended analyses.
4. Whether quarantining the 48 invalid `Unknown` cards, while retaining six named cards without a minute, is the right policy.
5. Whether the two residual detailed-versus-summary shot-count differences require upstream investigation.
6. Whether the new event tables should be adopted as separate production tables.
7. Whether the 293 source-added player-match rows should be retained in production.
8. Whether partial non-Premier-League coverage should be published or held back until complete.
9. Whether average positions and momentum are useful downstream features.
10. Whether the sparse weather/travel fields are useful enough to retain.

## Production work not included

This review branch does not itself put the integration into production.

If the data is approved, a separate implementation would still need:

1. A secure scheduled ingestion mechanism.
2. Source-to-FPL identity tables outside the public CSV output.
3. Supabase table or view decisions for shots, incidents, lineups, xG timelines, momentum, average positions, and quarantine.
4. Idempotent upsert keys and database constraints.
5. Monitoring for match coverage and unresolved identities.
6. Regression checks for placeholder/stale kickoffs, timezone consistency, incident schema degradation, negative minutes, own-goal duplication, and projection parity.
7. Explicit namespacing for summary xG versus shot-model xG.
8. A decision on how incomplete non-Premier-League competitions should be exposed.

No capture script, transformation helper, credential, migration, or production pipeline change is committed on this review branch.
