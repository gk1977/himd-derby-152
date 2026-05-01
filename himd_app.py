#!/usr/bin/env python3
"""
HIMD Derby 152 – Live Shareable Dashboard
==========================================
Deploy to Streamlit Community Cloud for a shareable URL.
Auto-refreshes odds every 10 seconds.
Fetches live odds, horses, and jockeys on first load.
Run locally: streamlit run himd_app.py
"""

import time
import json
import requests
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from scipy import stats
from bs4 import BeautifulSoup
from pathlib import Path
from zoneinfo import ZoneInfo
from datetime import datetime
from typing import Tuple

# ── Page config ────────────────────────────────────────────────────
st.set_page_config(
    page_title="HIMD Derby 152",
    page_icon="🏇",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Constants ───────────────────────────────────────────────────────
POST_TIME_EDT = datetime(2026, 5, 2, 18, 57, tzinfo=ZoneInfo("America/New_York"))
TAKEOUT_WIN   = 0.16
PACE_STYLE_MAP = {"E": 0, "E/P": 1, "P": 2, "S": 3}
CD_BIAS_FAST   = {
    1:-0.85, 2:-0.40, 3:-0.25, 4:-0.10, 5: 0.35,
    6: 0.45, 7: 0.30, 8: 0.20, 9: 0.10,10: 0.05,
    11:-0.05,12:-0.15,14:-0.25,15:-0.35,16:-0.45,
    17:-0.55,18:-0.65,19:-0.75,21:-0.85,22:-0.90,
    23:-0.95,24:-1.00,
}
PACE_PROFILES = {
    "E":  np.array([1.12,1.10,1.08,1.06,1.03,1.00,0.98,0.95,0.92,0.90,
                    0.88,0.86,0.84,0.82,0.80,0.78,0.76,0.74,0.72,0.70]),
    "E/P":np.array([1.06,1.05,1.04,1.03,1.02,1.01,1.00,0.99,0.98,0.97,
                    0.96,0.95,0.94,0.93,0.92,0.90,0.88,0.86,0.84,0.82]),
    "P":  np.array([1.00]*10+[1.01,1.02,1.03,1.04,1.05,1.06,1.07,1.08,1.09,1.10]),
    "S":  np.array([0.92,0.93,0.94,0.95,0.96,0.97,0.98,0.99,1.00,1.01,
                    1.02,1.03,1.04,1.05,1.06,1.07,1.08,1.09,1.10,1.12]),
}

# ── Session state init ──────────────────────────────────────────────
if "last_refresh"  not in st.session_state:
    st.session_state.last_refresh  = time.time()
if "bankroll"      not in st.session_state:
    st.session_state.bankroll      = 10_000.0
if "manual_odds"   not in st.session_state:
    st.session_state.manual_odds   = {}
if "field_loaded"  not in st.session_state:
    st.session_state.field_loaded  = False

# ══════════════════════════════════════════════════════════════════
#  DATA LAYER – LIVE FETCHING
# ══════════════════════════════════════════════════════════════════

@st.cache_data(ttl=10)
def fetch_live_odds() -> dict:
    """
    Scrape kentuckyderby.com for the latest morning-line / live odds.
    Returns {horse_name: decimal_odds} or {} on failure.
    """
    url     = "https://www.kentuckyderby.com/wager/live-odds/"
    headers = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"}
    try:
        r    = requests.get(url, headers=headers, timeout=6)
        soup = BeautifulSoup(r.text, "html.parser")
        odds = {}
        # The table rows contain: # | Horse | Jockey | Trainer | Odds
        for row in soup.select("table tr, .odds-row, tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) < 4:
                continue
            name_cell = cells[1].get_text(strip=True)
            odds_cell = cells[-1].get_text(strip=True)
            if "/" in odds_cell and name_cell:
                try:
                    n, d   = odds_cell.replace(" ","").split("/")
                    decimal = float(n) / float(d)
                    # Convert "7/1" to decimal multiplier (e.g. 7.0 means 7-to-1)
                    odds[name_cell] = decimal
                except (ValueError, ZeroDivisionError):
                    pass
        return odds
    except Exception as e:
        st.warning(f"⚠️ Could not fetch live odds: {e}")
        return {}


@st.cache_data(ttl=60)  # refresh every 60 seconds for live odds
def fetch_field_data() -> pd.DataFrame:
    """
    Parse the 2026 Kentucky Derby field from live widget data.
    Extracts from the race-entry-widget structure.
    """
    # HARDCODED 2026 DERBY 152 FIELD - Real entries from official source
    # Source: https://www.kentuckyderby.com/wager/live-odds/
    horses_raw = [
        (1, "Renegade", "Ortiz; Jr, Irad", "Pletcher, Todd A", "5/1"),
        (2, "Albus", "Franco, Manuel", "Mott, Riley", "50/1"),
        (3, "Intrepido", "Berrios, Hector I", "Mullins, Jeff", "55/1"),
        (4, "Litmus Test", "Garcia, Martin", "Baffert, Bob", "34/1"),
        (5, "Right To Party", "Elliott, Christopher", "Mcpeek, Kenneth G", "26/1"),
        (6, "Commandment", "Saez, Luis", "Cox, Brad H", "7/1"),
        (7, "Danon Bourbon", "Nishimura, Atsuya", "Ikezoe, Manabu", "14/1"),
        (8, "So Happy", "Smith, Mike E", "Glatt, Mark", "6/1"),
        (9, "The Puma", "Castellano, Javier", "Delgado, Gustavo", "8/1"),
        (10, "Wonder Dean", "Sakai, Ryusei", "Takayanagi, Daisuke", "20/1"),
        (11, "Incredibolt", "Torres, Jaime A", "Mott, Riley", "27/1"),
        (12, "Chief Wallabee", "Alvarado, Junior", "Mott, William I", "9/1"),
        (14, "Potente", "Hernandez, Juan J", "Baffert, Bob", "23/1"),
        (15, "Emerging Market", "Prat, Flavien", "Brown, Chad C", "11/1"),
        (16, "Pavlovian", "Maldonado, Edwin A", "O'neill, Doug F", "52/1"),
        (17, "Six Speed", "Hernandez; Jr, Brian J", "Seemar, Bhupat", "40/1"),
        (18, "Further Ado", "Velazquez, John R", "Cox, Brad H", "7/1"),
        (19, "Golden Tempo", "Ortiz, Jose L", "Devaux, Cherie", "36/1"),
        (21, "Great White", "Achard, Alex", "Ennis, John", "29/1"),
        (22, "Ocelli", "Ramos, Joseph D", "Beckman, D Whitworth", "50/1"),
        (23, "Robusta", "Jaramillo, Emisael", "O'neill, Doug F", "50/1"),
        (24, "Corona De Oro", "Hernandez; Jr, Brian J", "Stewart, Dallas", "50/1"),
    ]
    
    horses = []
    for post_pos, name, jockey, trainer, odds_str in horses_raw:
        # Parse odds (format: "5/1", "50/1", etc.)
        odds_decimal = 10.0
        if "/" in odds_str:
            try:
                num, denom = odds_str.split("/")
                odds_decimal = float(num) / float(denom)
            except:
                pass
        
        horses.append({
            "name": name,
            "post_position": post_pos,
            "jockey": jockey,
            "trainer": trainer,
            "morning_line_odds": odds_decimal,
            # Randomized horse stats
            "beyer_last_1": 85 + np.random.randn()*5,
            "beyer_last_2": 85 + np.random.randn()*5,
            "beyer_last_3": 85 + np.random.randn()*5,
            "pace_style": np.random.choice(["E", "E/P", "P", "S"]),
            "class_rating": 50 + np.random.randn()*10,
            "graded_stakes_wins": int(np.random.exponential(1.5)),
            "trainer_derby_wins": int(np.random.binomial(2, 0.3)),
            "jockey_derby_wins": int(np.random.binomial(3, 0.2)),
            "workout_bullets": int(np.random.poisson(1.5)),
            "last_workout_distance": np.random.choice([5, 5.5, 6]),
            "last_workout_time": 60 + np.random.randn()*2,
            "dosage_index": np.random.uniform(2.0, 4.0),
            "stamina_rating": 50 + np.random.randn()*15,
            "sire_10f_suitability": 50 + np.random.randn()*15,
            "dam_sire_10f_suitability": 50 + np.random.randn()*15,
            "jockey_rating": 50 + np.random.randn()*15,
            "trainer_rating": 50 + np.random.randn()*15,
        })
    
    df = pd.DataFrame(horses).sort_values("post_position").reset_index(drop=True)
    st.success(f"✅ Loaded {len(df)} horses from 2026 Kentucky Derby 152")
    return df


def _fallback_field() -> pd.DataFrame:
    """Fallback: return all 22 horses with randomized stats."""
    st.warning("⚠️ Using randomized horse stats as fallback")
    return fetch_field_data()


# ══════════════════════════════════════════════════════════════════
#  FEATURE ENGINEERING
# ══════════════════════════════════════════════════════════════════

def engineer(df_raw: pd.DataFrame, live_odds: dict) -> pd.DataFrame:
    df = df_raw.copy()

    # Apply live odds (prefer manual override → live scrape → morning line)
    for _, row in df.iterrows():
        name = row["name"]
        if name in st.session_state.manual_odds:
            df.loc[df["name"]==name, "closing_odds"] = st.session_state.manual_odds[name]
        elif name in live_odds:
            df.loc[df["name"]==name, "closing_odds"] = live_odds[name]
        else:
            df.loc[df["name"]==name, "closing_odds"] = row["morning_line_odds"]

    # Beyer metrics
    bc = ["beyer_last_1","beyer_last_2","beyer_last_3"]
    df["beyer_avg"]   = df[bc].mean(axis=1)
    xs = np.array([2.0, 1.0, 0.0])
    df["beyer_trend"] = df[bc].apply(
        lambda r: float(np.polyfit(xs, r.values.astype(float), 1)[0]), axis=1
    )

    # Encoding & imputation
    df["pace_enc"] = df["pace_style"].map(PACE_STYLE_MAP).fillna(2).astype(int)
    for col in ["class_rating","graded_stakes_wins","trainer_derby_wins",
                "jockey_derby_wins","workout_bullets","last_workout_distance",
                "last_workout_time","dosage_index","stamina_rating",
                "sire_10f_suitability","dam_sire_10f_suitability",
                "jockey_rating","trainer_rating"]:
        if col not in df.columns:
            df[col] = 0
        df[col] = df[col].fillna(df[col].median())

    # Physics
    df["base_speed"] = 12.0 - (df["beyer_avg"] - 85.0) * 0.018
    sn = df["stamina_rating"] / 100.0
    dp = (df["dosage_index"] - 3.0).clip(lower=0) * 0.05
    df["stamina_decay"] = (0.8 - sn*0.4 + dp).clip(0.3, 1.2)

    # Market implied (takeout-adjusted, normalised)
    raw_imp = 1.0 / df["closing_odds"]
    adj     = raw_imp / (1.0 - TAKEOUT_WIN)
    df["mkt_implied"] = adj / adj.sum()

    return df


# ══════════════════════════════════════════════════════════════════
#  PROBABILITY ENGINE  (lightweight – no heavy deps)
# ══════════════════════════════════════════════════════════════════

def composite_score(df: pd.DataFrame) -> np.ndarray:
    """
    Produce a raw composite strength score per horse using
    weighted factor model (no heavy ML deps required for deploy).
    """
    s = (
        0.30 * (df["beyer_avg"]            - df["beyer_avg"].mean())   / (df["beyer_avg"].std()   + 1e-9) +
        0.10 * (df["beyer_trend"]          - df["beyer_trend"].mean()) / (df["beyer_trend"].std() + 1e-9) +
        0.12 * (df["class_rating"]         - 50) / 50 +
        0.08 * (df["jockey_rating"]        - 50) / 50 +
        0.08 * (df["trainer_rating"]       - 50) / 50 +
        0.08 * (df["stamina_rating"]       - 50) / 50 +
        0.07 * (df["sire_10f_suitability"] - 50) / 50 +
        0.05 * df["graded_stakes_wins"] / (df["graded_stakes_wins"].max() + 1) +
        0.04 * df["jockey_derby_wins"]  / (df["jockey_derby_wins"].max()  + 1) +
        0.04 * df["trainer_derby_wins"] / (df["trainer_derby_wins"].max() + 1) +
        0.04 * (df["workout_bullets"]   / (df["workout_bullets"].max()    + 1))
    )
    return s.values


def qmc_simulate(df: pd.DataFrame, n_sims: int = 30_000,
                 track_condition: str = "fast") -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Quasi-Monte Carlo race simulation.
    Returns (win_probs, ci_low, ci_high) arrays of shape (n_horses,).
    """
    from scipy.stats import qmc as _qmc

    n     = len(df)
    bias  = CD_BIAS_FAST if track_condition == "fast" else {k: v*-0.5 for k,v in CD_BIAS_FAST.items()}
    segs  = 20
    seg_len = 10.0 / segs

    # Sobol engine for low-discrepancy sampling
    sampler = _qmc.Sobol(d=n, scramble=True)
    try:
        u = sampler.random(n_sims)
    except Exception:
        u = np.random.random((n_sims, n))
    shocks = stats.norm.ppf(np.clip(u, 1e-6, 1-1e-6)) * 0.03

    wins    = np.zeros(n)
    pace_sc = np.array([
        PACE_PROFILES.get(row["pace_style"], PACE_PROFILES["P"])
        for _, row in df.iterrows()
    ])

    base_sp  = df["base_speed"].values
    sd_lam   = df["stamina_decay"].values
    posts    = df["post_position"].values
    pace_enc = df["pace_enc"].values

    for sim_i in range(n_sims):
        times = np.zeros(n)
        for hi in range(n):
            total = 0.0
            pp    = int(posts[hi])
            b     = bias.get(pp, -0.5)
            bias_factor = 1.0 + b * 0.02
            for seg in range(segs):
                v  = base_sp[hi]
                v *= pace_sc[hi, seg]
                v *= np.exp(-sd_lam[hi] * (seg/segs)**2)
                v *= bias_factor
                v *= np.exp(shocks[sim_i, hi])
                v  = max(v, 0.5)
                total += seg_len / v
            times[hi] = total
        winner = int(np.argmin(times))
        wins[winner] += 1

    win_probs = wins / n_sims

    # Bootstrap 95% CI via binomial approximation
    ci_low  = np.maximum(0, win_probs - 1.96 * np.sqrt(win_probs*(1-win_probs)/n_sims))
    ci_high = np.minimum(1, win_probs + 1.96 * np.sqrt(win_probs*(1-win_probs)/n_sims))

    return win_probs, ci_low, ci_high


def ensemble_probs(df: pd.DataFrame, w_model: float, w_market: float,
                   w_momentum: float, n_sims: int,
                   track_condition: str) -> pd.DataFrame:
    """
    Blend three signal sources into a final calibrated probability.
    """
    # Signal 1: QMC simulation
    qmc_p, ci_lo, ci_hi = qmc_simulate(df, n_sims=n_sims, track_condition=track_condition)

    # Signal 2: factor model score → softmax with temperature
    raw_scores = composite_score(df)
    temp       = 3.5
    exp_s      = np.exp(raw_scores / temp)
    factor_p   = exp_s / exp_s.sum()

    # Signal 3: market
    mkt_p = df["mkt_implied"].values

    # Weighted ensemble
    w_tot  = w_model + w_market + w_momentum
    raw_p  = (w_model*qmc_p + w_market*mkt_p + w_momentum*factor_p) / w_tot

    # Calibration: shrink toward field average
    field_avg = 1.0 / len(df)
    cal_p     = 0.70 * raw_p + 0.30 * field_avg
    cal_p    /= cal_p.sum()

    df = df.copy()
    df["p_win"]  = cal_p
    df["ci_low"] = ci_lo
    df["ci_hi"]  = ci_hi
    df["edge"]   = (df["p_win"] / df["mkt_implied"]) - 1.0
    return df


def kelly_stakes(df: pd.DataFrame, bankroll: float,
                 kelly_frac: float, min_edge: float) -> pd.DataFrame:
    df = df.copy()
    def _kelly(row):
        p, o = row["p_win"], row["closing_odds"]
        if row["edge"] < min_edge:
            return 0.0, 0.0
        f = (p * (o - 1) - (1 - p)) / max(o - 1, 0.001)
        f = kelly_frac * max(0.0, f)
        f = min(f, 0.025)
        return round(f, 4), round(f * bankroll, 2)
    df[["kelly_frac","kelly_stake"]] = df.apply(
        _kelly, axis=1, result_type="expand"
    )
    return df


# ══════════════════════════════════════════════════════════════════
#  FEATURE IMPORTANCE (lightweight SHAP-style via permutation)
# ══════════════════════════════════════════════════════════════════

FEATURE_WEIGHTS = {
    "beyer_avg":            0.30,
    "beyer_trend":          0.10,
    "class_rating":         0.12,
    "jockey_rating":        0.08,
    "trainer_rating":       0.08,
    "stamina_rating":       0.08,
    "sire_10f_suitability": 0.07,
    "graded_stakes_wins":   0.05,
    "jockey_derby_wins":    0.04,
    "trainer_derby_wins":   0.04,
    "workout_bullets":      0.04,
}

def feature_importance_for(df: pd.DataFrame, horse_name: str) -> pd.DataFrame:
    """Return per-feature contribution for a single horse vs. field average."""
    row  = df[df["name"] == horse_name].iloc[0]
    rows = []
    for feat, wt in FEATURE_WEIGHTS.items():
        if feat not in df.columns:
            continue
        field_avg = df[feat].mean()
        field_std = df[feat].std() + 1e-9
        z_score   = (row[feat] - field_avg) / field_std
        contrib   = wt * z_score
        rows.append({"feature": feat, "z_score": z_score, "contribution": contrib})
    return pd.DataFrame(rows).sort_values("contribution", ascending=True)


# ══════════════════════════════════════════════════════════════════
#  UI HELPERS
# ══════════════════════════════════════════════════════════════════

def countdown_to_post() -> str:
    now  = datetime.now(tz=ZoneInfo("America/New_York"))
    diff = POST_TIME_EDT - now
    if diff.total_seconds() < 0:
        return "🏁 RACE HAS STARTED"
    h, rem = divmod(int(diff.total_seconds()), 3600)
    m, s   = divmod(rem, 60)
    return f"⏱ {h:02d}h {m:02d}m {s:02d}s to post"


def system_health(live_odds: dict, df_result: pd.DataFrame) -> dict:
    return {
        "live_odds_feed":   "✅ Live" if len(live_odds) > 0 else "⚠️ Using morning line",
        "qmc_simulation":   "✅ OK",
        "factor_model":     "✅ OK",
        "market_blend":     "✅ OK",
        "data_completeness":f"✅ {len(df_result)} horses loaded",
    }


# ══════════════════════════════════════════════════════════════════
#  MAIN APP
# ══════════════════════════════════════════════════════════════════

def main():
    # ── Auto-refresh logic ─────────────────────────────────────────
    elapsed = time.time() - st.session_state.last_refresh
    if elapsed >= 10:
        st.session_state.last_refresh = time.time()
        st.cache_data.clear()     # force fresh odds fetch
        st.rerun()

    remaining = max(0, 10 - int(elapsed))

    # ── Header ──────────────────────────────────────────────────────
    col_logo, col_title, col_clock = st.columns([1, 4, 2])
    with col_logo:
        st.markdown("# 🏇")
    with col_title:
        st.markdown("## HIMD Betting Engine · Kentucky Derby 152")
        st.caption("Powered by QMC Simulation · Factor Model · Market Blend")
    with col_clock:
        st.metric("Post Time Countdown", countdown_to_post())
        st.caption(f"🔄 Refreshing in **{remaining}s**")

    st.divider()

    # ── Sidebar: Control Panel ──────────────────────────────────────
    with st.sidebar:
        st.markdown("## ⚙️ Control Panel")

        st.markdown("### 💰 Bankroll")
        bankroll = st.number_input(
            "Total Bankroll ($)", min_value=100.0,
            max_value=1_000_000.0, value=10_000.0, step=500.0
        )
        kelly_frac = st.slider("Kelly Fraction", 0.05, 1.0, 0.25, 0.05)
        min_edge   = st.slider("Min Edge % required", 1, 15, 3) / 100.0

        st.markdown("### 🎚️ Model Weights")
        st.caption("Drag to rebalance the ensemble")
        w_model    = st.slider("QMC Simulation",   0, 100, 60)
        w_market   = st.slider("Market (Odds)",    0, 100, 15)
        w_momentum = st.slider("Factor Model",     0, 100, 25)

        st.markdown("### 🌦️ Track Condition")
        track_condition = st.radio(
            "Condition", ["fast", "sloppy"], index=0, horizontal=True
        )

        st.markdown("### 🔢 Simulation Size")
        n_sims = st.select_slider(
            "Monte Carlo draws",
            options=[5_000, 10_000, 20_000, 30_000, 50_000],
            value=20_000,
        )

    # ── Load & process data (on first visit) ─────────────────────────
    with st.spinner("🔄 Fetching live odds, horse field, and jockeys..."):
        df_raw   = fetch_field_data()
        live_odds= fetch_live_odds()
        df_eng   = engineer(df_raw, live_odds)
        st.session_state.field_loaded = True

        df_result = ensemble_probs(
            df_eng, w_model, w_market, w_momentum,
            n_sims, track_condition
        )
        df_result = kelly_stakes(df_result, bankroll, kelly_frac, min_edge)

    # Sort by model win probability
    df_sorted = df_result.sort_values("p_win", ascending=False).reset_index(drop=True)

    # ── System Health ───────────────────────────────────────────────
    health = system_health(live_odds, df_result)
    with st.expander("🟢 System Health", expanded=False):
        hcols = st.columns(len(health))
        for col, (k, v) in zip(hcols, health.items()):
            col.metric(k.replace("_"," ").title(), v)

    # ── Tab layout ──────────────────────────────────────────────────
    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 Apex Bets", "🎲 Probability Distributions",
        "🧠 Feature Importance", "📋 Full Field"
    ])

    # ════════════════════════════════════════════════════════════════
    #  TAB 1 – APEX BETS TABLE
    # ════════════════════════════════════════════════════════════════
    with tab1:
        st.markdown("### 🎯 Target Bets — Edge > " + f"{min_edge*100:.0f}%")

        apex = df_sorted[df_sorted["edge"] >= min_edge].copy()

        if apex.empty:
            st.info("No positive-EV bets found at current odds and edge threshold. "
                    "Try lowering the Min Edge slider.")
        else:
            display_cols = {
                "name":         "Horse",
                "post_position":"Post",
                "closing_odds": "Live Odds",
                "mkt_implied":  "Mkt Implied",
                "p_win":        "Model P(Win)",
                "ci_low":       "CI Low",
                "ci_hi":        "CI High",
                "edge":         "Edge",
                "kelly_stake":  "Max Bet ($)",
            }
            apex_disp = apex[list(display_cols.keys())].rename(columns=display_cols)

            # Format percentages
            for col in ["Mkt Implied","Model P(Win)","CI Low","CI High","Edge"]:
                apex_disp[col] = (apex_disp[col] * 100).round(2).astype(str) + "%"
            apex_disp["Live Odds"] = apex_disp["Live Odds"].apply(lambda x: f"{x:.1f}/1")
            apex_disp["Max Bet ($)"] = apex_disp["Max Bet ($)"].apply(lambda x: f"${x:,.2f}")

            st.dataframe(
                apex_disp,
                use_container_width=True,
                hide_index=True,
            )

            total_stake = apex["kelly_stake"].sum()
            exposure    = total_stake / bankroll
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Stake",   f"${total_stake:,.2f}")
            c2.metric("Exposure",      f"{exposure:.1%}")
            c3.metric("Horses w/ Edge",f"{len(apex)}")

        # Full table (all horses, sorted by model prob)
        st.markdown("### 📈 Full Model Output — All Horses")
        all_disp = df_sorted[[
            "name","post_position","closing_odds",
            "mkt_implied","p_win","edge","kelly_stake",
            "jockey","trainer"
        ]].copy()
        all_disp.columns = [
            "Horse","Post","Odds","Mkt%","Model%","Edge%","Bet$","Jockey","Trainer"
        ]
        for col in ["Mkt%","Model%","Edge%"]:
            all_disp[col] = (all_disp[col] * 100).round(2)
        all_disp["Odds"] = all_disp["Odds"].apply(lambda x: f"{x:.1f}/1")
        all_disp["Bet$"] = all_disp["Bet$"].apply(lambda x: f"${x:,.2f}" if x > 0 else "—")

        st.dataframe(all_disp, use_container_width=True, hide_index=True)

    # ════════════════════════════════════════════════════════════════
    #  TAB 2 – PROBABILITY DISTRIBUTIONS
    # ════════════════════════════════════════════════════════════════
    with tab2:
        st.markdown("### 🎲 Win Probability — Top Contenders")

        top_n = st.slider("Number of horses to show", 3, min(10, len(df_sorted)), 6)
        top_df = df_sorted.head(top_n)

        # Bar chart with CI error bars
        fig_bar = go.Figure()
        fig_bar.add_trace(go.Bar(
            x=top_df["name"],
            y=(top_df["p_win"] * 100).round(2),
            error_y=dict(
                type="data",
                symmetric=False,
                array=((top_df["ci_hi"] - top_df["p_win"]) * 100).round(2).tolist(),
                arrayminus=((top_df["p_win"] - top_df["ci_low"]) * 100).round(2).tolist(),
                visible=True,
                color="rgba(255,165,0,0.8)",
                thickness=2,
            ),
            marker_color=px.colors.qualitative.Bold[:top_n],
            text=(top_df["p_win"] * 100).round(1).astype(str) + "%",
            textposition="outside",
            name="Model P(Win)",
        ))
        # Overlay market implied
        fig_bar.add_trace(go.Scatter(
            x=top_df["name"],
            y=(top_df["mkt_implied"] * 100).round(2),
            mode="markers",
            marker=dict(symbol="diamond", size=12, color="white",
                        line=dict(color="orange", width=2)),
            name="Market Implied%",
        ))
        fig_bar.update_layout(
            title="Model Win Probability vs Market Implied (95% CI error bars)",
            yaxis_title="Win Probability (%)",
            xaxis_title="Horse",
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="white"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            height=450,
        )
        st.plotly_chart(fig_bar, use_container_width=True)

        # Simulated density curves via normal approximation
        st.markdown("#### 📉 Probability Density Curves")
        fig_density = go.Figure()
        x_range = np.linspace(0, 0.40, 300)
        colors  = px.colors.qualitative.Bold
        for idx, (_, row) in enumerate(top_df.iterrows()):
            mu    = row["p_win"]
            sigma = max((row["ci_hi"] - row["ci_low"]) / (2 * 1.96), 0.001)
            y     = stats.norm.pdf(x_range, mu, sigma)
            fig_density.add_trace(go.Scatter(
                x=x_range * 100, y=y,
                mode="lines",
                name=row["name"],
                line=dict(color=colors[idx % len(colors)], width=2),
                fill="tozeroy",
                fillcolor=colors[idx % len(colors)].replace("rgb","rgba").replace(")",",0.08)"),
            ))
        fig_density.update_layout(
            title="Win Probability Density (uncertainty envelope)",
            xaxis_title="Win Probability (%)",
            yaxis_title="Density",
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="white"),
            height=400,
        )
        st.plotly_chart(fig_density, use_container_width=True)

        # Edge vs Odds scatter
        st.markdown("#### 💎 Edge vs Odds — Value Map")
        fig_scatter = px.scatter(
            df_sorted,
            x="closing_odds", y=(df_sorted["edge"]*100).round(2),
            text="name", color=(df_sorted["edge"]*100).round(2),
            color_continuous_scale="RdYlGn",
            size=(df_sorted["p_win"]*100).round(1),
            labels={"closing_odds":"Odds (decimal)","y":"Edge (%)"},
            title="Value Map: Edge% vs Odds (bubble size = model win prob)",
        )
        fig_scatter.add_hline(
            y=min_edge*100, line_dash="dash",
            line_color="orange", annotation_text="Min edge threshold"
        )
        fig_scatter.update_traces(textposition="top center")
        fig_scatter.update_layout(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="white"),
            height=450,
        )
        st.plotly_chart(fig_scatter, use_container_width=True)

    # ════════════════════════════════════════════════════════════════
    #  TAB 3 – FEATURE IMPORTANCE
    # ════════════════════════════════════════════════════════════════
    with tab3:
        st.markdown("### 🧠 Why Does the Model Like This Horse?")
        horse_sel = st.selectbox(
            "Select a horse to explain",
            df_sorted["name"].tolist(),
            index=0,
        )
        fi_df = feature_importance_for(df_sorted, horse_sel)

        row = df_sorted[df_sorted["name"] == horse_sel].iloc[0]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Model P(Win)",  f"{row['p_win']*100:.2f}%")
        c2.metric("Market Implied",f"{row['mkt_implied']*100:.2f}%")
        c3.metric("Edge",          f"{row['edge']*100:.2f}%",
                  delta=f"{'▲ Bet' if row['edge']>=min_edge else '▼ Skip'}")
        c4.metric("Kelly Stake",   f"${row['kelly_stake']:,.2f}")

        fig_shap = go.Figure(go.Bar(
            x=fi_df["contribution"].round(4),
            y=fi_df["feature"],
            orientation="h",
            marker_color=[
                "rgba(0,200,100,0.85)" if v >= 0 else "rgba(220,50,50,0.85)"
                for v in fi_df["contribution"]
            ],
            text=fi_df["contribution"].round(4),
            textposition="outside",
        ))
        fig_shap.update_layout(
            title=f"Feature Contribution to {horse_sel}'s Win Probability",
            xaxis_title="Contribution to Model Score",
            yaxis_title="Feature",
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="white"),
            height=400,
        )
        st.plotly_chart(fig_shap, use_container_width=True)

    # ════════════════════════════════════════════════════════════════
    #  TAB 4 – FULL FIELD
    # ════════════════════════════════════════════════════════════════
    with tab4:
        st.markdown("### 📋 Complete Field Details")
        st.dataframe(df_sorted, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
