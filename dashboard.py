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

XP_WEIGHTS = {"duolingo": 0.5, "reading": 3.0, "listening": 0.5, "speaking": 5.0, "srs": 1.0, "writing": 2.0}
SKILL_LEVEL_XP   = [0, 50, 150, 350, 700, 1200, 2000]
OVERALL_LEVEL_XP = [0, 100, 300, 700, 1500, 3000, 6000, 10000]

ACHIEVEMENTS = [
    ("first_day",   "First Day",          "🌱", lambda s: s["total_days"] >= 1),
    ("streak_3",    "3-Day Streak",        "🔥", lambda s: s["max_streak"] >= 3),
    ("streak_7",    "On Fire",             "⚡", lambda s: s["max_streak"] >= 7),
    ("streak_14",   "Two Weeks",           "💎", lambda s: s["max_streak"] >= 14),
    ("streak_30",   "Monthly Warrior",     "👑", lambda s: s["max_streak"] >= 30),
    ("streak_60",   "Iron Will",           "🌙", lambda s: s["max_streak"] >= 60),
    ("streak_100",  "Century",             "💫", lambda s: s["max_streak"] >= 100),
    ("streak_365",  "Year Legend",         "🌍", lambda s: s["max_streak"] >= 365),
    ("xp_100",      "First 100 XP",        "💯", lambda s: s["total_xp"] >= 100),
    ("xp_500",      "Rising Star",         "⭐", lambda s: s["total_xp"] >= 500),
    ("xp_1000",     "1K Club",             "🏆", lambda s: s["total_xp"] >= 1000),
    ("xp_5000",     "5K Legend",           "🌟", lambda s: s["total_xp"] >= 5000),
    ("xp_10000",    "Grandmaster",         "🔮", lambda s: s["total_xp"] >= 10000),
    ("pass_50",     "50 PASS Days",        "📅", lambda s: s["total_days"] >= 50),
    ("pass_100",    "100 PASS Days",       "🏅", lambda s: s["total_days"] >= 100),
    ("pass_200",    "Unstoppable",         "🎖", lambda s: s["total_days"] >= 200),
    ("speaking_5",  "Voice Starter",       "🗣", lambda s: s["speaking_sessions"] >= 5),
    ("reading_100", "Bookworm",            "📚", lambda s: s["reading_pages"] >= 100),
    ("srs_50",      "Card Shark",          "🃏", lambda s: s["srs_reviews"] >= 50),
    ("level_5",     "Level 5",             "⚔️", lambda s: s["level"] >= 5),
    ("consistency", "Consistency Master",  "🎯", lambda s: s["total_days"] >= 30 and s["max_streak"] >= 20),
]

