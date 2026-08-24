"""
FPL-Core-Insights — Update Pipeline
============================================
Volgorde:
  1. Sofascore gespeelde wedstrijden bijwerken
  2. Cleaning data (combineren + timestamp fix + filteren)
  3. Lineup strength berekenen (rating-gebaseerd + log marktwaarde)
     → match_data.csv bijgewerkt met beide varianten
     → player_strength.csv apart opgeslagen
  4. Aankomende wedstrijden + verwachte lineups
     → gebruikt schone player_data uit stap 2
  5. Understat xG bijwerken

Wijzigingen tov vorige versie:
  - ClubElo verwijderd
  - Polymarket verwijderd
  - Twee lineup strength varianten:
      home/away_lineup_strength_rating  (rolling sofascore rating)
      home/away_lineup_strength_mv      (log gemiddelde marktwaarde)
  - match_data bevat alleen kernkolommen + lineup strength
  - team_strength.csv verwijderd (zit nu in match_data)
  - Pi-ratings worden berekend door kalman_updater_with_pi.py
  - Fallback voor lineup strength rating is nu causaal:
      expanding mean per positie gesorteerd op tijd (geen data leakage)
"""

import os, csv, time, math, glob, requests
import numpy as np
import pandas as pd
from io import StringIO

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATIE
# ══════════════════════════════════════════════════════════════════════════════

# ── Paden ─────────────────────────────────────────────────────────────────────
OLD_DATA_DIR  = r"C:\Users\semwi\FPL-Core-Insights_Thesis\data"
SEASONAL_DIR  = os.path.join(OLD_DATA_DIR, "Seasonal data")
MATCHES_DIR   = os.path.join(SEASONAL_DIR, "matches")
PLAYERS_DIR   = os.path.join(SEASONAL_DIR, "players")

RAW_2526      = os.path.join(MATCHES_DIR, "2025-2026_raw.csv")
PLAYERS_2526  = os.path.join(PLAYERS_DIR, "2025-2026_players.csv")

# Output bestanden
DATA_DIR      = r"C:\Users\semwi\FPL-Core-Insights_Thesis\data"
os.makedirs(DATA_DIR, exist_ok=True)

MATCH_DATA_PATH  = os.path.join(DATA_DIR, "match_data.csv")
PLAYER_DATA_PATH = os.path.join(DATA_DIR, "player_data.csv")
PLAYER_STR_PATH  = os.path.join(DATA_DIR, "player_strength.csv")
UNDERSTAT_XG_PATH= os.path.join(DATA_DIR, "understat_xg.csv")

API_KEY    = "2b277abcd2msh0e5627048810020p119057jsn4412b05235c9"
SEASON_ID  = 76986
TOURNAMENT = 17
SEASON_STR = "2025-2026"
DELAY      = 0.3
RETRIES    = 3

HEADERS = {
    "x-rapidapi-key":  API_KEY,
    "x-rapidapi-host": "sofascore.p.rapidapi.com"
}

# Kernkolommen voor match_data
MATCH_CORE_COLS = [
    "match_id", "season", "round", "timestamp", "status",
    "home_team", "away_team", "home_team_id", "away_team_id",
    "home_goals", "away_goals",
    "home_lineup_strength_rating", "away_lineup_strength_rating",
    "home_lineup_strength_mv",     "away_lineup_strength_mv",
]

PLAYER_COLS_FIXED = [
    "match_id","season","home_team","away_team","home_goals","away_goals",
    "round","timestamp","side","formation","player_id","player_name","short_name",
    "position","shirt_number","substitute","captain","nationality","height",
    "market_value","rating","minutes_played","touches","total_pass","accurate_pass",
    "total_long_balls","accurate_long_balls","total_cross","accurate_cross","key_pass",
    "total_shots","on_target","shot_off_target","blocked_shot","goals","goal_assist",
    "big_chance_created","big_chance_missed","hit_woodwork","duel_won","duel_lost",
    "aerial_won","aerial_lost","total_tackle","won_tackle","interception_won",
    "total_clearance","outfielder_block","total_contest","won_contest","dispossessed",
    "possession_lost","unsuccessful_touch","ball_recovery","was_fouled","fouls",
    "total_offside","penalty_won","penalty_conceded","penalty_miss","error_led_to_goal",
    "saves","saves_inside_box","penalty_save","punches","acc_own_half_pass","acc_opp_half_pass"
]

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def api_get(url: str) -> dict | None:
    for attempt in range(RETRIES):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            data = resp.json()
            if "message" in data:
                print(f"\n  ⛔ QUOTA OP: {data['message']}")
                return None
            return data
        except Exception as e:
            wait = 2 ** attempt
            print(f"  ⏳ Fout ({e}), wacht {wait}s...", end=" ", flush=True)
            time.sleep(wait)
    return None


