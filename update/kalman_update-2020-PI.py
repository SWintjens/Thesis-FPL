"""
Extended Kalman Filter — Drie Varianten
========================================
Produceert drie aparte CSV's voor de evaluatiescript:

  1. kalman_basis.csv            — EKF zonder asymmetrie, zonder lineup
  2. kalman_asymmetrie.csv       — EKF met asymmetrie, zonder lineup
  3. kalman_asymmetrie_lineup.csv — EKF met asymmetrie + lineup (volledig model)

Alle drie modellen gebruiken dezelfde getuunde hyperparameters.
Het enige verschil is of de asymmetrische gewichten en/of lineup
actief zijn tijdens de state updates.

Input:  understat_xg.csv, match_data.csv
Output: kalman_basis.csv
        kalman_asymmetrie.csv
        kalman_asymmetrie_lineup.csv
"""

import os
import pandas as pd
import numpy as np
import penaltyblog as pb

BASE_DIR        = r"C:\Users\semwi\FPL-Core-Insights_Thesis\data"
UNDERSTAT_PATH  = os.path.join(BASE_DIR, "understat_xg.csv")
MATCH_DATA_PATH = os.path.join(BASE_DIR, "match_data.csv")
OUTPUT_DIR      = BASE_DIR
os.makedirs(OUTPUT_DIR, exist_ok=True)

UD_TEAM_MAP = {
    "Tottenham":     "Tottenham Hotspur",
    "Newcastle":     "Newcastle United",
    "Wolves":        "Wolverhampton Wanderers",
    "Wolverhampton": "Wolverhampton Wanderers",
    "Brighton":      "Brighton & Hove Albion",
    "West Ham":      "West Ham United",
    "Leicester":     "Leicester City",
    "Ipswich":       "Ipswich Town",
    "Luton":         "Luton Town",
    "Norwich":       "Norwich City",
    "Leeds":         "Leeds United",
}

EXCLUDE_SEASONS = {"2014/2015", "2015/2016"}

# ── Getuunde EKF parameters (gemiddelde over validatiefolds) ──────────────────
PHI           = 1.0        # random walk (phi convergeert naar 0.99, gefixeerd op 1)
SIGMA2_W_ATT  = 0.001415
SIGMA2_W_DEF  = 0.001064
SIGMA2_V      = 0.471024
DELTA         = 0.223082
ETA           = 0.016073
KAPPA_ATT     = 0.096247
KAPPA_DEF     = -0.272917 

LINEUP_VARIANT = "rating"


# ══════════════════════════════════════════════════════════════════════════════
# DATA LADEN (identiek aan origineel script)
# ══════════════════════════════════════════════════════════════════════════════
print("Laden understat_xg.csv...")
df = pd.read_csv(UNDERSTAT_PATH)
df["home_team"] = df["home_team"].replace(UD_TEAM_MAP)
df["away_team"] = df["away_team"].replace(UD_TEAM_MAP)
df["date"]      = pd.to_datetime(df["date"], errors="coerce")
df = df[~df["season"].isin(EXCLUDE_SEASONS)].copy()
df = df.sort_values("date").reset_index(drop=True)
print(f"  {len(df)} wedstrijden (vanaf 2016/2017)")

# ── Lineup strength ───────────────────────────────────────────────────────────
print("Lineup strength laden...")
md = pd.read_csv(MATCH_DATA_PATH, low_memory=False)
md["date"]      = pd.to_datetime(md["timestamp"], format="mixed", errors="coerce").dt.date
md["home_team"] = md["home_team"].replace(UD_TEAM_MAP)
md["away_team"] = md["away_team"].replace(UD_TEAM_MAP)
ls_h_col = f"home_lineup_strength_{LINEUP_VARIANT}"
ls_a_col = f"away_lineup_strength_{LINEUP_VARIANT}"
match_lookup = md[["home_team", "away_team", "date", ls_h_col, ls_a_col]].copy()

df["date_key"] = df["date"].dt.date
df = df.merge(match_lookup, left_on=["home_team", "away_team", "date_key"],
              right_on=["home_team", "away_team", "date"], how="left")
df = df.drop(columns=["date_key", "date_y"], errors="ignore")
df = df.rename(columns={"date_x": "date",
                         ls_h_col: "home_lineup_strength",
                         ls_a_col: "away_lineup_strength"})

