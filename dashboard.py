import sqlite3, os, time, base64, json
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from datetime import date, datetime, timedelta

DB_PATH    = os.path.join(os.path.dirname(__file__), "english_rpg.db")
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")

# ── Supabase ──────────────────────────────────────────────────────────────────
def _get_secret(k):
    v = os.getenv(k, "")
    if v: return v
    try: return st.secrets.get(k, "")
    except: return ""

_SUPABASE_URL = _get_secret("SUPABASE_URL")
_SUPABASE_KEY = _get_secret("SUPABASE_KEY")
_supa = None
if _SUPABASE_URL and _SUPABASE_KEY:
    try:
        from supabase import create_client
        _supa = create_client(_SUPABASE_URL, _SUPABASE_KEY)
    except: pass

# ── Constants ─────────────────────────────────────────────────────────────────
XP_WEIGHTS   = {"duolingo":.5,"reading":3.,"listening":.5,"speaking":5.,"srs":1.,"writing":2.}
SKILL_LVL_XP = [0,50,150,350,700,1200,2000]
TOTAL_LVL_XP = [0,100,300,700,1500,3000,6000,10000]
SKILL_KEYS   = ["duolingo","reading","listening","speaking","srs","writing"]
SKILL_LABELS = ["Duolingo","Reading","Listening","Speaking","SRS","Writing"]
SKILL_EMOJIS = ["📱","📖","🎧","🗣","🃏","✍️"]
SKILL_COLORS = ["#00C8FF","#00FFB3","#7B6CF6","#FF6B9D","#FFB800","#FF8C42"]

# ── Data ──────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=30)
def load_data():
    if _supa:
        try:
            r = _supa.table("english_daily_log").select(
                "log_date,duo_xp,reading_pages,listening_min,speaking_sessions,"
                "srs_reviews,writing_min,raw_xp,total_xp,streak,multiplier,status,penalty"
            ).order("log_date").execute()
            df = pd.DataFrame(r.data)
            if not df.empty:
                df["log_date"] = pd.to_datetime(df["log_date"])
                df["day_xp"] = df.apply(lambda r: r["raw_xp"]*r["multiplier"] if r["status"]=="PASS" else 0, axis=1)
            return df
        except: pass
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("""SELECT log_date,duo_xp,reading_pages,listening_min,
        speaking_sessions,srs_reviews,writing_min,raw_xp,total_xp,streak,multiplier,status,penalty
        FROM daily_log ORDER BY log_date""", conn)
    conn.close()
    if df.empty: return df
    df["log_date"] = pd.to_datetime(df["log_date"])
    df["day_xp"] = df.apply(lambda r: r["raw_xp"]*r["multiplier"] if r["status"]=="PASS" else 0, axis=1)
    return df

@st.cache_data(ttl=120)
def load_memories():
    if not _supa: return []
    try:
        return _supa.table("english_memory").select("category,value").order("updated_at",desc=True).limit(20).execute().data or []
    except: return []

@st.cache_data(ttl=60)
def load_profile():
    keys = ["english_level","english_weak"]
    if _supa:
        try:
            r = _supa.table("english_config").select("key,value").in_("key",keys).execute()
            return {row["key"]:row["value"] for row in r.data}
        except: pass
    try:
        conn = sqlite3.connect(DB_PATH)
        out = {}
        for k in keys:
            row = conn.execute("SELECT value FROM config WHERE key=?",(k,)).fetchone()
            out[k] = row[0] if row else None
        conn.close()
        return out
    except: return {}

