import sqlite3
import os
import time
import base64
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from datetime import date, datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "english_rpg.db")
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")

def _get_secret(key):
    val = os.getenv(key, "")
    if val:
        return val
    try:
        return st.secrets.get(key, "")
    except Exception:
        return ""

_SUPABASE_URL = _get_secret("SUPABASE_URL")
_SUPABASE_KEY = _get_secret("SUPABASE_KEY")
_supa = None
if _SUPABASE_URL and _SUPABASE_KEY:
    try:
        from supabase import create_client
        _supa = create_client(_SUPABASE_URL, _SUPABASE_KEY)
    except Exception:
        _supa = None

XP_WEIGHTS = {"duolingo": 1.0, "reading": 3.0, "listening": 0.5, "speaking": 5.0, "srs": 1.0, "writing": 2.0}
SKILL_LEVEL_XP = [0, 50, 150, 350, 700, 1200, 2000]
OVERALL_LEVEL_XP = [0, 100, 300, 700, 1500, 3000, 6000, 10000]

ACHIEVEMENTS = [
    ("first_day",   "First Day",           "🌟", lambda s: s["total_days"] >= 1),
    ("streak_3",    "3 Day Streak",         "🔥", lambda s: s["max_streak"] >= 3),
    ("streak_7",    "7 Day Streak",         "⚡", lambda s: s["max_streak"] >= 7),
    ("streak_14",   "2 Week Streak",        "💎", lambda s: s["max_streak"] >= 14),
    ("streak_30",   "30 Day Streak",        "👑", lambda s: s["max_streak"] >= 30),
    ("streak_60",   "60 Day Streak",        "🌙", lambda s: s["max_streak"] >= 60),
    ("streak_100",  "100 Day Streak",       "💫", lambda s: s["max_streak"] >= 100),
    ("streak_365",  "Year Streak",          "🌍", lambda s: s["max_streak"] >= 365),
    ("xp_100",      "First 100 XP",         "💯", lambda s: s["total_xp"] >= 100),
    ("xp_500",      "500 XP Club",          "🏆", lambda s: s["total_xp"] >= 500),
    ("xp_1000",     "1K XP",               "⭐", lambda s: s["total_xp"] >= 1000),
    ("xp_5000",     "5K XP",               "🌠", lambda s: s["total_xp"] >= 5000),
    ("xp_10000",    "10K XP Legend",        "🔮", lambda s: s["total_xp"] >= 10000),
    ("pass_50",     "50 PASS Days",         "📅", lambda s: s["total_days"] >= 50),
    ("pass_100",    "100 PASS Days",        "🏅", lambda s: s["total_days"] >= 100),
    ("pass_200",    "200 PASS Days",        "🎖", lambda s: s["total_days"] >= 200),
    ("speaking_5",  "Speaking x5",          "🗣", lambda s: s["speaking_sessions"] >= 5),
    ("reading_100", "Reading 100 pages",    "📚", lambda s: s["reading_pages"] >= 100),
    ("srs_50",      "SRS 50 reviews",       "🃏", lambda s: s["srs_reviews"] >= 50),
    ("level_5",     "Level 5",              "⚔️", lambda s: s["level"] >= 5),
    ("consistency", "Consistency Master",   "🎯", lambda s: s["total_days"] >= 30 and s["max_streak"] >= 20),
]

WEEKLY_QUESTS = {
    1: [("Duolingo", "duo_days", 5), ("Reading", "reading_pages", 30), ("Speaking", "speaking_sessions", 2), ("SRS", "srs_reviews", 3)],
    2: [("Duolingo", "duo_days", 6), ("Reading", "reading_pages", 50), ("Listening", "listening_minutes", 40), ("Speaking", "speaking_sessions", 3), ("SRS", "srs_reviews", 5)],
    3: [("Duolingo", "duo_days", 7), ("Reading", "reading_pages", 70), ("Listening", "listening_minutes", 60), ("Speaking", "speaking_sessions", 4), ("SRS", "srs_reviews", 7), ("Writing", "writing_essays", 2)],
    4: [("Duolingo", "duo_days", 9), ("Reading", "reading_pages", 100), ("Listening", "listening_minutes", 90), ("Speaking", "speaking_sessions", 5), ("SRS", "srs_reviews", 10), ("Writing", "writing_essays", 4)],
}


def load_img_b64(name="cat_main.png"):
    path = os.path.join(ASSETS_DIR, name)
    if os.path.exists(path):
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return None