med_home = df["home_lineup_strength"].median()
med_away = df["away_lineup_strength"].median()
df["home_lineup_strength"] = df["home_lineup_strength"].fillna(med_home)
df["away_lineup_strength"] = df["away_lineup_strength"].fillna(med_away)
df["lineup_strength_diff"] = df["home_lineup_strength"] - df["away_lineup_strength"]

ls_mean = df["lineup_strength_diff"].mean()
ls_std  = df["lineup_strength_diff"].std()
df["lineup_strength_diff_norm"] = (df["lineup_strength_diff"] - ls_mean) / ls_std

# ── Pi-ratings ────────────────────────────────────────────────────────────────
print("Pi-ratings berekenen...")
pi = pb.ratings.PiRatingSystem(alpha=0.15, beta=0.10, k=0.75)
home_pi_home_list   = []
away_pi_away_list   = []
pi_rating_diff_list = []

for _, row in df.iterrows():
    h, a = row["home_team"], row["away_team"]
    h_home_pre = pi.team_ratings.get(h, {"home": 0.0})["home"]
    a_away_pre = pi.team_ratings.get(a, {"away": 0.0})["away"]
    diff_pre   = h_home_pre - a_away_pre
    home_pi_home_list.append(round(h_home_pre, 5))
    away_pi_away_list.append(round(a_away_pre, 5))
    pi_rating_diff_list.append(round(diff_pre, 5))
    if pd.notna(row.get("home_goals")) and pd.notna(row.get("away_goals")):
        pi.update_ratings(h, a, int(row["home_goals"]) - int(row["away_goals"]))

df["home_pi_home_pre"] = home_pi_home_list
df["away_pi_away_pre"] = away_pi_away_list
df["pi_rating_diff"]   = pi_rating_diff_list

pi_diff_mean = df["pi_rating_diff"].mean()
pi_diff_std  = df["pi_rating_diff"].std()
df["pi_rating_diff_norm"] = (df["pi_rating_diff"] - pi_diff_mean) / pi_diff_std

df_xg = df[df["home_xg"].notna() & df["away_xg"].notna()].copy().reset_index(drop=True)
print(f"  Wedstrijden met xG: {len(df_xg)}")