def get_stats(df):
    empty = {"total_xp":0,"total_days":0,"max_streak":0,"current_streak":0,
             "reading_pages":0,"listening_minutes":0,"speaking_sessions":0,
             "srs_reviews":0,"duo_days":0,"level":1,
             "skill_xp":{k:0. for k in SKILL_KEYS}}
    if df.empty: return empty
    p = df[df["status"]=="PASS"]
    s = {
        "total_xp":       float(df["total_xp"].iloc[-1]),
        "total_days":     len(p),
        "max_streak":     int(df["streak"].max()),
        "current_streak": int(df["streak"].iloc[-1]),
        "reading_pages":  int(p["reading_pages"].sum()),
        "listening_minutes": int(p["listening_min"].sum()),
        "speaking_sessions": int(p["speaking_sessions"].sum()),
        "srs_reviews":    int(p["srs_reviews"].sum()),
        "duo_days":       int((p["duo_xp"]>0).sum()),
        "skill_xp": {
            "duolingo":  float(p["duo_xp"].sum()           * XP_WEIGHTS["duolingo"]),
            "reading":   float(p["reading_pages"].sum()     * XP_WEIGHTS["reading"]),
            "listening": float(p["listening_min"].sum()     * XP_WEIGHTS["listening"]),
            "speaking":  float(p["speaking_sessions"].sum() * XP_WEIGHTS["speaking"]),
            "srs":       float(p["srs_reviews"].sum()       * XP_WEIGHTS["srs"]),
            "writing":   float(p["writing_min"].sum()       * XP_WEIGHTS["writing"]),
        },
    }
    lv = 1
    for i,t in enumerate(TOTAL_LVL_XP):
        if s["total_xp"] >= t: lv = i+1
    s["level"] = lv
    return s

def lvl_progress(xp):
    lv = 1
    for i,t in enumerate(TOTAL_LVL_XP):
        if xp >= t: lv = i+1
    lo = TOTAL_LVL_XP[min(lv-1, len(TOTAL_LVL_XP)-1)]
    hi = TOTAL_LVL_XP[min(lv,   len(TOTAL_LVL_XP)-1)]
    pct = (xp-lo)/(hi-lo) if hi>lo else 1.
    return lv, min(pct,1.)

def skill_lv(xp):
    for i,t in enumerate(reversed(SKILL_LVL_XP)):
        if xp >= t: return len(SKILL_LVL_XP)-1-i
    return 0

def load_img_b64(name="cat_main.png"):
    p = os.path.join(ASSETS_DIR, name)
    if os.path.exists(p):
        with open(p,"rb") as f: return base64.b64encode(f.read()).decode()
    return None

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="Harvi — English Bro", layout="wide", page_icon="😺")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Inter:wght@400;500;600;700&display=swap');