@st.cache_data(ttl=30)
def load_data():
    if _supa:
        try:
            resp = _supa.table("english_daily_log").select(
                "log_date,duo_xp,reading_pages,listening_min,speaking_sessions,"
                "srs_reviews,writing_min,raw_xp,total_xp,streak,multiplier,status,penalty"
            ).order("log_date").execute()
            df = pd.DataFrame(resp.data)
            if not df.empty:
                df["log_date"] = pd.to_datetime(df["log_date"])
                df["day_xp"] = df.apply(lambda r: r["raw_xp"] * r["multiplier"] if r["status"] == "PASS" else 0, axis=1)
            return df
        except Exception:
            pass
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("""
        SELECT log_date, duo_xp, reading_pages, listening_min, speaking_sessions,
               srs_reviews, writing_min, raw_xp, total_xp, streak, multiplier, status, penalty
        FROM daily_log ORDER BY log_date
    """, conn)
    conn.close()
    if df.empty:
        return df
    df["log_date"] = pd.to_datetime(df["log_date"])
    df["day_xp"] = df.apply(lambda r: r["raw_xp"] * r["multiplier"] if r["status"] == "PASS" else 0, axis=1)
    return df


def get_stats(df):
    if df.empty:
        return {"total_xp": 0, "total_days": 0, "max_streak": 0, "current_streak": 0,
                "reading_pages": 0, "listening_minutes": 0, "speaking_sessions": 0,
                "srs_reviews": 0, "writing_essays": 0, "duo_days": 0,
                "skill_xp": {k: 0.0 for k in XP_WEIGHTS}, "level": 1}
    pass_df = df[df["status"] == "PASS"]
    stats = {
        "total_xp": df["total_xp"].iloc[-1],
        "total_days": len(pass_df),
        "max_streak": df["streak"].max(),
        "current_streak": df["streak"].iloc[-1],
        "reading_pages": int(pass_df["reading_pages"].sum()),
        "listening_minutes": int(pass_df["listening_min"].sum()),
        "speaking_sessions": int(pass_df["speaking_sessions"].sum()),
        "srs_reviews": int(pass_df["srs_reviews"].sum()),
        "writing_essays": int((pass_df["writing_min"] > 0).sum()),
        "duo_days": int((pass_df["duo_xp"] > 0).sum()),
        "skill_xp": {
            "duolingo":  float(pass_df["duo_xp"].sum() * XP_WEIGHTS["duolingo"]),
            "reading":   float(pass_df["reading_pages"].sum() * XP_WEIGHTS["reading"]),
            "listening": float(pass_df["listening_min"].sum() * XP_WEIGHTS["listening"]),
            "speaking":  float(pass_df["speaking_sessions"].sum() * XP_WEIGHTS["speaking"]),
            "srs":       float(pass_df["srs_reviews"].sum() * XP_WEIGHTS["srs"]),
            "writing":   float(pass_df["writing_min"].sum() * XP_WEIGHTS["writing"]),
        },
    }
    level = 1
    for i, t in enumerate(OVERALL_LEVEL_XP):
        if stats["total_xp"] >= t:
            level = i + 1
    stats["level"] = level
    return stats


def skill_level(xp):
    for i, t in enumerate(reversed(SKILL_LEVEL_XP)):
        if xp >= t:
            return len(SKILL_LEVEL_XP) - 1 - i
    return 0


def level_progress(total_xp):
    level = 1
    for i, t in enumerate(OVERALL_LEVEL_XP):
        if total_xp >= t:
            level = i + 1
    lo = OVERALL_LEVEL_XP[min(level - 1, len(OVERALL_LEVEL_XP) - 1)]
    hi = OVERALL_LEVEL_XP[min(level, len(OVERALL_LEVEL_XP) - 1)]
    pct = (total_xp - lo) / (hi - lo) if hi > lo else 1.0
    return level, min(pct, 1.0)


def get_english_profile():
    keys = ["english_level", "english_weak", "vocab_estimate"]
    if _supa:
        try:
            resp = _supa.table("english_config").select("key,value").in_("key", keys).execute()
            return {row["key"]: row["value"] for row in resp.data}
        except Exception:
            pass
    try:
        conn = sqlite3.connect(DB_PATH)
        result = {}
        for k in keys:
            row = conn.execute("SELECT value FROM config WHERE key=?", (k,)).fetchone()
            result[k] = row[0] if row else None
        conn.close()
        return result
    except Exception:
        return {}