WEEKLY_QUESTS = {
    1: [("Duolingo", "duo_days", 5), ("Reading", "reading_pages", 30),
        ("Speaking", "speaking_sessions", 2), ("SRS", "srs_reviews", 3)],
    2: [("Duolingo", "duo_days", 6), ("Reading", "reading_pages", 50),
        ("Listening", "listening_minutes", 40), ("Speaking", "speaking_sessions", 3), ("SRS", "srs_reviews", 5)],
    3: [("Duolingo", "duo_days", 7), ("Reading", "reading_pages", 70),
        ("Listening", "listening_minutes", 60), ("Speaking", "speaking_sessions", 4),
        ("SRS", "srs_reviews", 7), ("Writing", "writing_essays", 2)],
    4: [("Duolingo", "duo_days", 9), ("Reading", "reading_pages", 100),
        ("Listening", "listening_minutes", 90), ("Speaking", "speaking_sessions", 5),
        ("SRS", "srs_reviews", 10), ("Writing", "writing_essays", 4)],
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
                df["day_xp"] = df.apply(
                    lambda r: r["raw_xp"] * r["multiplier"] if r["status"] == "PASS" else 0, axis=1)
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
    df["day_xp"] = df.apply(
        lambda r: r["raw_xp"] * r["multiplier"] if r["status"] == "PASS" else 0, axis=1)
    return df


@st.cache_data(ttl=120)
def load_memories():
    if not _supa:
        return []
    try:
        rows = (
            _supa.table("english_memory")
            .select("category,key,value,updated_at")
            .order("updated_at", desc=True)
            .limit(30)
            .execute()
            .data or []
        )
        return rows
    except Exception:
        return []


def get_stats(df):
    if df.empty:
        return {"total_xp": 0, "total_days": 0, "max_streak": 0, "current_streak": 0,
                "reading_pages": 0, "listening_minutes": 0, "speaking_sessions": 0,
                "srs_reviews": 0, "writing_essays": 0, "duo_days": 0,
                "skill_xp": {k: 0.0 for k in XP_WEIGHTS}, "level": 1}
    pass_df = df[df["status"] == "PASS"]
    stats = {
        "total_xp":          df["total_xp"].iloc[-1],
        "total_days":        len(pass_df),
        "max_streak":        df["streak"].max(),
        "current_streak":    df["streak"].iloc[-1],
        "reading_pages":     int(pass_df["reading_pages"].sum()),
        "listening_minutes": int(pass_df["listening_min"].sum()),
        "speaking_sessions": int(pass_df["speaking_sessions"].sum()),
        "srs_reviews":       int(pass_df["srs_reviews"].sum()),
        "writing_essays":    int((pass_df["writing_min"] > 0).sum()),
        "duo_days":          int((pass_df["duo_xp"] > 0).sum()),
        "skill_xp": {
            "duolingo":  float(pass_df["duo_xp"].sum()             * XP_WEIGHTS["duolingo"]),
            "reading":   float(pass_df["reading_pages"].sum()       * XP_WEIGHTS["reading"]),
            "listening": float(pass_df["listening_min"].sum()       * XP_WEIGHTS["listening"]),
            "speaking":  float(pass_df["speaking_sessions"].sum()   * XP_WEIGHTS["speaking"]),
            "srs":       float(pass_df["srs_reviews"].sum()         * XP_WEIGHTS["srs"]),
            "writing":   float(pass_df["writing_min"].sum()         * XP_WEIGHTS["writing"]),
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
            return "Don't forget your check-in tonight! 📝"
        else:
            return "Less than 2 hours left — check in NOW! 🚨"
    row = today_rows.iloc[-1]
    if row["status"] == "PASS":
        if streak >= 30:
            return f"LEGENDARY! {streak}-day streak — you're unstoppable! 🔥👑"
        elif streak >= 14:
            return f"Two weeks and counting! {streak} days of pure dedication. 💎"
        elif streak >= 7:
            return f"One full week strong! {streak} days — you make this look easy 😎"
        elif streak >= 3:
            return f"Nice! {streak} days in a row. Keep that energy going! 💪"
        else:
            return "Day checked — every PASS gets you closer to the goal ✅"
    else:
        return "Rough day — happens to the best. Tomorrow we come back stronger 💪"


# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="English Bro — Harvi", layout="wide", page_icon="😺")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Space+Grotesk:wght@400;500;600;700&display=swap');

    /* ── Base ── */
    .stApp { background: #080514; }
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    /* ── Scrollbar ── */
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: #0D0A20; }
    ::-webkit-scrollbar-thumb { background: #3A2D72; border-radius: 3px; }

    /* ── Sidebar ── */
    section[data-testid="stSidebar"] { background: #0D0A20 !important; border-right: 1px solid #1E1748; }
    section[data-testid="stSidebar"] * { color: #8B7EC0 !important; }

    /* ── Glass card ── */
    .glass {
        background: rgba(26, 19, 64, 0.6);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border: 1px solid rgba(100, 80, 200, 0.25);
        border-radius: 20px;
    }

    /* ── Hero ── */
    .hero-name {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 2.8rem;
        font-weight: 800;
        background: linear-gradient(135deg, #EDE8FF 0%, #C4A8FF 50%, #7B6CF6 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        line-height: 1.1;
        margin: 0;
    }
    .hero-sub {
        color: #6A5FA0;
        font-size: 0.95rem;
        margin-top: 0.4rem;
        font-weight: 400;
    }

    /* ── Speech bubble ── */
    .cat-bubble {
        background: linear-gradient(135deg, rgba(34, 23, 72, 0.9), rgba(26, 19, 64, 0.9));
        border: 1px solid rgba(100, 80, 200, 0.4);
        border-radius: 0 16px 16px 16px;
        padding: 0.9rem 1.2rem;
        color: #C8B8F0;
        font-size: 0.95rem;
        font-style: italic;
        margin-top: 0.8rem;
        position: relative;
    }
    .cat-bubble::before {
        content: '';
        position: absolute;
        top: 0; left: -8px;
        border: 8px solid transparent;
        border-right-color: rgba(100, 80, 200, 0.4);
        border-top: 0;
    }

    /* ── KPI cards ── */
    .kpi-card {
        background: linear-gradient(145deg, rgba(26, 19, 64, 0.8), rgba(34, 26, 82, 0.8));
        border: 1px solid rgba(100, 80, 200, 0.3);
        border-radius: 18px;
        padding: 1rem;
        text-align: center;
        margin-bottom: 0.7rem;
        transition: border-color 0.2s;
    }
    .kpi-card:hover { border-color: rgba(196, 168, 255, 0.5); }
    .kpi-value {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 2.1rem;
        font-weight: 700;
        color: #C4A8FF;
        line-height: 1;
    }
    .kpi-label {
        font-size: 0.65rem;
        color: #5A4F90;
        text-transform: uppercase;
        letter-spacing: 1.8px;
        margin-top: 0.4rem;
        font-weight: 600;
    }

    /* ── Level bar ── */
    .level-bar-track {
        background: rgba(26, 19, 64, 0.8);
        border-radius: 100px;
        height: 12px;
        margin: 8px 0 16px;
        overflow: hidden;
        border: 1px solid rgba(100, 80, 200, 0.2);
    }
    .level-bar-fill {
        height: 100%;
        border-radius: 100px;
        background: linear-gradient(90deg, #5B21B6, #7B6CF6, #C4A8FF);
        box-shadow: 0 0 12px rgba(123, 108, 246, 0.6);
        transition: width 1s ease;
    }

    /* ── Today cards ── */
    .today-pass {
        background: linear-gradient(135deg, rgba(10, 37, 24, 0.9), rgba(13, 53, 32, 0.9));
        border: 2px solid rgba(34, 197, 94, 0.7);
        border-radius: 18px;
        padding: 1.2rem 1.5rem;
        box-shadow: 0 0 24px rgba(34, 197, 94, 0.1);
    }
    .today-fail {
        background: linear-gradient(135deg, rgba(40, 10, 10, 0.9), rgba(58, 15, 15, 0.9));
        border: 2px solid rgba(248, 113, 113, 0.6);
        border-radius: 18px;
        padding: 1.2rem 1.5rem;
        box-shadow: 0 0 24px rgba(248, 113, 113, 0.08);
    }
    .today-pending {
        background: linear-gradient(135deg, rgba(30, 22, 8, 0.9), rgba(45, 32, 16, 0.9));
        border: 2px solid rgba(251, 191, 36, 0.5);
        border-radius: 18px;
        padding: 1.2rem 1.5rem;
        box-shadow: 0 0 24px rgba(251, 191, 36, 0.08);
    }
    .today-urgent {
        background: linear-gradient(135deg, rgba(40, 10, 10, 0.9), rgba(58, 15, 15, 0.9));
        border: 2px solid rgba(239, 68, 68, 0.8);
        border-radius: 18px;
        padding: 1.2rem 1.5rem;
        box-shadow: 0 0 32px rgba(239, 68, 68, 0.15);
    }

    /* ── Section headers ── */
    .section-title {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 0.72rem;
        font-weight: 700;
        color: #4A3F7A;
        text-transform: uppercase;
        letter-spacing: 2.5px;
        padding-bottom: 0.6rem;
        border-bottom: 1px solid rgba(58, 45, 114, 0.4);
        margin-bottom: 1rem;
    }

    /* ── Profile card ── */
    .profile-card {
        background: linear-gradient(145deg, rgba(22, 14, 56, 0.8), rgba(30, 20, 72, 0.8));
        border: 1px solid rgba(100, 80, 200, 0.3);
        border-radius: 18px;
        padding: 1.2rem;
        height: 100%;
    }

    /* ── Achievement cards ── */
    .ach-unlocked {
        background: linear-gradient(135deg, rgba(26, 19, 64, 0.8), rgba(37, 26, 85, 0.8));
        border: 1px solid rgba(168, 128, 255, 0.5);
        border-radius: 12px;
        padding: 0.5rem 0.8rem;
        font-size: 0.82rem;
        color: #E0D0FF;
        display: flex;
        align-items: center;
        gap: 0.5rem;
        margin-bottom: 6px;
        box-shadow: 0 0 8px rgba(168, 128, 255, 0.1);
    }
    .ach-locked {
        background: rgba(17, 12, 37, 0.5);
        border: 1px solid rgba(34, 23, 72, 0.6);
        border-radius: 12px;
        padding: 0.5rem 0.8rem;
        font-size: 0.78rem;
        color: #2D2560;
        display: flex;
        align-items: center;
        gap: 0.5rem;
        margin-bottom: 6px;
    }

    /* ── Memory card ── */
    .memory-card {
        background: linear-gradient(135deg, rgba(18, 10, 48, 0.9), rgba(26, 16, 64, 0.9));
        border: 1px solid rgba(80, 60, 160, 0.4);
        border-radius: 14px;
        padding: 0.7rem 1rem;
        margin-bottom: 8px;
        font-size: 0.84rem;
        color: #B0A0D8;
    }
    .memory-category {
        font-size: 0.62rem;
        text-transform: uppercase;
        letter-spacing: 1.5px;
        font-weight: 700;
        margin-bottom: 3px;
    }

    /* ── Forecast ── */
    .forecast-bar {
        background: linear-gradient(135deg, rgba(18, 10, 48, 0.8), rgba(26, 16, 64, 0.8));
        border: 1px solid rgba(58, 45, 114, 0.5);
        border-radius: 14px;
        padding: 0.7rem 1.4rem;
        display: flex;
        align-items: center;
        gap: 1rem;
        margin: 0.6rem 0;
    }

    /* ── Metric overrides ── */
    div[data-testid="stMetric"] {
        background: rgba(26, 19, 64, 0.5) !important;
        border-radius: 12px !important;
        padding: 10px !important;
        border: 1px solid rgba(58, 45, 114, 0.4) !important;
    }
    div[data-testid="stMetricValue"] { color: #C4A8FF !important; }
    div[data-testid="stMetricDelta"] { color: #22C55E !important; }

    /* ── Divider ── */
    hr { border-color: rgba(58, 45, 114, 0.3) !important; margin: 1.5rem 0 !important; }

    /* ── Button ── */
    .stButton > button {
        background: linear-gradient(135deg, #3D1E8A, #5B3DBA) !important;
        border: none !important;
        color: #E0D0FF !important;
        border-radius: 10px !important;
        font-weight: 600 !important;
        font-size: 0.85rem !important;
        padding: 0.4rem 1.2rem !important;
    }
    .stButton > button:hover {
        background: linear-gradient(135deg, #5B3DBA, #7B6CF6) !important;
        box-shadow: 0 0 16px rgba(123, 108, 246, 0.4) !important;
    }

    /* ── Activity pips (calendar legend) ── */
    .pip { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 3px; }
</style>
""", unsafe_allow_html=True)

# ── Load data ──────────────────────────────────────────────────────────────────
df       = load_data()
stats    = get_stats(df)
level, level_pct = level_progress(stats["total_xp"])
profile  = get_english_profile()
memories = load_memories()
cat_b64  = load_img_b64("cat_main.png")

today_str  = date.today().isoformat()
today_rows = df[df["log_date"] == pd.Timestamp(today_str)] if not df.empty else pd.DataFrame()
msg_text   = cat_message(today_rows, stats)

SKILL_KEYS   = ["duolingo", "reading", "listening", "speaking", "srs", "writing"]
SKILL_LABELS = ["Duolingo", "Reading", "Listening", "Speaking", "SRS", "Writing"]
SKILL_COLORS = ["#7B6CF6", "#34D399", "#38BDF8", "#F472B6", "#A78BFA", "#FBBF24"]
SKILL_EMOJIS = ["📱", "📖", "🎧", "🗣", "🃏", "✍️"]

# ── Sidebar ────────────────────────────────────────────────────────────────────
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
            chart_df   = df[df["log_date"].dt.to_period("M") == sel_period].copy()
            chart_stats = get_stats(chart_df)
        else:
            chart_df    = df.copy()
            chart_stats = stats
    else:
        month_sel   = "All time"
        chart_df    = df.copy()
        chart_stats = stats

    st.markdown("---")
    st.markdown("""
    <div style="font-size:0.78rem; color:#4A3F7A; line-height:1.8;">
        <b style="color:#6A5FA0">Commands</b><br>
        /checkin — daily check-in<br>
        /stats — progress<br>
        /talk — conversation mode<br>
        /memory — Harvi's memory<br>
        /skilltree — skill levels
    </div>
    """, unsafe_allow_html=True)
    st.markdown(
        '<div style="margin-top:1rem; font-size:0.75rem; color:#3A3060;">'
        '🔗 <a href="https://t.me/MyEnglishBro_bot" style="color:#7B6CF6;">@MyEnglishBro_bot</a>'
        '</div>',
        unsafe_allow_html=True
    )

# ── HERO ──────────────────────────────────────────────────────────────────────
col_cat, col_greet, col_kpi = st.columns([1.1, 2.2, 2])

with col_cat:
    if cat_b64:
        st.markdown(f"""
        <div style="border-radius:22px; overflow:hidden;
                    border:2px solid rgba(100,80,200,0.4);
                    box-shadow: 0 0 40px rgba(123,80,255,0.25),
                                0 8px 32px rgba(0,0,0,0.4);
                    margin-top:0.3rem;">
            <img src="data:image/png;base64,{cat_b64}" style="width:100%; display:block;">
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown(
            '<div style="font-size:5.5rem; text-align:center; padding:1.5rem 0; '
            'border-radius:22px; background:rgba(26,19,64,0.5); '
            'border:2px solid rgba(100,80,200,0.3);">😺</div>',
            unsafe_allow_html=True
        )

with col_greet:
    st.markdown(
        '<div class="hero-name">Hey, Vladimir! 👋</div>'
        '<div class="hero-sub">Your English journey — one day at a time</div>',
        unsafe_allow_html=True
    )
    st.markdown(f'<div class="cat-bubble">"{msg_text}"</div>', unsafe_allow_html=True)

    # mini activity strip — last 14 days
    if not df.empty:
        last14 = []
        for i in range(13, -1, -1):
            d = (date.today() - timedelta(days=i)).isoformat()
            row14 = df[df["log_date"] == pd.Timestamp(d)]
            if row14.empty:
                last14.append(("⬜", "#222"))
            elif row14.iloc[-1]["status"] == "PASS":
                last14.append(("🟩", "#22C55E"))
            else:
                last14.append(("🟥", "#F87171"))
        pips = "".join(
            f'<div class="pip" style="background:{c};" title="{d}"></div>'
            for (_, c), d in zip(last14, [
                (date.today() - timedelta(days=i)).strftime("%d.%m")
                for i in range(13, -1, -1)
            ])
        )
        st.markdown(
            f'<div style="margin-top:0.8rem; display:flex; align-items:center; gap:4px;">'
            f'<span style="color:#4A3F7A; font-size:0.72rem; margin-right:4px;">Last 14 days</span>'
            f'{pips}</div>',
            unsafe_allow_html=True
        )

with col_kpi:
    k1, k2 = st.columns(2)
    streak_emoji = "🔥" if stats["current_streak"] > 0 else "💔"
    today_label  = "✅" if (not today_rows.empty and today_rows.iloc[-1]["status"] == "PASS") else (
                   "❌" if not today_rows.empty else "—")
    with k1:
        st.markdown(
            f'<div class="kpi-card">'
            f'<div class="kpi-value">{streak_emoji} {stats["current_streak"]}</div>'
            f'<div class="kpi-label">Day Streak</div></div>',
            unsafe_allow_html=True
        )
        st.markdown(
            f'<div class="kpi-card">'
            f'<div class="kpi-value">{stats["total_xp"]:.0f}</div>'
            f'<div class="kpi-label">Total XP ⭐</div></div>',
            unsafe_allow_html=True
        )
    with k2:
        st.markdown(
            f'<div class="kpi-card">'
            f'<div class="kpi-value">⚔️ {level}</div>'
            f'<div class="kpi-label">Level</div></div>',
            unsafe_allow_html=True
        )
        st.markdown(
            f'<div class="kpi-card">'
            f'<div class="kpi-value">{today_label}</div>'
            f'<div class="kpi-label">Today</div></div>',
            unsafe_allow_html=True
        )

# Level XP bar
pct_int = int(level_pct * 100)
lo_xp = OVERALL_LEVEL_XP[min(level - 1, len(OVERALL_LEVEL_XP) - 1)]
hi_xp = OVERALL_LEVEL_XP[min(level, len(OVERALL_LEVEL_XP) - 1)]
st.markdown(f"""
<div style="display:flex; justify-content:space-between; align-items:center; margin: 0.8rem 0 4px 0;">
    <span style="color:#6A5FA0; font-size:0.78rem; font-weight:600;">⚔️ Level {level}
        <span style="color:#3A2D72; font-weight:400;"> · {stats['total_xp']:.0f} / {hi_xp} XP</span>
    </span>
    <span style="color:#C4A8FF; font-size:0.78rem; font-weight:600;">{pct_int}% → Lv{level+1}</span>
</div>
<div class="level-bar-track">
    <div class="level-bar-fill" style="width:{pct_int}%;"></div>
</div>
""", unsafe_allow_html=True)

# ── Stats strip ────────────────────────────────────────────────────────────────
s1, s2, s3, s4, s5 = st.columns(5)
strip_items = [
    ("📅", stats["total_days"], "PASS days"),
    ("🏅", stats["max_streak"], "Best streak"),
    ("📖", stats["reading_pages"], "Pages read"),
    ("🗣", stats["speaking_sessions"], "Speaking"),
    ("🃏", stats["srs_reviews"], "SRS reviews"),
]
for col, (icon, val, label) in zip([s1, s2, s3, s4, s5], strip_items):
    col.markdown(
        f'<div style="text-align:center; padding:0.6rem 0;">'
        f'<div style="font-size:1.4rem;">{icon}</div>'
        f'<div style="font-family:Space Grotesk,sans-serif; color:#C4A8FF; font-size:1.2rem; font-weight:700;">{val}</div>'
        f'<div style="color:#3A3060; font-size:0.63rem; text-transform:uppercase; letter-spacing:1.5px;">{label}</div>'
        f'</div>',
        unsafe_allow_html=True
    )

st.markdown("---")

# ── TODAY + PROFILE ────────────────────────────────────────────────────────────
col_today, col_profile = st.columns([2, 1])

with col_today:
    st.markdown('<div class="section-title">📋 Today</div>', unsafe_allow_html=True)
    if today_rows.empty:
        hour_now = datetime.now().hour
        if hour_now >= 20:
            cls, color, msg = "today-urgent", "#EF4444", "🚨 URGENT — less than 2 hours left!"
        else:
            cls, color, msg = "today-pending", "#FBBF24", f"📋 {date.today().strftime('%A, %d %b')} — not checked in yet"
        st.markdown(f"""
        <div class="{cls}">
            <div style="font-weight:700; color:{color}; font-size:1rem; font-family:Space Grotesk,sans-serif;">{msg}</div>
            <div style="color:#8B7040; font-size:0.85rem; margin-top:0.5rem;">
                Open @MyEnglishBro_bot → tap /checkin
            </div>
        </div>""", unsafe_allow_html=True)
    else:
        row = today_rows.iloc[-1]
        is_pass  = row["status"] == "PASS"
        s_color  = "#22C55E" if is_pass else "#F87171"
        s_icon   = "✅ PASS" if is_pass else "❌ FAIL"
        cls      = "today-pass" if is_pass else "today-fail"
        parts = []
        if row["duo_xp"] > 0:            parts.append(f"📱 +{row['duo_xp']:.0f} XP")
        if row["reading_pages"] > 0:     parts.append(f"📖 {row['reading_pages']}p")
        if row["listening_min"] > 0:     parts.append(f"🎧 {row['listening_min']}min")
        if row["speaking_sessions"] > 0: parts.append(f"🗣 {row['speaking_sessions']}x")
        if row["srs_reviews"] > 0:       parts.append(f"🃏 {row['srs_reviews']}")
        if row["writing_min"] > 0:       parts.append(f"✍️ {row['writing_min']}min")
        summary = "  ·  ".join(parts) if parts else "Nothing logged"
        mult_badge = (f'<span style="background:rgba(34,197,94,0.15); color:#22C55E; '
                      f'font-size:0.75rem; border-radius:6px; padding:2px 7px; margin-left:8px;">'
                      f'×{row["multiplier"]:.1f}</span>') if row["multiplier"] > 1 else ""
        st.markdown(f"""
        <div class="{cls}">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.5rem;">
                <div>
                    <span style="font-family:Space Grotesk,sans-serif; font-weight:700;
                                 color:{s_color}; font-size:1.1rem;">{s_icon}</span>{mult_badge}
                </div>
                <div style="font-family:Space Grotesk,sans-serif; font-size:1.6rem;
                             font-weight:800; color:{s_color};">+{row['day_xp']:.0f} XP</div>
            </div>
            <div style="color:#7A9A7A; font-size:0.85rem;">{summary}</div>
        </div>""", unsafe_allow_html=True)

with col_profile:
    st.markdown('<div class="section-title">🎓 English Profile</div>', unsafe_allow_html=True)
    eng_level = profile.get("english_level")
    eng_weak  = profile.get("english_weak")
    level_colors = {"A1": "#6EE7B7", "A2": "#34D399", "B1": "#38BDF8",
                    "B2": "#818CF8", "C1": "#C4A8FF", "C2": "#F472B6"}
    lc = level_colors.get(eng_level, "#6A5FA0")
    if eng_level:
        weak_html = (f'<div style="margin-top:0.6rem; font-size:0.82rem; color:#8B7EC0;">'
                     f'Focus: <span style="color:{lc}; font-weight:700;">{eng_weak.capitalize()}</span></div>'
                     if eng_weak else "")
        st.markdown(f"""
        <div class="profile-card">
            <div style="display:flex; align-items:center; gap:14px;">
                <div style="background:{lc}22; border:2px solid {lc}; border-radius:14px;
                             padding:6px 18px; font-family:Space Grotesk,sans-serif;
                             font-weight:800; font-size:1.6rem; color:{lc};
                             box-shadow: 0 0 20px {lc}33;">{eng_level}</div>
                <div>
                    <div style="color:#D0C0F8; font-size:0.9rem; font-weight:600;">CEFR Level</div>
                    <div style="color:#6A5FA0; font-size:0.75rem; margin-top:2px;">English assessment</div>
                </div>
            </div>
            {weak_html}
            <div style="color:#2A2050; font-size:0.7rem; margin-top:12px;">Update via /level in the bot</div>
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="profile-card" style="text-align:center; padding:1.2rem 1rem;">
            <div style="font-size:2.5rem;">🎓</div>
            <div style="color:#8B7EC0; font-size:0.9rem; margin-top:0.5rem; font-weight:600;">Set your level!</div>
            <div style="color:#4A3F7A; font-size:0.8rem; margin-top:0.3rem;">Send /level to @MyEnglishBro_bot</div>
        </div>""", unsafe_allow_html=True)

# Forecast
if not df.empty and len(df) >= 3:
    last_7 = df[df["status"] == "PASS"].tail(7)
    avg_daily_xp = last_7["day_xp"].mean() if not last_7.empty else 0
    if avg_daily_xp > 0:
        next_level_xp = next((t for t in OVERALL_LEVEL_XP if t > stats["total_xp"]), None)
        if next_level_xp:
            days_to   = int((next_level_xp - stats["total_xp"]) / avg_daily_xp)
            reach_date = date.today() + timedelta(days=days_to)
            st.markdown(f"""
            <div class="forecast-bar">
                <span style="font-size:1.4rem;">🔮</span>
                <span style="color:#9080C8; font-size:0.88rem;">
                    Avg pace: <b style="color:#C4A8FF">{avg_daily_xp:.0f} XP/day</b>
                    &nbsp;→&nbsp; <b style="color:#22C55E">Level {level+1}</b> in
                    <b style="color:#C4A8FF">{days_to} days</b>
                    <span style="color:#4A3F7A;"> ({reach_date.strftime('%d %b %Y')})</span>
                </span>
            </div>""", unsafe_allow_html=True)

st.markdown("---")

# ── XP Chart + Radar ──────────────────────────────────────────────────────────
col_left, col_right = st.columns([3, 2])

with col_left:
    title_period = f" · {month_sel}" if month_sel != "All time" else ""
    st.markdown(f'<div class="section-title">📈 XP History{title_period}</div>', unsafe_allow_html=True)
    if not chart_df.empty:
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        pass_df = chart_df[chart_df["status"] == "PASS"]
        fail_df = chart_df[chart_df["status"] == "FAIL"]

        # Gradient-ish bars for PASS
        fig.add_trace(go.Bar(
            x=pass_df["log_date"], y=pass_df["day_xp"],
            name="Daily XP",
            marker=dict(color=pass_df["day_xp"], colorscale=[[0,"#3D1E8A"],[0.5,"#7B6CF6"],[1,"#C4A8FF"]],
                        opacity=0.9, showscale=False),
        ), secondary_y=False)
        if not fail_df.empty:
            fig.add_trace(go.Bar(
                x=fail_df["log_date"], y=[max(pass_df["day_xp"].max() * 0.05, 5)] * len(fail_df),
                name="FAIL", marker_color="#F87171", opacity=0.5,
            ), secondary_y=False)

        # Cumulative XP line
        fig.add_trace(go.Scatter(
            x=chart_df["log_date"], y=chart_df["total_xp"],
            name="Total XP",
            line=dict(color="#C4A8FF", width=2.5, shape="spline", smoothing=0.3),
            mode="lines",
            fill="tozeroy", fillcolor="rgba(196,168,255,0.06)",
        ), secondary_y=True)

        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(20,14,42,0.6)",
            font=dict(color="#6A5FA0", family="Inter"),
            legend=dict(bgcolor="rgba(26,19,64,0.8)", bordercolor="#3A2D72",
                        font=dict(color="#8B7EC0", size=11)),
            margin=dict(l=8, r=8, t=8, b=8), height=290,
            xaxis=dict(gridcolor="rgba(30,23,72,0.5)", showgrid=True, tickformat="%d.%m"),
            yaxis=dict(gridcolor="rgba(30,23,72,0.5)", title="Daily XP", title_font_color="#4A3F7A"),
            yaxis2=dict(gridcolor="rgba(30,23,72,0)", title="Total XP",
                        overlaying="y", side="right", title_font_color="#4A3F7A"),
            barmode="overlay",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No data yet. Start with /checkin in the bot.")

with col_right:
    st.markdown('<div class="section-title">🕸 Skill Radar</div>', unsafe_allow_html=True)
    skill_xp_vals = [chart_stats["skill_xp"][k] for k in SKILL_KEYS]
    fig2 = go.Figure(go.Scatterpolar(
        r=skill_xp_vals + [skill_xp_vals[0]],
        theta=SKILL_LABELS + [SKILL_LABELS[0]],
        fill="toself",
        fillcolor="rgba(123, 108, 246, 0.18)",
        line=dict(color="#7B6CF6", width=2.5),
        marker=dict(color="#C4A8FF", size=7, symbol="circle",
                    line=dict(color="#7B6CF6", width=2)),
    ))
    fig2.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        polar=dict(
            bgcolor="rgba(20,14,42,0.6)",
            radialaxis=dict(visible=True, gridcolor="rgba(34,23,72,0.6)",
                            color="#4A3F7A", showticklabels=False),
            angularaxis=dict(gridcolor="rgba(34,23,72,0.4)", color="#C4A8FF",
                             tickfont=dict(size=12, color="#A090D8")),
        ),
        showlegend=False, margin=dict(l=22, r=22, t=22, b=22), height=290,
    )
    st.plotly_chart(fig2, use_container_width=True)

# ── Activity Calendar + Skill Bars ────────────────────────────────────────────
col_heat, col_bars = st.columns([3, 2])

with col_heat:
    st.markdown('<div class="section-title">📅 Activity Heatmap</div>', unsafe_allow_html=True)
    if not chart_df.empty:
        df_h = chart_df.copy()
        df_h["week"] = df_h["log_date"].dt.isocalendar().week
        df_h["dow"]  = df_h["log_date"].dt.dayofweek
        df_h["color_val"] = df_h.apply(
            lambda r: r["day_xp"] if r["status"] == "PASS" else -8, axis=1)
        df_h["label"] = df_h.apply(
            lambda r: f"{r['log_date'].strftime('%d %b')} · {r['status']} · {r['day_xp']:.0f} XP · 🔥{r['streak']}",
            axis=1)
        max_xp = max(df_h["color_val"].max(), 60)
        fig3 = go.Figure(go.Heatmap(
            x=df_h["week"], y=df_h["dow"],
            z=df_h["color_val"], text=df_h["label"],
            hovertemplate="%{text}<extra></extra>",
            colorscale=[
                [0.00, "#2D0808"], [0.10, "#2D0808"],
                [0.10, "#140E2A"], [0.30, "#2D1E5A"],
                [0.60, "#5B3DAA"], [1.00, "#C4A8FF"],
            ],
            zmin=-10, zmax=max_xp, showscale=False, xgap=4, ygap=4,
        ))
        fig3.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            yaxis=dict(tickvals=list(range(7)),
                       ticktext=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                       color="#4A3F7A", gridcolor="rgba(0,0,0,0)"),
            xaxis=dict(title="Week →", color="#4A3F7A", gridcolor="rgba(0,0,0,0)"),
            margin=dict(l=38, r=10, t=8, b=28), height=240,
        )
        st.plotly_chart(fig3, use_container_width=True)

with col_bars:
    st.markdown('<div class="section-title">📊 Skill Progress</div>', unsafe_allow_html=True)
    skill_levs = [skill_level(chart_stats["skill_xp"][k]) for k in SKILL_KEYS]

    week_start = date.today() - timedelta(days=date.today().weekday())
    prev_start = week_start - timedelta(days=7)
    if not chart_df.empty:
        this_wdf = chart_df[chart_df["log_date"] >= pd.Timestamp(week_start)]
        prev_wdf = chart_df[(chart_df["log_date"] >= pd.Timestamp(prev_start)) &
                             (chart_df["log_date"] < pd.Timestamp(week_start))]
        def wk_xp(wdf, col, w):
            return float(wdf[wdf["status"] == "PASS"][col].sum()) * w
        this_w = [wk_xp(this_wdf,"duo_xp",1), wk_xp(this_wdf,"reading_pages",3),
                  wk_xp(this_wdf,"listening_min",0.5), wk_xp(this_wdf,"speaking_sessions",5),
                  wk_xp(this_wdf,"srs_reviews",1), wk_xp(this_wdf,"writing_min",2)]
        prev_w = [wk_xp(prev_wdf,"duo_xp",1), wk_xp(prev_wdf,"reading_pages",3),
                  wk_xp(prev_wdf,"listening_min",0.5), wk_xp(prev_wdf,"speaking_sessions",5),
                  wk_xp(prev_wdf,"srs_reviews",1), wk_xp(prev_wdf,"writing_min",2)]
        trends = ["↑" if t > p else ("↓" if t < p else "→") for t, p in zip(this_w, prev_w)]
        trend_c = ["#22C55E" if t == "↑" else ("#F87171" if t == "↓" else "#6A5FA0") for t in trends]
    else:
        trends = ["→"] * 6
        trend_c = ["#6A5FA0"] * 6

    for i, (em, label, key, color, lv, tr, tc) in enumerate(
        zip(SKILL_EMOJIS, SKILL_LABELS, SKILL_KEYS, SKILL_COLORS, skill_levs, trends, trend_c)
    ):
        xp = chart_stats["skill_xp"][key]
        if lv >= len(SKILL_LEVEL_XP) - 1:
            pct_s = 1.0
        else:
            lo = SKILL_LEVEL_XP[lv]
            hi = SKILL_LEVEL_XP[lv + 1]
            pct_s = (xp - lo) / (hi - lo) if hi > lo else 1.0
        pct_s = min(max(pct_s, 0), 1)
        st.markdown(f"""
        <div style="margin-bottom:10px;">
            <div style="display:flex; justify-content:space-between; align-items:center;
                         font-size:0.82rem; margin-bottom:3px;">
                <span style="color:#C0B0E8; font-weight:500;">{em} {label}
                    <span style="color:#4A3F7A; font-weight:400; font-size:0.72rem;"> Lv{lv}</span>
                </span>
                <span style="color:{tc}; font-size:0.8rem; font-weight:700;">{tr}
                    <span style="color:#4A3F7A; font-weight:400; font-size:0.7rem;"> {xp:.0f} XP</span>
                </span>
            </div>
            <div style="background:rgba(20,14,42,0.8); border-radius:100px; height:8px;
                         border:1px solid rgba(58,45,114,0.3); overflow:hidden;">
                <div style="height:100%; border-radius:100px; width:{int(pct_s*100)}%;
                             background:linear-gradient(90deg, {color}80, {color});
                             box-shadow: 0 0 8px {color}44;"></div>
            </div>
        </div>""", unsafe_allow_html=True)

st.markdown("---")

# ── Quests + Achievements ──────────────────────────────────────────────────────
col_q, col_a = st.columns([1, 1])

with col_q:
    week_num = min(4, (date.today().day - 1) // 7 + 1)
    st.markdown(f'<div class="section-title">📋 Weekly Quests · Week {week_num}</div>', unsafe_allow_html=True)
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
        wk_stats = {k: 0 for k in ["duo_days","reading_pages","listening_minutes",
                                    "speaking_sessions","srs_reviews","writing_essays"]}

    for name, key, target in WEEKLY_QUESTS.get(week_num, WEEKLY_QUESTS[4]):
        current = wk_stats.get(key, 0)
        pct = min(current / target, 1.0)
        done = pct >= 1.0
        bar_clr = "#22C55E" if done else ("#7B6CF6" if pct >= 0.5 else "#4A3F7A")
        icon = "✅" if done else ("🔄" if pct > 0 else "⬜")
        st.markdown(f"""
        <div style="margin-bottom:10px;">
            <div style="display:flex; justify-content:space-between; align-items:center;
                         font-size:0.83rem; margin-bottom:3px;">
                <span style="color:#C0B0E8;">{icon} {name}</span>
                <span style="color:{bar_clr}; font-weight:600;">{current} / {target}</span>
            </div>
            <div style="background:rgba(20,14,42,0.8); border-radius:100px; height:8px;
                         border:1px solid rgba(58,45,114,0.3); overflow:hidden;">
                <div style="height:100%; border-radius:100px; width:{int(pct*100)}%;
                             background:linear-gradient(90deg, #3D1E8A, {bar_clr});
                             box-shadow: 0 0 6px {bar_clr}44;"></div>
            </div>
        </div>""", unsafe_allow_html=True)

with col_a:
    st.markdown('<div class="section-title">🏆 Achievements</div>', unsafe_allow_html=True)
    unlocked_list, locked_list = [], []
    for ach_id, name, emoji, condition in ACHIEVEMENTS:
        try:
            (unlocked_list if condition(stats) else locked_list).append((emoji, name))
        except Exception:
            locked_list.append((emoji, name))

    for emoji, name in unlocked_list:
        st.markdown(f"""
        <div class="ach-unlocked">
            <span style="font-size:1.15rem">{emoji}</span>
            <span style="font-weight:600;">{name}</span>
            <span style="margin-left:auto; color:#A880FF; font-size:0.75rem;">✨</span>
        </div>""", unsafe_allow_html=True)

    if locked_list:
        st.markdown(
            f'<div style="color:#2D2560; font-size:0.7rem; margin:8px 0 5px;">🔒 {len(locked_list)} locked</div>',
            unsafe_allow_html=True
        )
        lk_cols = st.columns(2)
        for i, (emoji, name) in enumerate(locked_list[:8]):
            lk_cols[i % 2].markdown(f"""
            <div class="ach-locked">
                <span style="opacity:0.2">{emoji}</span>
                <span>{name}</span>
            </div>""", unsafe_allow_html=True)

# ── Harvi's Memory ─────────────────────────────────────────────────────────────
if memories:
    st.markdown("---")
    st.markdown('<div class="section-title">🧠 Harvi\'s Memory</div>', unsafe_allow_html=True)

    cat_meta = {
        "progress": ("📊", "#38BDF8"),
        "goals":    ("🎯", "#C4A8FF"),
        "habits":   ("📅", "#34D399"),
        "personal": ("👤", "#F472B6"),
        "problems": ("⚠️", "#FBBF24"),
        "general":  ("💡", "#A78BFA"),
    }
    by_cat: dict = {}
    for m in memories:
        cat = m.get("category", "general").lower()
        by_cat.setdefault(cat, []).append(m["value"])

    order = ["progress", "goals", "habits", "personal", "problems", "general"]
    active_cats = [c for c in order if c in by_cat]
    if active_cats:
        mem_cols = st.columns(min(len(active_cats), 3))
        for ci, cat in enumerate(active_cats):
            icon, color = cat_meta.get(cat, ("💬", "#6A5FA0"))
            items = by_cat[cat]
            with mem_cols[ci % len(mem_cols)]:
                st.markdown(
                    f'<div class="memory-category" style="color:{color};">{icon} {cat.capitalize()}</div>',
                    unsafe_allow_html=True
                )
                for val in items[:4]:
                    st.markdown(
                        f'<div class="memory-card">• {val}</div>',
                        unsafe_allow_html=True
                    )
    st.markdown(
        f'<div style="color:#2A2050; font-size:0.7rem; margin-top:4px;">'
        f'🧠 {len(memories)} memories · updates after conversations · /forget to clear</div>',
        unsafe_allow_html=True
    )

# ── Footer ─────────────────────────────────────────────────────────────────────
st.markdown("---")
fc, _, ft = st.columns([1, 3, 1])
with fc:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()
with ft:
    st.markdown(
        f'<div style="color:#1A1440; font-size:0.7rem; text-align:right;">'
        f'Auto-refresh 60s · {date.today().strftime("%d.%m.%Y")}</div>',
        unsafe_allow_html=True
    )

time.sleep(60)
st.cache_data.clear()
st.rerun()