# ══════════════════════════════════════════════════════════════════════════════
# EKF RUNNER — generiek voor alle drie varianten
# ══════════════════════════════════════════════════════════════════════════════
def run_ekf(df_in, use_asymmetry, use_lineup):
    """
    Draait het EKF over alle wedstrijden in df_in.

    use_asymmetry : bool — of de asymmetrische pi-rating gewichten actief zijn
    use_lineup    : bool — of eta het xG voorspelling beïnvloedt
                          (lineup heeft geen rol meer in de Kalman gain-gewichten)

    Geeft een DataFrame terug met voorspellingen en kalman states.
    """
    teams     = sorted(set(df_in["home_team"]) | set(df_in["away_team"]))
    alpha     = {t: 0.0 for t in teams}
    gamma     = {t: 0.0 for t in teams}
    var_alpha = {t: 1.0 for t in teams}
    var_gamma = {t: 1.0 for t in teams}

    results = []
    for _, row in df_in.iterrows():
        h            = row["home_team"]
        a            = row["away_team"]
        ls_diff_norm = row["lineup_strength_diff_norm"]
        pi_diff_norm = row["pi_rating_diff_norm"]

        # ── Predictie stap ────────────────────────────────────────────────────
        a_h  = PHI * alpha[h];  a_a  = PHI * alpha[a]
        g_h  = PHI * gamma[h];  g_a  = PHI * gamma[a]
        va_h = PHI**2 * var_alpha[h] + SIGMA2_W_ATT
        va_a = PHI**2 * var_alpha[a] + SIGMA2_W_ATT
        vg_h = PHI**2 * var_gamma[h] + SIGMA2_W_DEF
        vg_a = PHI**2 * var_gamma[a] + SIGMA2_W_DEF

        # Lineup effect op xG voorspelling alleen in volledig model
        eta_eff = ETA if use_lineup else 0.0
        xg_h_pred = np.exp(np.clip(DELTA + a_h - g_a + eta_eff * ls_diff_norm, -10, 10))
        xg_a_pred = np.exp(np.clip(        a_a - g_h - eta_eff * ls_diff_norm, -10, 10))

        # ── Innovaties ────────────────────────────────────────────────────────
        e_h = row["home_xg"] - xg_h_pred
        e_a = row["away_xg"] - xg_a_pred

        # ── Kalman gains via Jacobiaan linearisatie ───────────────────────────
        S_h = xg_h_pred**2 * (va_h + vg_a) + SIGMA2_V
        S_a = xg_a_pred**2 * (va_a + vg_h) + SIGMA2_V
        K_alpha_h = xg_h_pred * va_h / S_h
        K_gamma_a = xg_h_pred * vg_a / S_h
        K_alpha_a = xg_a_pred * va_a / S_a
        K_gamma_h = xg_a_pred * vg_h / S_a

        # ── Asymmetrische gewichten (uitsluitend pi-rating, geen lineup) ──────
        if use_asymmetry:
            w_att_h = float(np.clip(1.0 + KAPPA_ATT * (-pi_diff_norm), 0.1, 3.0))
            w_att_a = float(np.clip(1.0 + KAPPA_ATT * ( pi_diff_norm), 0.1, 3.0))
            w_def_h = float(np.clip(1.0 + KAPPA_DEF * (-pi_diff_norm), 0.1, 3.0))
            w_def_a = float(np.clip(1.0 + KAPPA_DEF * ( pi_diff_norm), 0.1, 3.0))
        else:
            w_att_h = w_att_a = w_def_h = w_def_a = 1.0

        # ── State updates ─────────────────────────────────────────────────────
        alpha[h] = a_h + K_alpha_h * e_h * w_att_h
        alpha[a] = a_a + K_alpha_a * e_a * w_att_a
        gamma[a] = g_a - K_gamma_a * e_h * w_def_a
        gamma[h] = g_h - K_gamma_h * e_a * w_def_h

        # ── Variantie updates ─────────────────────────────────────────────────
        var_alpha[h] = max((1 - K_alpha_h * xg_h_pred) * va_h, 1e-8)
        var_alpha[a] = max((1 - K_alpha_a * xg_a_pred) * va_a, 1e-8)
        var_gamma[a] = max((1 - K_gamma_a * xg_h_pred) * vg_a, 1e-8)
        var_gamma[h] = max((1 - K_gamma_h * xg_a_pred) * vg_h, 1e-8)

        results.append({
            "date":                      row["date"].date() if hasattr(row["date"], "date") else row["date"],
            "season":                    row["season"],
            "home_team":                 h,
            "away_team":                 a,
            "home_goals":                row["home_goals"],
            "away_goals":                row["away_goals"],
            "home_xg":                   row["home_xg"],
            "away_xg":                   row["away_xg"],
            "home_lineup_strength":      round(row["home_lineup_strength"], 3),
            "away_lineup_strength":      round(row["away_lineup_strength"], 3),
            "lineup_strength_diff_norm": round(ls_diff_norm, 4),
            "home_pi_home_pre":          row["home_pi_home_pre"],
            "away_pi_away_pre":          row["away_pi_away_pre"],
            "pi_rating_diff_norm":       round(pi_diff_norm, 4),
            "kalman_alpha_home":         round(a_h, 4),
            "kalman_gamma_home":         round(g_h, 4),
            "kalman_alpha_away":         round(a_a, 4),
            "kalman_gamma_away":         round(g_a, 4),
            "kalman_xg_pred_home":       round(xg_h_pred, 4),
            "kalman_xg_pred_away":       round(xg_a_pred, 4),
        })

    return pd.DataFrame(results)


# ══════════════════════════════════════════════════════════════════════════════
# DRIE VARIANTEN DRAAIEN EN OPSLAAN
# ══════════════════════════════════════════════════════════════════════════════
variants = [
    {
        "label":         "basis",
        "use_asymmetry": False,
        "use_lineup":    False,
        "filename":      "kalman_basis.csv",
    },
    {
        "label":         "asymmetrie",
        "use_asymmetry": True,
        "use_lineup":    False,
        "filename":      "kalman_asymmetrie.csv",
    },
    {
        "label":         "asymmetrie + lineup",
        "use_asymmetry": True,
        "use_lineup":    True,
        "filename":      "kalman_asymmetrie_lineup.csv",
    },
]

for v in variants:
    print(f"\n{'='*60}")
    print(f"EKF variant: {v['label']}")
    print(f"{'='*60}")
    out = run_ekf(df_xg,
                  use_asymmetry=v["use_asymmetry"],
                  use_lineup=v["use_lineup"])
    path = os.path.join(OUTPUT_DIR, v["filename"])
    out.to_csv(path, index=False)
    print(f"  Opgeslagen: {path}  ({len(out):,} rijen)")

print("\nKlaar. Drie CSV's aangemaakt:")
for v in variants:
    print(f"  → {v['filename']}")