/* ── Base ── */
.stApp { background: #080D1A; }
html,body,[class*="css"]{ font-family:'Inter',sans-serif; }
section[data-testid="stSidebar"]{ background:#060B14!important; border-right:1px solid #0D2030; }
hr{ border-color:#0D2030!important; margin:1.2rem 0!important; }
::-webkit-scrollbar{ width:4px; }
::-webkit-scrollbar-thumb{ background:#0D2030; border-radius:2px; }

/* ── Page title ── */
.page-title{
    font-family:'Orbitron',sans-serif;
    font-size:clamp(1.4rem,3vw,2rem);
    font-weight:900;
    color:#00C8FF;
    text-align:center;
    text-shadow:0 0 20px rgba(0,200,255,.5);
    letter-spacing:3px;
    margin:0;
    padding:0;
}
.page-title-border{
    border:1px solid #0D2A3A;
    border-top:2px solid #00C8FF;
    border-radius:0 0 8px 8px;
    padding:.6rem 2rem .5rem;
    background:linear-gradient(180deg,rgba(0,200,255,.05),transparent);
    margin-bottom:1.2rem;
    text-align:center;
    position:relative;
}
.page-title-border::before,.page-title-border::after{
    content:'◆';
    position:absolute;
    top:6px;
    color:#00C8FF;
    font-size:.6rem;
    opacity:.6;
}
.page-title-border::before{ left:12px; }
.page-title-border::after{  right:12px; }

/* ── Cat circle ── */
.cat-ring{
    width:100%;
    aspect-ratio:1;
    border-radius:50%;
    border:2px solid #00C8FF;
    box-shadow:0 0 20px rgba(0,200,255,.4),0 0 40px rgba(0,200,255,.15);
    overflow:hidden;
    background:#0D1A28;
    display:flex;
    align-items:center;
    justify-content:center;
    font-size:3.5rem;
}

/* ── Today status banner ── */
.today-pass{
    background:linear-gradient(135deg,rgba(0,255,100,.06),rgba(0,255,100,.02));
    border:1px solid rgba(0,255,150,.3);
    border-left:3px solid #00FF96;
    border-radius:10px;
    padding:.7rem 1rem;
    margin-bottom:.8rem;
}
.today-fail{
    background:linear-gradient(135deg,rgba(255,60,60,.06),rgba(255,60,60,.02));
    border:1px solid rgba(255,80,80,.3);
    border-left:3px solid #FF4D6A;
    border-radius:10px;
    padding:.7rem 1rem;
    margin-bottom:.8rem;
}
.today-pending{
    background:linear-gradient(135deg,rgba(255,180,0,.06),rgba(255,180,0,.02));
    border:1px solid rgba(255,180,0,.3);
    border-left:3px solid #FFB800;
    border-radius:10px;
    padding:.7rem 1rem;
    margin-bottom:.8rem;
}

/* ── KPI card (reference style) ── */
.kpi{
    background:#0A1220;
    border:1px solid #0D2035;
    border-radius:8px;
    padding:1rem .8rem .8rem;
    text-align:center;
    position:relative;
    overflow:hidden;
}
.kpi::before{
    content:'';
    position:absolute;
    top:0;left:0;right:0;
    height:2px;
    background:linear-gradient(90deg,transparent,#00C8FF,transparent);
}
.kpi-val{
    font-family:'Orbitron',sans-serif;
    font-size:1.8rem;
    font-weight:700;
    color:#00C8FF;
    line-height:1;
    white-space:nowrap;
}
.kpi-label{
    font-size:.6rem;
    color:#1E4060;
    text-transform:uppercase;
    letter-spacing:2px;
    margin-top:.4rem;
    font-weight:600;
}

/* ── Section header ── */
.sec{
    font-family:'Orbitron',sans-serif;
    font-size:.65rem;
    color:#1A4060;
    text-transform:uppercase;
    letter-spacing:3px;
    border-bottom:1px solid #0D2030;
    padding-bottom:.5rem;
    margin-bottom:.9rem;
    display:flex;
    align-items:center;
    gap:.5rem;
}
.sec::before{ content:'▶'; color:#00C8FF; font-size:.5rem; }

/* ── Skill bar ── */
.skill-row{ margin-bottom:11px; }
.skill-meta{
    display:flex;
    justify-content:space-between;
    font-size:.78rem;
    margin-bottom:3px;
    color:#6A8AA8;
}
.skill-name{ color:#C8DCF0; font-weight:500; }
.skill-track{
    background:#0A1220;
    border-radius:100px;
    height:7px;
    border:1px solid #0D2035;
    overflow:hidden;
}
.skill-fill{
    height:100%;
    border-radius:100px;
}

/* ── Waffle ── */
.waffle-grid{
    display:flex;
    flex-wrap:wrap;
    gap:3px;
    margin-top:.5rem;
}
.waffle-cell{
    width:14px;
    height:14px;
    border-radius:3px;
}

/* ── Memory pill ── */
.mem-pill{
    display:inline-block;
    background:rgba(0,200,255,.06);
    border:1px solid rgba(0,200,255,.15);
    border-radius:20px;
    padding:3px 10px;
    font-size:.75rem;
    color:#4A7A9A;
    margin:3px 3px 0 0;
}

/* ── Metric overrides ── */
div[data-testid="stMetric"]{
    background:#0A1220!important;
    border-radius:8px!important;
    padding:10px!important;
    border:1px solid #0D2035!important;
}
div[data-testid="stMetricValue"]{ color:#00C8FF!important; }

/* ── Button ── */
.stButton>button{
    background:#0D2035!important;
    border:1px solid #00C8FF!important;
    color:#00C8FF!important;
    border-radius:6px!important;
    font-size:.8rem!important;
    font-family:'Orbitron',sans-serif!important;
    letter-spacing:1px!important;
}
.stButton>button:hover{
    background:rgba(0,200,255,.1)!important;
    box-shadow:0 0 12px rgba(0,200,255,.3)!important;
}
</style>
""", unsafe_allow_html=True)

# ── Load ──────────────────────────────────────────────────────────────────────
df       = load_data()
stats    = get_stats(df)
level, level_pct = lvl_progress(stats["total_xp"])
profile  = load_profile()
memories = load_memories()
cat_b64  = load_img_b64("cat_main.png")

today_str  = date.today().isoformat()
today_rows = df[df["log_date"]==pd.Timestamp(today_str)] if not df.empty else pd.DataFrame()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<p style="color:#00C8FF;font-family:Orbitron,sans-serif;font-size:.8rem;letter-spacing:2px;margin-bottom:8px;">◆ PERIOD</p>', unsafe_allow_html=True)
    if not df.empty:
        periods = sorted(df["log_date"].dt.to_period("M").unique(), reverse=True)
        labels  = ["All time"] + [p.strftime("%B %Y") for p in periods]
        sel     = st.selectbox("", labels, index=0, label_visibility="collapsed")
        if sel != "All time":
            sp = next(p for p in periods if p.strftime("%B %Y")==sel)
            chart_df    = df[df["log_date"].dt.to_period("M")==sp].copy()
            chart_stats = get_stats(chart_df)
        else:
            chart_df, chart_stats = df.copy(), stats
    else:
        sel, chart_df, chart_stats = "All time", df.copy(), stats

    st.markdown("---")
    st.markdown("""
    <div style="font-size:.75rem;color:#1A4060;line-height:2;">
    <span style="color:#00C8FF;">/checkin</span> — daily log<br>
    <span style="color:#00C8FF;">/stats</span> — progress<br>
    <span style="color:#00C8FF;">/talk</span> — speak practice<br>
    <span style="color:#00C8FF;">/memory</span> — what Harvi knows<br>
    <span style="color:#00C8FF;">/skilltree</span> — skill levels
    </div>""", unsafe_allow_html=True)
    st.markdown('<p style="margin-top:1rem;font-size:.7rem;color:#0D2030;">@MyEnglishBro_bot</p>', unsafe_allow_html=True)

# ── PAGE TITLE ────────────────────────────────────────────────────────────────
st.markdown("""
<div class="page-title-border">
    <div class="page-title">HARVI — ENGLISH BRO</div>
    <div style="color:#1A4060;font-size:.65rem;letter-spacing:3px;margin-top:4px;">ENGLISH PROGRESS DASHBOARD</div>
</div>
""", unsafe_allow_html=True)

# ── HERO ROW — cat + today + KPIs ────────────────────────────────────────────
col_cat, col_main = st.columns([1, 4])

with col_cat:
    if cat_b64:
        st.markdown(f'<div class="cat-ring"><img src="data:image/png;base64,{cat_b64}" style="width:100%;height:100%;object-fit:cover;"></div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="cat-ring">😺</div>', unsafe_allow_html=True)
    eng_level = profile.get("english_level", "—")
    st.markdown(f'<div style="text-align:center;margin-top:.5rem;"><span style="background:rgba(0,200,255,.1);border:1px solid rgba(0,200,255,.3);border-radius:6px;padding:3px 12px;font-family:Orbitron,sans-serif;font-size:.85rem;color:#00C8FF;font-weight:700;">{eng_level}</span></div>', unsafe_allow_html=True)

with col_main:
    # Today status
    if today_rows.empty:
        hour_now = datetime.now().hour
        if hour_now >= 20:
            cls, color, icon, msg = "today-pending", "#FF4D6A", "🚨", f"URGENT — {date.today().strftime('%d %b')} · Check-in before midnight!"
        else:
            cls, color, icon, msg = "today-pending", "#FFB800", "📋", f"{date.today().strftime('%A, %d %b')} · No check-in yet"
        st.markdown(f'<div class="{cls}"><span style="color:{color};font-weight:700;font-size:.95rem;">{icon} {msg}</span><br><span style="color:#2A4A6A;font-size:.8rem;">Open @MyEnglishBro_bot → /checkin</span></div>', unsafe_allow_html=True)
    else:
        row = today_rows.iloc[-1]
        is_pass = row["status"] == "PASS"
        cls = "today-pass" if is_pass else "today-fail"
        color = "#00FF96" if is_pass else "#FF4D6A"
        icon = "✅" if is_pass else "❌"
        parts = []
        if row["duo_xp"]>0:            parts.append(f"📱 +{row['duo_xp']:.0f}")
        if row["reading_pages"]>0:     parts.append(f"📖 {row['reading_pages']}p")
        if row["listening_min"]>0:     parts.append(f"🎧 {row['listening_min']}min")
        if row["speaking_sessions"]>0: parts.append(f"🗣 {row['speaking_sessions']}x")
        if row["srs_reviews"]>0:       parts.append(f"🃏 {row['srs_reviews']}")
        if row["writing_min"]>0:       parts.append(f"✍️ {row['writing_min']}min")
        summary = "  ·  ".join(parts) or "—"
        mult = f'<span style="color:#00FFB3;font-size:.75rem;margin-left:.5rem;">×{row["multiplier"]:.1f} streak bonus</span>' if row["multiplier"]>1 else ""
        st.markdown(f'''<div class="{cls}">
            <span style="color:{color};font-weight:700;font-size:1rem;">{icon} {row["status"]}</span>{mult}
            <span style="float:right;color:{color};font-family:Orbitron,sans-serif;font-size:1.2rem;font-weight:700;">+{row["day_xp"]:.0f} XP</span>
            <br><span style="color:#2A5A4A;font-size:.8rem;">{summary}</span>
        </div>''', unsafe_allow_html=True)

    # 4 KPI boxes
    k1,k2,k3,k4 = st.columns(4)
    streak_ico = "🔥" if stats["current_streak"]>=3 else ("⚡" if stats["current_streak"]>0 else "💔")
    for col, val, label in [
        (k1, f"{streak_ico} {stats['current_streak']}", "STREAK"),
        (k2, f"{stats['total_xp']:.0f}", "TOTAL XP"),
        (k3, f"LV {level}", "LEVEL"),
        (k4, str(stats["total_days"]), "PASS DAYS"),
    ]:
        col.markdown(f'<div class="kpi"><div class="kpi-val">{val}</div><div class="kpi-label">{label}</div></div>', unsafe_allow_html=True)

# ── LEVEL PROGRESS BAR ────────────────────────────────────────────────────────
pct_int = int(level_pct*100)
hi_xp = TOTAL_LVL_XP[min(level, len(TOTAL_LVL_XP)-1)]
st.markdown(f"""
<div style="display:flex;justify-content:space-between;font-size:.72rem;color:#1A4060;margin:.8rem 0 4px;font-family:'Orbitron',sans-serif;letter-spacing:1px;">
    <span>LEVEL {level}</span>
    <span style="color:#00C8FF;">{pct_int}% → LEVEL {level+1} &nbsp;·&nbsp; {stats['total_xp']:.0f} / {hi_xp} XP</span>
</div>
<div style="background:#0A1220;border:1px solid #0D2035;border-radius:100px;height:10px;overflow:hidden;">
    <div style="height:100%;width:{pct_int}%;border-radius:100px;
                background:linear-gradient(90deg,#0047FF,#00C8FF);
                box-shadow:0 0 10px rgba(0,200,255,.6);"></div>
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# ── 3 DONUT RING CHARTS ───────────────────────────────────────────────────────
st.markdown('<div class="sec">PERFORMANCE RINGS</div>', unsafe_allow_html=True)
d1, d2, d3 = st.columns(3)

def make_ring(value_pct, label, center_text, color, bg="#0A1220"):
    val = min(max(value_pct, 0), 1)
    fig = go.Figure(go.Pie(
        values=[val, 1-val],
        hole=0.72,
        sort=False,
        marker=dict(colors=[color, "#0D1E2A"], line=dict(width=0)),
        textinfo="none",
        hoverinfo="skip",
    ))
    fig.add_annotation(
        text=f"<b>{center_text}</b>",
        x=0.5, y=0.55, xref="paper", yref="paper",
        font=dict(size=22, color=color, family="Orbitron"),
        showarrow=False,
    )
    fig.add_annotation(
        text=label,
        x=0.5, y=0.35, xref="paper", yref="paper",
        font=dict(size=10, color="#1A4060", family="Inter"),
        showarrow=False,
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False, margin=dict(l=10,r=10,t=10,b=10), height=160,
    )
    return fig

# Ring 1: Level progress
with d1:
    st.plotly_chart(make_ring(level_pct, f"Level {level} → {level+1}", f"{int(level_pct*100)}%", "#00C8FF"), use_container_width=True)

# Ring 2: Weekly XP goal (target: 100 XP/week)
week_start = date.today() - timedelta(days=date.today().weekday())
if not df.empty:
    wdf = df[df["log_date"]>=pd.Timestamp(week_start)]
    week_xp = float(wdf[wdf["status"]=="PASS"]["day_xp"].sum()) if not wdf.empty else 0
else:
    week_xp = 0
WEEKLY_XP_TARGET = 100
with d2:
    pct_w = week_xp / WEEKLY_XP_TARGET
    st.plotly_chart(make_ring(pct_w, "Weekly XP Goal", f"{week_xp:.0f}", "#00FFB3"), use_container_width=True)

# Ring 3: Streak vs personal record
with d3:
    max_str = max(stats["max_streak"], 1)
    pct_s = stats["current_streak"] / max_str
    st.plotly_chart(make_ring(pct_s, "Streak / Record", f"{stats['current_streak']}d", "#FFB800"), use_container_width=True)

st.markdown("---")

# ── XP HISTORY CHART ──────────────────────────────────────────────────────────
title_sfx = f" · {sel}" if sel != "All time" else ""
st.markdown(f'<div class="sec">XP HISTORY{title_sfx}</div>', unsafe_allow_html=True)

if not chart_df.empty:
    pass_df = chart_df[chart_df["status"]=="PASS"]
    fail_df = chart_df[chart_df["status"]=="FAIL"]
    from plotly.subplots import make_subplots
    fig = make_subplots(specs=[[{"secondary_y":True}]])
    fig.add_trace(go.Bar(
        x=pass_df["log_date"], y=pass_df["day_xp"],
        name="Daily XP",
        marker=dict(
            color=pass_df["day_xp"],
            colorscale=[[0,"#003A55"],[0.4,"#0080AA"],[1,"#00C8FF"]],
            showscale=False, opacity=.9,
        ),
    ), secondary_y=False)
    if not fail_df.empty:
        fig.add_trace(go.Bar(
            x=fail_df["log_date"], y=[max(pass_df["day_xp"].max()*.04,4)]*len(fail_df),
            name="FAIL", marker_color="#FF4D6A", opacity=.5,
        ), secondary_y=False)
    fig.add_trace(go.Scatter(
        x=chart_df["log_date"], y=chart_df["total_xp"],
        name="Total XP",
        line=dict(color="#00FFB3", width=2, shape="spline"),
        mode="lines",
        fill="tozeroy", fillcolor="rgba(0,255,179,.04)",
    ), secondary_y=True)
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#080E18",
        font=dict(color="#1A4060", family="Inter"),
        legend=dict(bgcolor="rgba(8,13,26,.8)", bordercolor="#0D2035", font=dict(color="#2A6080",size=11)),
        margin=dict(l=8,r=8,t=8,b=8), height=240,
        xaxis=dict(gridcolor="#0D1E2A", tickformat="%d.%m", color="#1A4060"),
        yaxis=dict(gridcolor="#0D1E2A", title="XP/day", title_font_color="#0D2A3A"),
        yaxis2=dict(gridcolor="rgba(0,0,0,0)", title="Total", overlaying="y", side="right", title_font_color="#0D2A3A"),
        barmode="overlay",
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.markdown('<p style="color:#1A4060;text-align:center;padding:2rem;">No data yet — start with /checkin in the bot</p>', unsafe_allow_html=True)

st.markdown("---")

# ── SKILL BARS + STREAK WAFFLE ────────────────────────────────────────────────
col_skills, col_streak = st.columns([3, 2])

with col_skills:
    st.markdown('<div class="sec">SKILL TREE</div>', unsafe_allow_html=True)
    week_start2 = date.today() - timedelta(days=date.today().weekday())
    prev_start  = week_start2 - timedelta(days=7)
    if not chart_df.empty:
        twdf = chart_df[chart_df["log_date"]>=pd.Timestamp(week_start2)]
        pwdf = chart_df[(chart_df["log_date"]>=pd.Timestamp(prev_start))&(chart_df["log_date"]<pd.Timestamp(week_start2))]
        def wkx(d,col,w): return float(d[d["status"]=="PASS"][col].sum())*w
        tw = [wkx(twdf,"duo_xp",.5),wkx(twdf,"reading_pages",3),wkx(twdf,"listening_min",.5),
              wkx(twdf,"speaking_sessions",5),wkx(twdf,"srs_reviews",1),wkx(twdf,"writing_min",2)]
        pw = [wkx(pwdf,"duo_xp",.5),wkx(pwdf,"reading_pages",3),wkx(pwdf,"listening_min",.5),
              wkx(pwdf,"speaking_sessions",5),wkx(pwdf,"srs_reviews",1),wkx(pwdf,"writing_min",2)]
        trends = ["↑" if t>p else("↓" if t<p else "→") for t,p in zip(tw,pw)]
        tc     = ["#00FFB3" if t=="↑" else("#FF4D6A" if t=="↓" else "#1A4060") for t in trends]
    else:
        trends,tc = ["→"]*6, ["#1A4060"]*6

    for em,label,key,color,tr,tcolor in zip(SKILL_EMOJIS,SKILL_LABELS,SKILL_KEYS,SKILL_COLORS,trends,tc):
        xp = chart_stats["skill_xp"][key]
        lv = skill_lv(xp)
        if lv >= len(SKILL_LVL_XP)-1:
            pct_sk = 1.
        else:
            lo,hi = SKILL_LVL_XP[lv],SKILL_LVL_XP[lv+1]
            pct_sk = (xp-lo)/(hi-lo) if hi>lo else 1.
        pct_sk = min(max(pct_sk,0),1)
        st.markdown(f"""
        <div class="skill-row">
            <div class="skill-meta">
                <span class="skill-name">{em} {label} <span style="color:#0D2A3A;font-size:.68rem;">LV{lv}</span></span>
                <span style="color:{tcolor};font-size:.8rem;">{tr} <span style="color:#1A4060;font-size:.7rem;">{xp:.0f} XP</span></span>
            </div>
            <div class="skill-track">
                <div class="skill-fill" style="width:{int(pct_sk*100)}%;background:linear-gradient(90deg,{color}55,{color});box-shadow:0 0 6px {color}44;"></div>
            </div>
        </div>""", unsafe_allow_html=True)

with col_streak:
    st.markdown('<div class="sec">ACTIVITY · 30 DAYS</div>', unsafe_allow_html=True)
    cells = []
    for i in range(29,-1,-1):
        d = (date.today()-timedelta(days=i)).isoformat()
        if df.empty:
            cells.append(("#0A1220","—"))
        else:
            row30 = df[df["log_date"]==pd.Timestamp(d)]
            if row30.empty:
                cells.append(("#0A1220","no data"))
            elif row30.iloc[-1]["status"]=="PASS":
                xp30 = row30.iloc[-1]["day_xp"]
                intensity = min(int(xp30/120*255),255)
                cells.append((f"rgb(0,{100+intensity//3},{intensity})","PASS"))
            else:
                cells.append(("#3A0A0A","FAIL"))

    rows_waffle = [cells[i:i+6] for i in range(0,30,6)]
    html_waffle = '<div style="display:grid;grid-template-columns:repeat(6,1fr);gap:4px;margin-top:.3rem;">'
    for cell_color, label in cells:
        html_waffle += f'<div style="height:22px;border-radius:4px;background:{cell_color};border:1px solid #0D1E2A;" title="{label}"></div>'
    html_waffle += '</div>'
    st.markdown(html_waffle, unsafe_allow_html=True)

    st.markdown(f"""
    <div style="margin-top:1rem;">
        <div style="color:#1A4060;font-size:.65rem;letter-spacing:2px;font-family:Orbitron,sans-serif;margin-bottom:.5rem;">STREAK STATS</div>
        <div style="display:flex;flex-direction:column;gap:.4rem;">
            <div style="display:flex;justify-content:space-between;font-size:.82rem;">
                <span style="color:#2A5A7A;">Current</span>
                <span style="color:#00C8FF;font-family:Orbitron,sans-serif;font-weight:700;">{stats['current_streak']}d</span>
            </div>
            <div style="display:flex;justify-content:space-between;font-size:.82rem;">
                <span style="color:#2A5A7A;">Best ever</span>
                <span style="color:#FFB800;font-family:Orbitron,sans-serif;font-weight:700;">{stats['max_streak']}d</span>
            </div>
            <div style="display:flex;justify-content:space-between;font-size:.82rem;">
                <span style="color:#2A5A7A;">PASS days</span>
                <span style="color:#00FFB3;font-family:Orbitron,sans-serif;font-weight:700;">{stats['total_days']}</span>
            </div>
            <div style="display:flex;justify-content:space-between;font-size:.82rem;">
                <span style="color:#2A5A7A;">Eng. level</span>
                <span style="color:#00C8FF;font-family:Orbitron,sans-serif;font-weight:700;">{profile.get('english_level','—')}</span>
            </div>
        </div>
    </div>""", unsafe_allow_html=True)

# ── Forecast ──────────────────────────────────────────────────────────────────
if not df.empty and len(df)>=3:
    last7 = df[df["status"]=="PASS"].tail(7)
    avg   = last7["day_xp"].mean() if not last7.empty else 0
    if avg>0:
        nxt = next((t for t in TOTAL_LVL_XP if t>stats["total_xp"]),None)
        if nxt:
            days_to = int((nxt-stats["total_xp"])/avg)
            reach   = date.today()+timedelta(days=days_to)
            st.markdown("---")
            st.markdown(f"""
            <div style="background:#090E1C;border:1px solid #0D2035;border-left:2px solid #00C8FF;
                         border-radius:8px;padding:.6rem 1rem;font-size:.82rem;">
                🔮 &nbsp; Avg pace <span style="color:#00C8FF;font-family:Orbitron,sans-serif;">{avg:.0f} XP/day</span>
                &nbsp;→&nbsp; Level {level+1} in
                <span style="color:#00FFB3;font-family:Orbitron,sans-serif;font-weight:700;">{days_to} days</span>
                <span style="color:#1A4060;"> · {reach.strftime('%d %b %Y')}</span>
            </div>""", unsafe_allow_html=True)

# ── HARVI'S MEMORY ────────────────────────────────────────────────────────────
if memories:
    st.markdown("---")
    st.markdown('<div class="sec">HARVI\'S MEMORY</div>', unsafe_allow_html=True)
    cat_colors = {"progress":"#00C8FF","goals":"#00FFB3","habits":"#FFB800","personal":"#FF6B9D","problems":"#FF4D6A","general":"#7B6CF6"}
    pills_html = ""
    for m in memories:
        cat   = m.get("category","general").lower()
        color = cat_colors.get(cat,"#2A5A7A")
        pills_html += f'<span class="mem-pill" style="border-color:{color}22;color:{color};">{m["value"]}</span>'
    st.markdown(f'<div style="line-height:2;">{pills_html}</div>', unsafe_allow_html=True)
    st.markdown(f'<p style="color:#0D2030;font-size:.65rem;margin-top:.5rem;">{len(memories)} memories · /memory for full list · /forget to clear</p>', unsafe_allow_html=True)

# ── FOOTER ────────────────────────────────────────────────────────────────────
st.markdown("---")
fc,_,ft = st.columns([1,4,1])
with fc:
    if st.button("◀◀ REFRESH"):
        st.cache_data.clear()
        st.rerun()
with ft:
    st.markdown(f'<p style="color:#0D2030;font-size:.65rem;text-align:right;font-family:Orbitron,sans-serif;">{date.today().strftime("%d.%m.%Y")}</p>', unsafe_allow_html=True)

time.sleep(60)
st.cache_data.clear()
st.rerun()