def cat_message(today_rows, stats):
    streak = stats["current_streak"]
    hour = datetime.now().hour
    if today_rows is None or today_rows.empty:
        if hour < 14:
            return "Good morning! Ready to make today count? 🌅"
        elif hour < 20:
            return "Hey Harvi, don't forget your check-in tonight! 📝"
        else:
            return "🚨 Less than 2 hours left! Check in NOW, buddy!"
    row = today_rows.iloc[-1]
    if row["status"] == "PASS":
        if streak >= 14:
            return f"LEGENDARY! {streak}-day streak! You are absolutely on FIRE! 🔥👑"
        elif streak >= 7:
            return f"One full week+! {streak} days strong — you make this look easy 😎"
        elif streak >= 3:
            return f"Nice work, Harvi! {streak} days in a row. Keep that energy! 💪"
        else:
            return "Good job today! Every PASS day gets you closer to the goal ✅"
    else:
        return "Rough day — it happens to everyone. 💪 Tomorrow we come back stronger!"


# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="English Bro — Harvi", layout="wide", page_icon="😺")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800&family=Space+Grotesk:wght@400;500;700&display=swap');

    .stApp { background: #0F0B1E; }

    .hero-name {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 2.6rem;
        font-weight: 700;
        color: #EDE8FF;
        line-height: 1.1;
        margin: 0;
    }
    .hero-sub {
        font-family: 'Nunito', sans-serif;
        color: #8B7EC0;
        font-size: 1rem;
        margin-top: 0.3rem;
    }
    .stat-card {
        background: linear-gradient(145deg, #1A1340, #221A52);
        border: 1px solid #3A2D72;
        border-radius: 18px;
        padding: 1.2rem 1rem;
        text-align: center;
        margin-bottom: 0.8rem;
    }
    .stat-value {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 2rem;
        font-weight: 700;
        color: #C4A8FF;
        line-height: 1;
    }
    .stat-label {
        font-family: 'Nunito', sans-serif;
        font-size: 0.68rem;
        color: #6A5FA0;
        text-transform: uppercase;
        letter-spacing: 1.5px;
        margin-top: 0.4rem;
    }
    .cat-bubble {
        background: linear-gradient(135deg, #221748, #1A1340);
        border: 1px solid #4A3890;
        border-radius: 0 18px 18px 18px;
        padding: 0.9rem 1.2rem;
        color: #C8B8F0;
        font-family: 'Nunito', sans-serif;
        font-size: 0.95rem;
        font-style: italic;
        margin-top: 0.8rem;
    }
    .today-card-pass {
        background: linear-gradient(135deg, #0A2518, #0D3520);
        border: 2px solid #22C55E;
        border-radius: 18px;
        padding: 1.2rem 1.5rem;
        margin-bottom: 0.8rem;
    }
    .today-card-fail {
        background: linear-gradient(135deg, #280A0A, #3A0F0F);
        border: 2px solid #F87171;
        border-radius: 18px;
        padding: 1.2rem 1.5rem;
        margin-bottom: 0.8rem;
    }
    .today-card-warn {
        background: linear-gradient(135deg, #1E1608, #2D2010);
        border: 2px solid #FBBF24;
        border-radius: 18px;
        padding: 1.2rem 1.5rem;
        margin-bottom: 0.8rem;
    }
    .today-card-crit {
        background: linear-gradient(135deg, #280A0A, #3A0F0F);
        border: 2px solid #EF4444;
        border-radius: 18px;
        padding: 1.2rem 1.5rem;
        margin-bottom: 0.8rem;
    }
    .section-header {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 0.78rem;
        font-weight: 600;
        color: #6A5FA0;
        text-transform: uppercase;
        letter-spacing: 2px;
        border-bottom: 1px solid #221748;
        padding-bottom: 0.5rem;
        margin-bottom: 1rem;
    }
    .xp-bar-bg {
        background: #1A1340;
        border-radius: 8px;
        height: 10px;
        margin: 4px 0 12px 0;
    }
    .profile-card {
        background: linear-gradient(145deg, #160E38, #1E1448);
        border: 1px solid #3A2D72;
        border-radius: 18px;
        padding: 1.2rem;
    }
    .ach-card-unlocked {
        background: linear-gradient(135deg, #1A1340, #251A55);
        border: 1px solid #A880FF;
        border-radius: 12px;
        padding: 0.55rem 0.9rem;
        font-size: 0.82rem;
        color: #E0D0FF;
        font-family: 'Nunito', sans-serif;
        display: flex;
        align-items: center;
        gap: 0.5rem;
        margin-bottom: 7px;
    }
    .ach-card-locked {
        background: #110C25;
        border: 1px solid #221748;
        border-radius: 12px;
        padding: 0.55rem 0.9rem;
        font-size: 0.78rem;
        color: #3A3060;
        font-family: 'Nunito', sans-serif;
        display: flex;
        align-items: center;
        gap: 0.5rem;
        margin-bottom: 7px;
    }
    div[data-testid="stMetric"] {
        background: #1A1340;
        border-radius: 12px;
        padding: 10px;
        border: 1px solid #221748;
    }
    div[data-testid="stMetricValue"] { color: #C4A8FF !important; }
</style>
""", unsafe_allow_html=True)

# ── Load data ─────────────────────────────────────────────────────────────────
df = load_data()
stats = get_stats(df)
level, level_pct = level_progress(stats["total_xp"])
profile = get_english_profile()
cat_b64 = load_img_b64("cat_main.png")

today_str = date.today().isoformat()
today_rows = df[df["log_date"] == pd.Timestamp(today_str)] if not df.empty else pd.DataFrame()
msg_text = cat_message(today_rows, stats)

# ── Sidebar — month filter ────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        '<p style="color:#C4A8FF; font-family:Space Grotesk,sans-serif; '
        'font-weight:700; font-size:1rem; margin-bottom:4px;">📅 Period</p>',
        unsafe_allow_html=True
    )
    if not df.empty:
        periods = sorted(df["log_date"].dt.to_period("M").unique(), reverse=True)
        month_labels = ["All time"] + [p.strftime("%B %Y") for p in periods]
        month_sel = st.selectbox("Show:", month_labels, index=0, label_visibility="collapsed")
        if month_sel != "All time":
            sel_period = next(p for p in periods if p.strftime("%B %Y") == month_sel)
            chart_df = df[df["log_date"].dt.to_period("M") == sel_period].copy()
            chart_stats = get_stats(chart_df)
        else:
            chart_df = df.copy()
            chart_stats = stats
    else:
        month_sel = "All time"
        chart_df = df.copy()
        chart_stats = stats

    st.markdown("---")
    st.markdown(
        '<p style="color:#6A5FA0; font-family:Nunito,sans-serif; font-size:0.75rem;">'
        '🔗 <a href="https://t.me/MyEnglishBro_bot" style="color:#7B6CF6;">@MyEnglishBro_bot</a>'
        '</p>',
        unsafe_allow_html=True
    )

# ── HERO ─────────────────────────────────────────────────────────────────────
col_cat, col_greet, col_kpi = st.columns([1.2, 2, 2.2])

with col_cat:
    if cat_b64:
        st.markdown(f"""
        <div style="border-radius:22px; overflow:hidden; border:2px solid #4A3890;
                    box-shadow: 0 8px 32px rgba(120,80,255,0.3); margin-top:0.3rem;">
            <img src="data:image/png;base64,{cat_b64}" style="width:100%; display:block;">
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(
            '<div style="font-size:5.5rem; text-align:center; padding:1.5rem 0; '
            'border-radius:22px; background:#1A1340; border:2px solid #4A3890;">😺</div>',
            unsafe_allow_html=True
        )

with col_greet:
    st.markdown(
        '<div class="hero-name">Hey, Harvi! 👋</div>'
        '<div class="hero-sub">Your English journey — one day at a time</div>',
        unsafe_allow_html=True
    )
    st.markdown(f'<div class="cat-bubble">"{msg_text}"</div>', unsafe_allow_html=True)

with col_kpi:
    k1, k2 = st.columns(2)
    streak_emoji = "🔥" if stats["current_streak"] > 0 else "💔"
    today_label = "—"
    if not today_rows.empty:
        today_label = "✅" if today_rows.iloc[-1]["status"] == "PASS" else "❌"

    with k1:
        st.markdown(
            f'<div class="stat-card">'
            f'<div class="stat-value">{streak_emoji} {stats["current_streak"]}</div>'
            f'<div class="stat-label">Streak</div></div>',
            unsafe_allow_html=True
        )
        st.markdown(
            f'<div class="stat-card">'
            f'<div class="stat-value">{stats["total_xp"]:.0f}</div>'
            f'<div class="stat-label">Total XP ⭐</div></div>',
            unsafe_allow_html=True
        )
    with k2:
        st.markdown(
            f'<div class="stat-card">'
            f'<div class="stat-value">⚔️ {level}</div>'
            f'<div class="stat-label">Level</div></div>',
            unsafe_allow_html=True
        )
        st.markdown(
            f'<div class="stat-card">'
            f'<div class="stat-value">{stats["total_days"]}</div>'
            f'<div class="stat-label">PASS Days</div></div>',
            unsafe_allow_html=True
        )

# Level progress bar
pct_int = int(level_pct * 100)
st.markdown(f"""
<div style="display:flex; justify-content:space-between; margin: 1rem 0 4px 0;">
    <span style="color:#6A5FA0; font-family:'Nunito',sans-serif; font-size:0.8rem;">⚔️ Level {level}</span>
    <span style="color:#C4A8FF; font-family:'Nunito',sans-serif; font-size:0.8rem;">{pct_int}% → Level {level+1}</span>
</div>
<div class="xp-bar-bg">
    <div style="height:10px; border-radius:8px; width:{pct_int}%;
                background: linear-gradient(90deg, #5B21B6, #C4A8FF);"></div>
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# ── TODAY + ENGLISH PROFILE ───────────────────────────────────────────────────
col_today, col_profile = st.columns([2, 1])

with col_today:
    if today_rows.empty:
        hour_now = datetime.now().hour
        if hour_now >= 20:
            card_cls, urgency_color, urgency = "today-card-crit", "#EF4444", "🚨 URGENT — less than 2 hours left!"
        elif hour_now >= 18:
            card_cls, urgency_color, urgency = "today-card-warn", "#FBBF24", "⚠️ Evening — check-in when you're ready!"
        else:
            card_cls, urgency_color, urgency = "today-card-warn", "#FBBF24", f"📋 {date.today().strftime('%d %b')} — no check-in yet"
        st.markdown(f"""
        <div class="{card_cls}">
            <div style="font-family:'Space Grotesk',sans-serif; font-weight:700;
                         color:{urgency_color}; font-size:1rem;">{urgency}</div>
            <div style="color:#B09040; font-family:'Nunito',sans-serif;
                         margin-top:0.5rem; font-size:0.88rem;">
                Open @MyEnglishBro_bot → tap /checkin
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        row = today_rows.iloc[-1]
        s_color = "#22C55E" if row["status"] == "PASS" else "#F87171"
        s_icon  = "✅ PASS" if row["status"] == "PASS" else "❌ FAIL"
        card_cls = "today-card-pass" if row["status"] == "PASS" else "today-card-fail"
        parts = []
        if row["duo_xp"] > 0:        parts.append(f"📱 +{row['duo_xp']:.0f}")
        if row["reading_pages"] > 0: parts.append(f"📖 {row['reading_pages']}p")
        if row["listening_min"] > 0: parts.append(f"🎧 {row['listening_min']}min")
        if row["speaking_sessions"] > 0: parts.append(f"🗣 {row['speaking_sessions']}x")
        if row["srs_reviews"] > 0:   parts.append(f"🃏 {row['srs_reviews']}")
        if row["writing_min"] > 0:   parts.append(f"✍️ {row['writing_min']}min")
        summary = "  ·  ".join(parts) if parts else "—"
        st.markdown(f"""
        <div class="{card_cls}">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div>
                    <span style="font-family:'Space Grotesk',sans-serif; font-weight:700;
                                 color:{s_color}; font-size:1.1rem;">{s_icon}</span>
                    <span style="color:#90A890; font-family:'Nunito',sans-serif;
                                 margin-left:1rem; font-size:0.85rem;">{summary}</span>
                </div>
                <div style="font-family:'Space Grotesk',sans-serif; font-size:1.4rem;
                             font-weight:700; color:{s_color};">+{row['day_xp']:.0f} XP</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

with col_profile:
    eng_level = profile.get("english_level")
    eng_weak  = profile.get("english_weak")
    vocab_est = profile.get("vocab_estimate")
    level_colors = {"A1": "#6EE7B7", "A2": "#34D399", "B1": "#38BDF8",
                    "B2": "#818CF8", "C1": "#C4A8FF", "C2": "#F472B6"}
    lc = level_colors.get(eng_level, "#6A5FA0")

    if eng_level:
        vocab_html = (f'<div style="color:#8B7EC0; font-size:0.78rem; margin-top:2px;">~{int(vocab_est):,} words</div>'
                      if vocab_est else "")
        weak_html  = (f'<div style="color:#8B7EC0; font-size:0.8rem; margin-top:6px;">Focus: '
                      f'<span style="color:{lc}; font-weight:600;">{eng_weak.capitalize()}</span></div>'
                      if eng_weak else "")
        st.markdown(f"""
        <div class="profile-card">
            <div style="font-family:'Space Grotesk',sans-serif; font-size:0.72rem;
                         color:#6A5FA0; text-transform:uppercase; letter-spacing:1px; margin-bottom:10px;">
                English Profile
            </div>
            <div style="display:flex; align-items:center; gap:12px; margin-bottom:4px;">
                <div style="background:{lc}22; border:2px solid {lc}; border-radius:14px;
                             padding:6px 16px; font-family:'Space Grotesk',sans-serif;
                             font-weight:700; font-size:1.5rem; color:{lc};">{eng_level}</div>
                <div>
                    <div style="color:#D0C0F8; font-family:'Nunito',sans-serif; font-size:0.9rem;">CEFR Level</div>
                    {vocab_html}
                </div>
            </div>
            {weak_html}
            <div style="color:#3A2D72; font-family:'Nunito',sans-serif;
                         font-size:0.72rem; margin-top:10px;">Update: /level in the bot</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="profile-card">
            <div style="text-align:center; padding:0.8rem 0;">
                <div style="font-size:2.5rem;">🎓</div>
                <div style="color:#8B7EC0; font-family:'Nunito',sans-serif;
                             font-size:0.9rem; margin-top:0.5rem; font-weight:600;">
                    Set your English level!
                </div>
                <div style="color:#6A5FA0; font-family:'Nunito',sans-serif;
                             font-size:0.8rem; margin-top:0.4rem;">
                    Send /level to @MyEnglishBro_bot<br>to get personalized messages
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

# ── Forecast ──────────────────────────────────────────────────────────────────
if not df.empty and len(df) >= 3:
    last_7 = df[df["status"] == "PASS"].tail(7)
    avg_daily_xp = last_7["day_xp"].mean() if not last_7.empty else 0
    if avg_daily_xp > 0:
        next_level_xp = next((t for t in OVERALL_LEVEL_XP if t > stats["total_xp"]), None)
        if next_level_xp:
            days_to = int((next_level_xp - stats["total_xp"]) / avg_daily_xp)
            reach_date = date.today() + timedelta(days=days_to)
            st.markdown(f"""
            <div style="background: linear-gradient(135deg, #120A30, #1A1040);
                        border: 1px solid #3A2D72; border-radius: 14px;
                        padding: 0.7rem 1.5rem; margin: 0.8rem 0;
                        display: flex; align-items: center; gap: 1.5rem;">
                <span style="font-size:1.3rem;">🔮</span>
                <span style="color:#B0A0D8; font-family:'Nunito',sans-serif; font-size:0.85rem;">
                    At <b style="color:#C4A8FF">{avg_daily_xp:.0f} XP/day</b> →
                    <b style="color:#22C55E">Level {level+1}</b> in
                    <b style="color:#C4A8FF">{days_to} days</b>
                    ({reach_date.strftime('%d.%m.%Y')})
                </span>
            </div>
            """, unsafe_allow_html=True)

st.markdown("---")

# ── XP History + Skill Radar ──────────────────────────────────────────────────
col_left, col_right = st.columns([3, 2])

with col_left:
    title_period = f" — {month_sel}" if month_sel != "All time" else ""
    st.markdown(f'<div class="section-header">📈 XP History{title_period}</div>', unsafe_allow_html=True)
    if not chart_df.empty:
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        pass_df = chart_df[chart_df["status"] == "PASS"]
        fail_df = chart_df[chart_df["status"] == "FAIL"]
        fig.add_trace(go.Bar(x=pass_df["log_date"], y=pass_df["day_xp"],
            name="XP (PASS)", marker_color="#7B6CF6", opacity=0.85), secondary_y=False)
        if not fail_df.empty:
            fig.add_trace(go.Bar(x=fail_df["log_date"], y=[10] * len(fail_df),
                name="FAIL", marker_color="#F87171", opacity=0.6), secondary_y=False)
        fig.add_trace(go.Scatter(x=chart_df["log_date"], y=chart_df["total_xp"],
            name="Total XP", line=dict(color="#C4A8FF", width=2.5),
            mode="lines+markers", marker=dict(size=4, color="#C4A8FF")), secondary_y=True)
        fig.update_layout(
            paper_bgcolor="#0F0B1E", plot_bgcolor="#140E2A",
            font=dict(color="#8B7EC0"),
            legend=dict(bgcolor="#1A1340", bordercolor="#3A2D72"),
            margin=dict(l=10, r=10, t=10, b=10), height=280,
            xaxis=dict(gridcolor="#1E1748"),
            yaxis=dict(gridcolor="#1E1748", title="Daily XP"),
            yaxis2=dict(gridcolor="#1E1748", title="Total XP", overlaying="y", side="right"),
            barmode="overlay",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No data yet. Start with /checkin in the bot.")

with col_right:
    st.markdown('<div class="section-header">🕸 Skills Radar</div>', unsafe_allow_html=True)
    skill_labels = ["Duolingo", "Reading", "Listening", "Speaking", "SRS", "Writing"]
    skill_keys   = ["duolingo", "reading", "listening", "speaking", "srs", "writing"]
    skill_xp_vals = [chart_stats["skill_xp"][k] for k in skill_keys]
    fig2 = go.Figure(go.Scatterpolar(
        r=skill_xp_vals + [skill_xp_vals[0]],
        theta=skill_labels + [skill_labels[0]],
        fill="toself",
        fillcolor="rgba(123, 108, 246, 0.2)",
        line=dict(color="#7B6CF6", width=2),
        marker=dict(color="#C4A8FF", size=6),
    ))
    fig2.update_layout(
        paper_bgcolor="#0F0B1E", plot_bgcolor="#0F0B1E",
        polar=dict(
            bgcolor="#140E2A",
            radialaxis=dict(visible=True, gridcolor="#221748", color="#6A5FA0", showticklabels=False),
            angularaxis=dict(gridcolor="#221748", color="#C4A8FF", tickfont=dict(size=11)),
        ),
        showlegend=False, margin=dict(l=20, r=20, t=20, b=20), height=280,
    )
    st.plotly_chart(fig2, use_container_width=True)

# ── Activity Calendar + Skill Bars ────────────────────────────────────────────
col_heat, col_bars = st.columns([3, 2])

with col_heat:
    st.markdown('<div class="section-header">📅 Activity Calendar</div>', unsafe_allow_html=True)
    if not chart_df.empty:
        df_h = chart_df.copy()
        df_h["week"] = df_h["log_date"].dt.isocalendar().week
        df_h["dow"]  = df_h["log_date"].dt.dayofweek
        df_h["color_val"] = df_h.apply(lambda r: r["day_xp"] if r["status"] == "PASS" else -5, axis=1)
        df_h["label"] = df_h.apply(
            lambda r: f"{r['log_date'].strftime('%d.%m')} | {r['status']} | {r['day_xp']:.0f} XP | 🔥{r['streak']}",
            axis=1
        )
        fig3 = go.Figure(go.Heatmap(
            x=df_h["week"], y=df_h["dow"],
            z=df_h["color_val"], text=df_h["label"],
            hovertemplate="%{text}<extra></extra>",
            colorscale=[[0, "#280A0A"], [0.1, "#280A0A"], [0.1, "#160E38"],
                        [0.5, "#4A2480"], [1.0, "#C4A8FF"]],
            zmin=-10, zmax=max(df_h["color_val"].max(), 80),
            showscale=False, xgap=3, ygap=3,
        ))
        fig3.update_layout(
            paper_bgcolor="#0F0B1E", plot_bgcolor="#0F0B1E",
            yaxis=dict(tickvals=list(range(7)),
                       ticktext=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"],
                       color="#6A5FA0"),
            xaxis=dict(title="Week", color="#6A5FA0"),
            margin=dict(l=40, r=10, t=10, b=30), height=240,
        )
        st.plotly_chart(fig3, use_container_width=True)

with col_bars:
    st.markdown('<div class="section-header">📊 Skill XP</div>', unsafe_allow_html=True)
    skill_colors = ["#7B6CF6", "#34D399", "#38BDF8", "#F472B6", "#A78BFA", "#FBBF24"]
    skill_levs = [skill_level(chart_stats["skill_xp"][k]) for k in skill_keys]

    week_start = date.today() - timedelta(days=date.today().weekday())
    prev_start = week_start - timedelta(days=7)
    if not chart_df.empty:
        this_wdf = chart_df[chart_df["log_date"] >= pd.Timestamp(week_start)]
        prev_wdf = chart_df[(chart_df["log_date"] >= pd.Timestamp(prev_start)) &
                      (chart_df["log_date"] < pd.Timestamp(week_start))]
        def wk_xp(wdf, col, w):
            return float(wdf[wdf["status"] == "PASS"][col].sum()) * w
        this_w = [wk_xp(this_wdf, "duo_xp", 1), wk_xp(this_wdf, "reading_pages", 3),
                  wk_xp(this_wdf, "listening_min", 0.5), wk_xp(this_wdf, "speaking_sessions", 5),
                  wk_xp(this_wdf, "srs_reviews", 1), wk_xp(this_wdf, "writing_min", 2)]
        prev_w = [wk_xp(prev_wdf, "duo_xp", 1), wk_xp(prev_wdf, "reading_pages", 3),
                  wk_xp(prev_wdf, "listening_min", 0.5), wk_xp(prev_wdf, "speaking_sessions", 5),
                  wk_xp(prev_wdf, "srs_reviews", 1), wk_xp(prev_wdf, "writing_min", 2)]
        trends = ["↑" if t > p else ("↓" if t < p else "→") for t, p in zip(this_w, prev_w)]
    else:
        trends = ["→"] * 6

    y_labels = [f"{e} Lv{l} {tr}" for e, l, tr in zip(skill_labels, skill_levs, trends)]
    fig4 = go.Figure(go.Bar(
        x=skill_xp_vals, y=y_labels, orientation="h",
        marker=dict(color=skill_colors, opacity=0.85),
        text=[f"{v:.0f} XP" for v in skill_xp_vals],
        textposition="outside", textfont=dict(color="#6A5FA0", size=10),
    ))
    fig4.update_layout(
        paper_bgcolor="#0F0B1E", plot_bgcolor="#140E2A",
        xaxis=dict(gridcolor="#1E1748", color="#6A5FA0", showticklabels=False),
        yaxis=dict(color="#C4A8FF", tickfont=dict(size=11)),
        margin=dict(l=10, r=60, t=10, b=10), height=240, showlegend=False,
    )
    st.plotly_chart(fig4, use_container_width=True)

st.markdown("---")

# ── Quests + Achievements ─────────────────────────────────────────────────────
col_q, col_a = st.columns([1, 1])

with col_q:
    week_num = min(4, (date.today().day - 1) // 7 + 1)
    st.markdown(f'<div class="section-header">📋 Weekly Quests — Week {week_num}</div>', unsafe_allow_html=True)
    week_start2 = date.today() - timedelta(days=date.today().weekday())
    if not df.empty:
        wk_df = df[df["log_date"] >= pd.Timestamp(week_start2)]
        wk_stats = {
            "duo_days":          int((wk_df[wk_df["status"] == "PASS"]["duo_xp"] > 0).sum()),
            "reading_pages":     int(wk_df[wk_df["status"] == "PASS"]["reading_pages"].sum()),
            "listening_minutes": int(wk_df[wk_df["status"] == "PASS"]["listening_min"].sum()),
            "speaking_sessions": int(wk_df[wk_df["status"] == "PASS"]["speaking_sessions"].sum()),
            "srs_reviews":       int(wk_df[wk_df["status"] == "PASS"]["srs_reviews"].sum()),
            "writing_essays":    int((wk_df[wk_df["status"] == "PASS"]["writing_min"] > 0).sum()),
        }
    else:
        wk_stats = {k: 0 for k in ["duo_days", "reading_pages", "listening_minutes",
                                    "speaking_sessions", "srs_reviews", "writing_essays"]}
    for name, key, target in WEEKLY_QUESTS.get(week_num, WEEKLY_QUESTS[4]):
        current = wk_stats.get(key, 0)
        pct = min(current / target, 1.0)
        done = pct >= 1.0
        bar_clr = "#22C55E" if done else ("#C4A8FF" if pct >= 0.5 else "#7B6CF6")
        icon = "✅" if done else "🔄"
        st.markdown(f"""
        <div style="margin-bottom:12px;">
            <div style="display:flex; justify-content:space-between;
                         font-family:'Nunito',sans-serif; color:#C0B0E8;
                         font-size:0.85rem; margin-bottom:3px;">
                <span>{icon} {name}</span>
                <span style="color:{bar_clr}; font-weight:600;">{current} / {target}</span>
            </div>
            <div class="xp-bar-bg">
                <div style="height:10px; border-radius:8px; width:{int(pct*100)}%;
                             background: linear-gradient(90deg, #3D1E8A, {bar_clr});"></div>
            </div>
        </div>
        """, unsafe_allow_html=True)

with col_a:
    st.markdown('<div class="section-header">🏆 Achievements</div>', unsafe_allow_html=True)
    unlocked_list, locked_list = [], []
    for ach_id, name, emoji, condition in ACHIEVEMENTS:
        try:
            (unlocked_list if condition(stats) else locked_list).append((emoji, name))
        except Exception:
            locked_list.append((emoji, name))

    for emoji, name in unlocked_list:
        st.markdown(f"""
        <div class="ach-card-unlocked">
            <span style="font-size:1.2rem">{emoji}</span>
            <span style="font-weight:600;">{name}</span>
            <span style="margin-left:auto; color:#A880FF; font-size:0.8rem;">✨ Unlocked</span>
        </div>
        """, unsafe_allow_html=True)

    if locked_list:
        st.markdown(
            f'<div style="color:#3A2D72; font-family:\'Nunito\',sans-serif; '
            f'font-size:0.72rem; margin: 10px 0 6px;">🔒 Locked — {len(locked_list)} remaining</div>',
            unsafe_allow_html=True
        )
        lk_cols = st.columns(2)
        for i, (emoji, name) in enumerate(locked_list[:8]):
            lk_cols[i % 2].markdown(f"""
            <div class="ach-card-locked">
                <span style="font-size:0.95rem; opacity:0.25">{emoji}</span>
                <span>{name}</span>
            </div>
            """, unsafe_allow_html=True)

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("---")
fc, _, ft = st.columns([1, 3, 1])
with fc:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()
with ft:
    st.markdown(
        f'<div style="color:#2A2050; font-family:\'Nunito\',sans-serif; '
        f'font-size:0.7rem; text-align:right;">'
        f'Auto-refresh every 60s<br>{date.today().strftime("%d.%m.%Y")}</div>',
        unsafe_allow_html=True
    )

time.sleep(60)
st.cache_data.clear()
st.rerun()