def load_csv_status(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    result = {}
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            mid = row.get("match_id", "")
            if mid:
                # Fallback: als geen status kolom (oud formaat), beschouw als finished
                result[mid] = row.get("status", "finished") or "finished"
    return result


def load_columns(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return next(csv.reader(f))


# ══════════════════════════════════════════════════════════════════════════════
# STAP 1 – Sofascore gespeelde wedstrijden
# ══════════════════════════════════════════════════════════════════════════════

def fetch_match_details(event_id: int) -> tuple[dict, list]:
    """Haal match details op — alleen kernkolommen, geen ingame stats."""
    data = api_get(f"https://sofascore.p.rapidapi.com/matches/detail?matchId={event_id}")
    time.sleep(DELAY)
    ed = data.get("event", {}) if data else {}

    match_row = {
        "match_id":     event_id,
        "season":       SEASON_STR,
        "round":        ed.get("roundInfo", {}).get("round"),
        "timestamp":    ed.get("startTimestamp"),
        "status":       ed.get("status", {}).get("description"),
        "home_team":    ed.get("homeTeam", {}).get("name"),
        "away_team":    ed.get("awayTeam", {}).get("name"),
        "home_team_id": ed.get("homeTeam", {}).get("id"),
        "away_team_id": ed.get("awayTeam", {}).get("id"),
        "home_goals":   ed.get("homeScore", {}).get("current"),
        "away_goals":   ed.get("awayScore", {}).get("current"),
        "home_lineup_strength_rating": None,
        "away_lineup_strength_rating": None,
        "home_lineup_strength_mv":     None,
        "away_lineup_strength_mv":     None,
    }

    # Lineups ophalen
    data = api_get(f"https://sofascore.p.rapidapi.com/matches/get-lineups?matchId={event_id}")
    time.sleep(DELAY)
    lineups_raw = data if data else {}
    home_formation = lineups_raw.get("home", {}).get("formation")
    away_formation = lineups_raw.get("away", {}).get("formation")

    lineup_rows = []
    for side in ["home", "away"]:
        formation = home_formation if side == "home" else away_formation
        for p in lineups_raw.get(side, {}).get("players", []):
            player = p.get("player", {})
            stats  = p.get("statistics", {})
            lineup_rows.append({
                "match_id":    event_id,
                "season":      SEASON_STR,
                "home_team":   ed.get("homeTeam", {}).get("name"),
                "away_team":   ed.get("awayTeam", {}).get("name"),
                "home_goals":  ed.get("homeScore", {}).get("current"),
                "away_goals":  ed.get("awayScore", {}).get("current"),
                "round":       ed.get("roundInfo", {}).get("round"),
                "timestamp":   ed.get("startTimestamp"),
                "side":        side,
                "formation":   formation,
                "player_id":   player.get("id"),
                "player_name": player.get("name"),
                "short_name":  player.get("shortName"),
                "position":    p.get("position"),
                "shirt_number":p.get("shirtNumber"),
                "substitute":  p.get("substitute"),
                "captain":     p.get("captain"),
                "nationality": player.get("country", {}).get("name"),
                "height":      player.get("height"),
                "market_value":player.get("proposedMarketValueRaw", {}).get("value")
                               if player.get("proposedMarketValueRaw") else None,
                "rating":          stats.get("rating"),
                "minutes_played":  stats.get("minutesPlayed"),
                "touches":         stats.get("touches"),
                "total_pass":      stats.get("totalPass"),
                "accurate_pass":   stats.get("accuratePass"),
                "total_long_balls":stats.get("totalLongBalls"),
                "accurate_long_balls":stats.get("accurateLongBalls"),
                "total_cross":     stats.get("totalCross"),
                "accurate_cross":  stats.get("accurateCross"),
                "key_pass":        stats.get("keyPass"),
                "total_shots":     stats.get("totalShots"),
                "on_target":       stats.get("onTargetScoringAttempt"),
                "shot_off_target": stats.get("shotOffTarget"),
                "blocked_shot":    stats.get("blockedScoringAttempt"),
                "goals":           stats.get("goals"),
                "goal_assist":     stats.get("goalAssist"),
                "big_chance_created": stats.get("bigChanceCreated"),
                "big_chance_missed":  stats.get("bigChanceMissed"),
                "hit_woodwork":    stats.get("hitWoodwork"),
                "duel_won":        stats.get("duelWon"),
                "duel_lost":       stats.get("duelLost"),
                "aerial_won":      stats.get("aerialWon"),
                "aerial_lost":     stats.get("aerialLost"),
                "total_tackle":    stats.get("totalTackle"),
                "won_tackle":      stats.get("wonTackle"),
                "interception_won":stats.get("interceptionWon"),
                "total_clearance": stats.get("totalClearance"),
                "outfielder_block":stats.get("outfielderBlock"),
                "total_contest":   stats.get("totalContest"),
                "won_contest":     stats.get("wonContest"),
                "dispossessed":    stats.get("dispossessed"),
                "possession_lost": stats.get("possessionLostCtrl"),
                "unsuccessful_touch":stats.get("unsuccessfulTouch"),
                "ball_recovery":   stats.get("ballRecovery"),
                "was_fouled":      stats.get("wasFouled"),
                "fouls":           stats.get("fouls"),
                "total_offside":   stats.get("totalOffside"),
                "penalty_won":     stats.get("penaltyWon"),
                "penalty_conceded":stats.get("penaltyConceded"),
                "penalty_miss":    stats.get("penaltyMiss"),
                "error_led_to_goal":stats.get("errorLeadToGoal"),
                "saves":           stats.get("saves"),
                "saves_inside_box":stats.get("savedShotsFromInsideTheBox"),
                "penalty_save":    stats.get("penaltySave"),
                "punches":         stats.get("punches"),
                "acc_own_half_pass":stats.get("accurateOwnHalfPasses"),
                "acc_opp_half_pass":stats.get("accurateOppositionHalfPasses"),
            })

    return match_row, lineup_rows


def overwrite_match_row(match_row: dict, path: str):
    df = pd.read_csv(path, low_memory=False)
    mid = str(match_row["match_id"])
    df["match_id"] = df["match_id"].astype(str)
    for k in match_row:
        if k not in df.columns:
            df[k] = None
    mask = df["match_id"] == mid
    for k, v in match_row.items():
        if k in df.columns:
            df.loc[mask, k] = v
    df.to_csv(path, index=False)


def overwrite_player_rows(lineup_rows: list, path: str, match_id: int):
    df = pd.read_csv(path, low_memory=False)
    df["match_id"] = df["match_id"].astype(str)
    mid = str(match_id)
    df = df[~((df["match_id"] == mid) & (df["substitute"].astype(str) == "expected"))]
    df = df[df["match_id"] != mid]
    df.to_csv(path, index=False)
    if lineup_rows:
        with open(path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=PLAYER_COLS_FIXED, extrasaction="ignore")
            writer.writerows(lineup_rows)


def append_match_row(match_row: dict, path: str):
    file_exists = os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MATCH_CORE_COLS, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerow(match_row)


def append_player_rows(lineup_rows: list, path: str):
    if not lineup_rows:
        return
    file_exists = os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=PLAYER_COLS_FIXED, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerows(lineup_rows)


def stap1_sofascore():
    print("\n══════════════════════════════════════════")
    print("  STAP 1 – Sofascore gespeelde wedstrijden")
    print("══════════════════════════════════════════")

    id_to_status = load_csv_status(RAW_2526)
    print(f"   📂 Bekende wedstrijden: {len(id_to_status)}")

    all_events = []
    page = 0
    while True:
        url = (f"https://sofascore.p.rapidapi.com/tournaments/get-matches"
               f"?tournamentId={TOURNAMENT}&seasonId={SEASON_ID}&pageIndex={page}")
        data = api_get(url)
        if not data:
            break
        events = data.get("events", [])
        if not events:
            break
        for e in events:
            all_events.append({
                "event_id": e["id"],
                "round":    e.get("roundInfo", {}).get("round"),
                "status":   e.get("status", {}).get("description", ""),
            })
        page += 1
        time.sleep(DELAY)

    print(f"   📊 Sofascore geeft {len(all_events)} wedstrijden")

    to_process = []
    for e in all_events:
        mid    = str(e["event_id"])
        status = id_to_status.get(mid, "nieuw")
        if status == "nieuw":
            e["action"] = "append"
            to_process.append(e)
        elif status in ("Not started", "upcoming"):
            e["action"] = "overwrite"
            to_process.append(e)

    print(f"   🆕 Nieuw: {sum(1 for e in to_process if e['action']=='append')} | "
          f"🔄 Overschrijven: {sum(1 for e in to_process if e['action']=='overwrite')}")

    if not to_process:
        print("   ✅ Alles al up-to-date!")
        return

    for i, event in enumerate(to_process, 1):
        event_id = event["event_id"]
        rnd      = event["round"]
        action   = event["action"]
        symbol   = "➕" if action == "append" else "🔄"
        print(f"   [{i:02d}/{len(to_process)}] {symbol} GW{rnd} – {event_id}...", end=" ", flush=True)

        match_row, lineup_rows = fetch_match_details(event_id)
        home = match_row.get("home_team", "?")
        away = match_row.get("away_team", "?")
        hg   = match_row.get("home_goals", "?")
        ag   = match_row.get("away_goals", "?")

        if action == "overwrite":
            overwrite_match_row(match_row, RAW_2526)
            overwrite_player_rows(lineup_rows, PLAYERS_2526, event_id)
        else:
            append_match_row(match_row, RAW_2526)
            append_player_rows(lineup_rows, PLAYERS_2526)

        print(f"✅ {home} {hg}-{ag} {away} | {len(lineup_rows)} spelers")

    print("   ✅ Stap 1 klaar!")


# ══════════════════════════════════════════════════════════════════════════════
# STAP 2 – Cleaning data
# ══════════════════════════════════════════════════════════════════════════════

def stap2_cleaning():
    print("\n══════════════════════════════════════════")
    print("  STAP 2 – Cleaning data")
    print("══════════════════════════════════════════")

    def read_safe(file):
        try:
            return pd.read_csv(file, low_memory=False)
        except Exception:
            with open(file, encoding="utf-8") as f:
                rows = list(csv.reader(f))
            header = rows[0]
            n = len(header)
            fixed = [(r + [None] * (n - len(r)))[:n] for r in rows[1:]]
            return pd.DataFrame(fixed, columns=header)

    match_files  = sorted(glob.glob(os.path.join(MATCHES_DIR, "*_raw.csv")))
    player_files = sorted(glob.glob(os.path.join(PLAYERS_DIR, "*_players.csv")))

    matches = pd.concat([read_safe(f) for f in match_files],
                        ignore_index=True, sort=False)
    players = pd.concat([pd.read_csv(f, low_memory=False) for f in player_files],
                        ignore_index=True, sort=False)

    # Timestamp fix — unix naar datetime string
    def fix_ts(ts):
        try:
            v = pd.to_numeric(ts, errors="raise")
            return pd.to_datetime(v, unit="s").strftime("%Y-%m-%d %H:%M")
        except Exception:
            return ts

    matches["timestamp"] = matches["timestamp"].apply(fix_ts)

    # Timestamp synchroniseren naar player_data
    ts_map = matches[["match_id", "timestamp"]].drop_duplicates("match_id")
    ts_map["match_id"] = ts_map["match_id"].astype(str)
    players["match_id"] = players["match_id"].astype(str)
    players = players.drop(columns=["timestamp"], errors="ignore")
    players = players.merge(ts_map, on="match_id", how="left")
    cols = list(players.columns)
    cols.remove("timestamp")
    cols.insert(cols.index("round") + 1, "timestamp")
    players = players[cols]

    # Filteren op relevante statussen
    matches = (matches
               .dropna(subset=["match_id"])
               .pipe(lambda d: d[d["status"].isin(["finished", "Ended", "Not started"])])
               .sort_values("timestamp")
               .reset_index(drop=True))

    # Dedup: Ended/finished wint van Not started
    matches["_sort"] = matches["status"].map(
        {"finished": 0, "Ended": 0, "Not started": 1}).fillna(1)
    matches = (matches
               .sort_values(["match_id", "_sort"])
               .drop_duplicates(subset=["match_id"], keep="first")
               .drop(columns=["_sort"])
               .reset_index(drop=True))

    # Extra dedup op teams + tijdstip
    matches = (matches
               .sort_values(["home_team", "away_team", "timestamp"])
               .drop_duplicates(subset=["home_team", "away_team", "timestamp"], keep="first")
               .sort_values("timestamp")
               .reset_index(drop=True))

    for c in MATCH_CORE_COLS:
        if c not in matches.columns:
            matches[c] = None
    matches = matches[MATCH_CORE_COLS]

    players = (players
               .sort_values("timestamp")
               .drop_duplicates(subset=["match_id", "player_id", "side"], keep="last")
               .reset_index(drop=True))

    matches.to_csv(MATCH_DATA_PATH, index=False)
    players.to_csv(PLAYER_DATA_PATH, index=False)
    print(f"   ✅ match_data:  {len(matches):,} rijen")
    print(f"   ✅ player_data: {len(players):,} rijen")


# ══════════════════════════════════════════════════════════════════════════════
# STAP 3 – Lineup strength (rating + log marktwaarde)
# ══════════════════════════════════════════════════════════════════════════════

def stap3_strength():
    print("\n══════════════════════════════════════════")
    print("  STAP 3 – Lineup strength berekenen")
    print("  Variant A: rolling sofascore rating")
    print("  Variant B: log gemiddelde marktwaarde")
    print("══════════════════════════════════════════")

    players = pd.read_csv(PLAYER_DATA_PATH, low_memory=False)
    matches = pd.read_csv(MATCH_DATA_PATH)
    matches["match_id"] = matches["match_id"].astype(str)
    players["match_id"] = players["match_id"].astype(str)

    # Timestamp numeriek voor sorteren
    players["timestamp_unix"] = pd.to_datetime(
        players["timestamp"], format="mixed", errors="coerce"
    ).astype("int64") // 10 ** 9

    # Alleen starters
    starters = players[
        players["substitute"].astype(str).str.lower().isin(["false", "expected"])
    ].copy()

    starters["rating"]       = pd.to_numeric(starters["rating"],       errors="coerce")
    starters["market_value"] = pd.to_numeric(starters["market_value"], errors="coerce")

    # ── Variant A: Rolling rating ─────────────────────────────────────────────
    # Per speler: expanding mean van alle VORIGE wedstrijden (shift 1)
    # → strikt causaal: rating van huidige wedstrijd telt nooit mee
    # Voorbeeld: speelronde 6 krijgt het gemiddelde van rondes 1 t/m 5
    starters = starters.sort_values(["player_id", "timestamp_unix"])
    starters["rating_rolling"] = (
        starters.groupby("player_id")["rating"]
        .transform(lambda x: x.expanding().mean().shift(1))
    )

    # Fallback voor spelers zonder historie (bijv. ronde 1):
    # Causaal gemiddelde van alle spelers op dezelfde positie tot dat moment,
    # gesorteerd op tijd. Voorkomt data leakage — het speler-eigen seizoens-
    # gemiddelde zou anders ook toekomstige wedstrijden bevatten.
    starters = starters.sort_values("timestamp_unix")
    starters["rating_pos_fallback"] = (
        starters.groupby("position")["rating"]
        .transform(lambda x: x.expanding().mean().shift(1))
    )

    # Gebruik speler-eigen rolling indien beschikbaar, anders positie-fallback
    starters["rating_best"] = starters["rating_rolling"].fillna(
        starters["rating_pos_fallback"]
    )

    n_rolling  = starters["rating_rolling"].notna().sum()
    n_fallback = starters["rating_best"].notna().sum() - n_rolling
    print(f"   📊 Rating rolling: {n_rolling:,} | positie-fallback: {n_fallback:,}")

    # ── Variant B: Log marktwaarde ────────────────────────────────────────────
    starters["log_mv"] = np.where(
        starters["market_value"] > 0,
        np.log(starters["market_value"]),
        np.nan
    )

    # ── Aggregeer naar team niveau per wedstrijd ──────────────────────────────
    def lineup_strength(df, val_col, suffix):
        """Bereken home/away lineup strength voor één variant."""
        agg = (
            df[df[val_col].notna()]
            .groupby(["match_id", "side"])[val_col]
            .mean()
            .reset_index()
            .rename(columns={val_col: "strength"})
        )
        home = (agg[agg["side"] == "home"][["match_id", "strength"]]
                .rename(columns={"strength": f"home_lineup_strength_{suffix}"}))
        away = (agg[agg["side"] == "away"][["match_id", "strength"]]
                .rename(columns={"strength": f"away_lineup_strength_{suffix}"}))
        return home, away

    home_r, away_r = lineup_strength(starters, "rating_best", "rating")
    home_m, away_m = lineup_strength(starters, "log_mv",      "mv")

    # ── Toevoegen aan match_data ──────────────────────────────────────────────
    for col in ["home_lineup_strength_rating", "away_lineup_strength_rating",
                "home_lineup_strength_mv",     "away_lineup_strength_mv"]:
        if col in matches.columns:
            matches = matches.drop(columns=[col])

    matches = matches.merge(home_r, on="match_id", how="left")
    matches = matches.merge(away_r, on="match_id", how="left")
    matches = matches.merge(home_m, on="match_id", how="left")
    matches = matches.merge(away_m, on="match_id", how="left")
    matches = matches[MATCH_CORE_COLS]
    matches.to_csv(MATCH_DATA_PATH, index=False)

    n_rating = matches["home_lineup_strength_rating"].notna().sum()
    n_mv     = matches["home_lineup_strength_mv"].notna().sum()
    print(f"   ✅ Lineup strength rating: {n_rating:,} wedstrijden")
    print(f"   ✅ Lineup strength mv:     {n_mv:,} wedstrijden")
    print(f"   💾 match_data bijgewerkt: {len(matches):,} rijen")

    # ── Player strength overzicht (apart bestand) ─────────────────────────────
    print("   📋 player_strength.csv bouwen...")
    ts_lookup = matches.set_index("match_id")["timestamp"].to_dict()
    rows = []
    for match_id, group in starters.groupby("match_id"):
        mid        = str(match_id)
        match_info = matches[matches["match_id"] == mid]
        if match_info.empty:
            continue
        m = match_info.iloc[0]
        row = {
            "match_id":  mid,
            "season":    m.get("season", ""),
            "round":     m.get("round", ""),
            "timestamp": ts_lookup.get(mid, ""),
            "status":    m.get("status", ""),
            "home_team": m.get("home_team", ""),
            "away_team": m.get("away_team", ""),
        }
        for side in ["home", "away"]:
            side_group = group[group["side"] == side].sort_values("position")
            avg_r = side_group["rating_best"].mean()
            avg_m = side_group["log_mv"].mean()
            row[f"{side}_lineup_strength_rating"] = round(avg_r, 4) if pd.notna(avg_r) else None
            row[f"{side}_lineup_strength_mv"]     = round(avg_m, 4) if pd.notna(avg_m) else None
            for pos in ["G", "D", "M", "F"]:
                pos_players = side_group[side_group["position"] == pos].reset_index(drop=True)
                for i, (_, p) in enumerate(pos_players.iterrows(), 1):
                    name   = p.get("short_name") or p.get("player_name", "")
                    rating = round(p["rating_best"], 2) if pd.notna(p.get("rating_best")) else None
                    mv     = round(p["log_mv"], 3)      if pd.notna(p.get("log_mv"))      else None
                    row[f"{side}_{pos}{i}_name"]   = name
                    row[f"{side}_{pos}{i}_rating"] = rating
                    row[f"{side}_{pos}{i}_log_mv"] = mv
        rows.append(row)

    overview = pd.DataFrame(rows)
    info_cols = ["match_id", "season", "round", "timestamp", "status",
                 "home_team", "away_team",
                 "home_lineup_strength_rating", "away_lineup_strength_rating",
                 "home_lineup_strength_mv",     "away_lineup_strength_mv"]
    home_cols = sorted([c for c in overview.columns if c.startswith("home_") and c not in info_cols])
    away_cols = sorted([c for c in overview.columns if c.startswith("away_") and c not in info_cols])
    overview  = overview[info_cols + home_cols + away_cols]
    overview.sort_values("timestamp").reset_index(drop=True).to_csv(PLAYER_STR_PATH, index=False)
    print(f"   ✅ player_strength: {len(overview):,} wedstrijden → {PLAYER_STR_PATH}")


# ══════════════════════════════════════════════════════════════════════════════
# STAP 4 – Aankomende wedstrijden + verwachte lineups
# ══════════════════════════════════════════════════════════════════════════════

def get_last_lineup(players_df: pd.DataFrame, team: str) -> pd.DataFrame:
    """Haal de laatste bekende opstelling op voor een team."""
    mask = (players_df["home_team"] == team) | (players_df["away_team"] == team)
    rows = players_df[mask].copy()
    rows["_team_side"] = rows.apply(
        lambda r: "home" if r["home_team"] == team else "away", axis=1)
    rows = rows[rows["side"] == rows["_team_side"]]
    rows = rows[rows["substitute"].astype(str).str.lower() == "false"]
    if rows.empty:
        return pd.DataFrame()
    last_id = rows.sort_values("timestamp").iloc[-1]["match_id"]
    return rows[rows["match_id"] == last_id].copy()


def stap4_upcoming():
    print("\n══════════════════════════════════════════")
    print("  STAP 4 – Aankomende wedstrijden + lineups")
    print("══════════════════════════════════════════")

    id_to_status = load_csv_status(RAW_2526)
    players_df   = pd.read_csv(PLAYER_DATA_PATH, low_memory=False)

    all_upcoming = []
    for page in range(5):
        url = (f"https://sofascore.p.rapidapi.com/tournaments/get-next-matches"
               f"?tournamentId={TOURNAMENT}&seasonId={SEASON_ID}&pageIndex={page}")
        data = api_get(url)
        if not data:
            break
        events = data.get("events", [])
        if not events:
            break
        for e in events:
            all_upcoming.append({
                "event_id":     e["id"],
                "round":        e.get("roundInfo", {}).get("round"),
                "home_team":    e.get("homeTeam", {}).get("name"),
                "away_team":    e.get("awayTeam", {}).get("name"),
                "home_team_id": e.get("homeTeam", {}).get("id"),
                "away_team_id": e.get("awayTeam", {}).get("id"),
                "timestamp":    e.get("startTimestamp"),
            })
        time.sleep(DELAY)

    new_count = exp_count = 0

    for event in all_upcoming:
        mid = str(event["event_id"])
        if mid in id_to_status:
            continue

        row = {c: None for c in MATCH_CORE_COLS}
        row.update({
            "match_id":     event["event_id"],
            "season":       SEASON_STR,
            "round":        event["round"],
            "timestamp":    event["timestamp"],
            "status":       "Not started",
            "home_team":    event["home_team"],
            "away_team":    event["away_team"],
            "home_team_id": event["home_team_id"],
            "away_team_id": event["away_team_id"],
        })

        with open(RAW_2526, "a", newline="", encoding="utf-8") as f:
            existing_cols = load_columns(RAW_2526)
            writer = csv.DictWriter(f, fieldnames=existing_cols or MATCH_CORE_COLS,
                                    extrasaction="ignore")
            writer.writerow(row)
        new_count += 1

        home_lineup = get_last_lineup(players_df, event["home_team"])
        away_lineup = get_last_lineup(players_df, event["away_team"])

        lineup_rows = []
        for side, lineup in [("home", home_lineup), ("away", away_lineup)]:
            for _, p in lineup.iterrows():
                prow = {col: None for col in PLAYER_COLS_FIXED}
                for col in ["player_id", "player_name", "short_name", "position",
                            "shirt_number", "nationality", "height",
                            "market_value", "formation", "captain"]:
                    if col in p.index:
                        prow[col] = p[col]
                prow.update({
                    "match_id":  event["event_id"],
                    "season":    SEASON_STR,
                    "round":     event["round"],
                    "timestamp": event["timestamp"],
                    "home_team": event["home_team"],
                    "away_team": event["away_team"],
                    "side":      side,
                    "substitute":"expected",
                })
                lineup_rows.append(prow)

        if lineup_rows:
            with open(PLAYERS_2526, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=PLAYER_COLS_FIXED,
                                        extrasaction="ignore")
                writer.writerows(lineup_rows)

        rnd = event["round"]
        print(f"   ➕ GW{rnd} {event['home_team']} vs {event['away_team']} "
              f"| {len(lineup_rows)} verwachte spelers")
        exp_count += 1

    print(f"   ✅ {new_count} nieuwe wedstrijden | {exp_count} verwachte lineups")


# ══════════════════════════════════════════════════════════════════════════════
# STAP 5 – Understat xG bijwerken
# ══════════════════════════════════════════════════════════════════════════════

UNDERSTAT_TEAM_MAP = {
    "Manchester United":      "Manchester United",
    "Manchester City":        "Manchester City",
    "Arsenal":                "Arsenal",
    "Liverpool":              "Liverpool",
    "Chelsea":                "Chelsea",
    "Tottenham Hotspur":      "Tottenham",
    "Aston Villa":            "Aston Villa",
    "Newcastle United":       "Newcastle United",
    "Brighton & Hove Albion": "Brighton",
    "West Ham United":        "West Ham",
    "Wolverhampton":          "Wolverhampton Wanderers",
    "Fulham":                 "Fulham",
    "Brentford":              "Brentford",
    "Crystal Palace":         "Crystal Palace",
    "Nottingham Forest":      "Nottingham Forest",
    "Bournemouth":            "Bournemouth",
    "Everton":                "Everton",
    "Leicester City":         "Leicester",
    "Ipswich Town":           "Ipswich",
    "Southampton":            "Southampton",
    "Burnley":                "Burnley",
    "Luton Town":             "Luton",
    "Sheffield United":       "Sheffield United",
    "Leeds United":           "Leeds",
    "Sunderland":             "Sunderland",
}

def stap5_understat():
    print("\n══════════════════════════════════════════")
    print("  STAP 5 – Understat xG bijwerken")
    print("══════════════════════════════════════════")

    try:
        import understatapi
    except ImportError:
        import subprocess, sys
        subprocess.check_call([sys.executable, "-m", "pip", "install", "understatapi", "--quiet"])
        import understatapi

    client = understatapi.UnderstatClient()
    een_maand_terug = (pd.Timestamp.now() - pd.DateOffset(months=1)).date()
    print(f"   📅 Ophalen vanaf: {een_maand_terug}")

    nu = pd.Timestamp.now()
    huidig_jaar = nu.year if nu.month >= 8 else nu.year - 1
    seizoenen   = [str(huidig_jaar - 1), str(huidig_jaar)]

    if os.path.exists(UNDERSTAT_XG_PATH):
        df_oud = pd.read_csv(UNDERSTAT_XG_PATH)
        bestaande_keys = set(
            df_oud["date"].astype(str) + "_" +
            df_oud["home_team"] + "_" +
            df_oud["away_team"]
        )
        print(f"   📂 Bestaande xG data: {len(df_oud)} wedstrijden")
    else:
        df_oud = pd.DataFrame()
        bestaande_keys = set()

    reverse_map  = {v: k for k, v in UNDERSTAT_TEAM_MAP.items()}
    nieuwe_rijen = []

    for seizoen in seizoenen:
        print(f"   🔍 Ophalen {seizoen}/{int(seizoen)+1}...", end=" ", flush=True)
        try:
            matches = client.league(league="EPL").get_match_data(season=seizoen)
        except Exception as e:
            print(f"❌ {e}"); continue

        nieuw = 0
        for match in matches:
            if match["xG"]["h"] is None or match["xG"]["a"] is None:
                continue
            datum = match["datetime"][:10]
            if datum < str(een_maand_terug):
                continue
            home_ss = reverse_map.get(match["h"]["title"], match["h"]["title"])
            away_ss = reverse_map.get(match["a"]["title"], match["a"]["title"])
            key = f"{datum}_{home_ss}_{away_ss}"
            if key in bestaande_keys:
                continue
            nieuwe_rijen.append({
                "date":       datum,
                "home_team":  home_ss,
                "away_team":  away_ss,
                "home_xg":    float(match["xG"]["h"]),
                "away_xg":    float(match["xG"]["a"]),
                "home_goals": int(match["goals"]["h"]),
                "away_goals": int(match["goals"]["a"]),
                "season":     f"{seizoen}/{int(seizoen)+1}",
            })
            nieuw += 1
        print(f"✅ {nieuw} nieuwe wedstrijden")

    UNDERSTAT_NORMALIZE = {
        "Wolverhampton":          "Wolverhampton Wanderers",
        "Brighton":               "Brighton & Hove Albion",
        "Tottenham":              "Tottenham Hotspur",
        "West Ham":               "West Ham United",
        "Leeds":                  "Leeds United",
        "Leicester":              "Leicester City",
        "Newcastle":              "Newcastle United",
        "Ipswich":                "Ipswich Town",
        "Luton":                  "Luton Town",
        "Norwich":                "Norwich City",
        "Sheffield United":       "Sheffield United",
        "Nott'm Forest":          "Nottingham Forest",
        "Man City":               "Manchester City",
        "Man United":             "Manchester United",
        "Man Utd":                "Manchester United",
    }

    if nieuwe_rijen:
        df_nieuw = pd.DataFrame(nieuwe_rijen)
        df_nieuw["home_team"] = df_nieuw["home_team"].replace(UNDERSTAT_NORMALIZE)
        df_nieuw["away_team"] = df_nieuw["away_team"].replace(UNDERSTAT_NORMALIZE)

        if not df_oud.empty:
            df_oud["home_team"] = df_oud["home_team"].replace(UNDERSTAT_NORMALIZE)
            df_oud["away_team"] = df_oud["away_team"].replace(UNDERSTAT_NORMALIZE)

        df_final = (pd.concat([df_oud, df_nieuw], ignore_index=True)
                    .drop_duplicates(subset=["date","home_team","away_team"], keep="last")
                    .sort_values("date").reset_index(drop=True))
        df_final.to_csv(UNDERSTAT_XG_PATH, index=False)
        print(f"\n   💾 {UNDERSTAT_XG_PATH}: {len(df_final)} wedstrijden (+{len(nieuwe_rijen)} nieuw)")
    else:
        print("\n   ✅ Geen nieuwe xG data — alles up-to-date")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    steps = sys.argv[1:] or ["1","2","3","4","5"]

    if "1" in steps: stap1_sofascore()
    if "2" in steps: stap2_cleaning()
    if "3" in steps: stap3_strength()
    if "4" in steps: stap4_upcoming()
    if "5" in steps: stap5_understat()

    print("\n🎉 Pipeline klaar!")