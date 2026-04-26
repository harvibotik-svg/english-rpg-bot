import os
import sqlite3
import asyncio
import requests
import logging
from datetime import datetime, date, time as dtime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler
)

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
DUOLINGO_USERNAME = os.getenv("DUOLINGO_USERNAME", "VladimirZa405")
DB_PATH = os.path.join(os.path.dirname(__file__), "english_rpg.db")

_SUPABASE_URL = os.getenv("SUPABASE_URL", "")
_SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
_supa = None
if _SUPABASE_URL and _SUPABASE_KEY:
    try:
        from supabase import create_client
        _supa = create_client(_SUPABASE_URL, _SUPABASE_KEY)
    except Exception:
        _supa = None

EVENING_HOUR = 21
EVENING_MINUTE = 0
MIN_XP_PASS = 30
FAIL_PENALTY = 20

XP_WEIGHTS = {
    "duolingo":  1.0,
    "reading":   3.0,
    "listening": 0.5,
    "speaking":  5.0,
    "srs":       1.0,
    "writing":   2.0,
}

SKILL_LEVEL_XP = [0, 50, 150, 350, 700, 1200, 2000]

STREAK_MULTIPLIERS = [(30, 2.5), (14, 2.0), (7, 1.5), (4, 1.2), (0, 1.0)]

ACHIEVEMENTS = [
    ("first_day",        "First Day",         "🌟", lambda s: s["total_days"] >= 1),
    ("streak_3",         "3 Day Streak",       "🔥", lambda s: s["max_streak"] >= 3),
    ("streak_7",         "7 Day Streak",       "⚡", lambda s: s["max_streak"] >= 7),
    ("streak_14",        "2 Week Streak",      "💎", lambda s: s["max_streak"] >= 14),
    ("streak_30",        "30 Day Streak",      "👑", lambda s: s["max_streak"] >= 30),
    ("xp_100",           "First 100 XP",       "💯", lambda s: s["total_xp"] >= 100),
    ("xp_500",           "500 XP Club",        "🏆", lambda s: s["total_xp"] >= 500),
    ("speaking_5",       "Speaking x5",        "🗣", lambda s: s["speaking_sessions"] >= 5),
    ("reading_100",      "Reading 100 pages",  "📚", lambda s: s["reading_pages"] >= 100),
    ("srs_50",           "SRS 50 reviews",     "🃏", lambda s: s["srs_reviews"] >= 50),
    ("level_5",          "Level 5",            "⚔️", lambda s: s["level"] >= 5),
    ("consistency",      "Consistency Master", "🎯", lambda s: s["total_days"] >= 30 and s["max_streak"] >= 20),
]

WEEKLY_QUESTS = {
    1: [("Duolingo 5 дней", "duo_days", 5), ("Reading 30 стр", "reading_pages", 30),
        ("Speaking 2 сессии", "speaking_sessions", 2), ("SRS 3 карточки", "srs_reviews", 3)],
    2: [("Duolingo 6 дней", "duo_days", 6), ("Reading 50 стр", "reading_pages", 50),
        ("Listening 40 мин", "listening_minutes", 40), ("Speaking 3 сессии", "speaking_sessions", 3),
        ("SRS 5 карточек", "srs_reviews", 5)],
    3: [("Duolingo 7 дней", "duo_days", 7), ("Reading 70 стр", "reading_pages", 70),
        ("Listening 60 мин", "listening_minutes", 60), ("Speaking 4 сессии", "speaking_sessions", 4),
        ("SRS 7 карточек", "srs_reviews", 7), ("Writing 2 эссе", "writing_essays", 2)],
    4: [("Duolingo 9 дней", "duo_days", 9), ("Reading 100 стр", "reading_pages", 100),
        ("Listening 90 мин", "listening_minutes", 90), ("Speaking 5 сессий", "speaking_sessions", 5),
        ("SRS 10 карточек", "srs_reviews", 10), ("Writing 4 эссе", "writing_essays", 4)],
}

ASK_READING, ASK_LISTENING, ASK_SPEAKING, ASK_SRS, ASK_WRITING, ASK_LEVEL, ASK_WEAK = range(7)

WRITING_TOPICS = [
    "Describe your favorite place in your hometown.",
    "What is the most important quality in a friend?",
    "Do you prefer cities or the countryside? Why?",
    "Describe a memorable event from your childhood.",
    "What would you do if you had a completely free day?",
    "How can people reduce stress in modern life?",
    "What is your favorite book or movie and why?",
    "Describe a person who has influenced you greatly.",
    "Do you think technology makes us closer or more distant?",
    "What are the benefits of learning a foreign language?",
    "Describe a skill you would like to learn and why.",
    "What does 'success' mean to you personally?",
    "Describe a typical day in your life.",
    "What is the best advice you have ever received?",
    "How do you stay motivated when things get hard?",
    "Describe a time you helped someone in need.",
    "What is your favorite season and why?",
    "Do you prefer working alone or in a team?",
    "Describe a place you would like to visit someday.",
    "What makes a good leader?",
    "How has the internet changed our daily lives?",
    "Describe a hobby you enjoy and why it matters to you.",
    "What is your dream job and why?",
    "How do you celebrate important events in your life?",
    "Describe a difficult decision you had to make.",
    "What does 'happiness' mean to you?",
    "Describe a time you overcame a fear.",
    "What is the role of art in society?",
    "How can we protect the environment in daily life?",
    "Describe a lesson you learned from failure.",
    "If you could change one thing about the world, what would it be?",
    "What traditions are important in your family?",
]


def get_todays_writing_topic() -> str:
    day_of_year = date.today().timetuple().tm_yday
    return WRITING_TOPICS[day_of_year % len(WRITING_TOPICS)]


SPEAKING_PROMPTS = [
    "Talk about your best memory from childhood — 2 minutes.",
    "Describe what you did yesterday, step by step.",
    "Explain your job to someone who knows nothing about it.",
    "Talk about a movie or series you watched recently.",
    "Describe your ideal weekend — where, what, with whom.",
    "Explain why you are learning English and what it will change.",
    "Talk about a goal you have for the next 3 months.",
    "Describe your morning routine in detail.",
    "What would you do with 1 million dollars?",
    "Talk about a person you admire and why.",
    "Describe your favourite food and how to cook it.",
    "What is the biggest challenge you face right now?",
    "Talk about a place you want to visit and why.",
    "Describe a skill you want to learn this year.",
    "What do you think is the biggest problem in the world today?",
]


def get_speaking_prompt() -> str:
    day_of_year = date.today().timetuple().tm_yday
    return SPEAKING_PROMPTS[day_of_year % len(SPEAKING_PROMPTS)]


WORD_OF_DAY = [
    ("persevere",    "v.", "to continue despite difficulty",           "She persevered through every challenge."),
    ("eloquent",     "adj.", "fluent and persuasive in speech",        "His eloquent speech moved the crowd."),
    ("resilient",    "adj.", "able to recover quickly from setbacks",  "You are more resilient than you think."),
    ("procrastinate","v.", "to delay doing something",                 "Stop procrastinating — start now!"),
    ("ambitious",    "adj.", "having a strong desire to succeed",      "Ambitious people find a way."),
    ("dedication",   "n.", "commitment to a task or purpose",          "Your dedication will pay off."),
    ("consistent",   "adj.", "always behaving the same way",           "Be consistent — results follow."),
    ("momentum",     "n.", "force gained by continuous movement",      "Build momentum, day by day."),
    ("discipline",   "n.", "training to follow rules and routines",    "Discipline beats motivation every time."),
    ("fluent",       "adj.", "able to speak a language easily",        "With practice, you will be fluent."),
    ("immerse",      "v.", "to involve yourself deeply in something",  "Immerse yourself in English daily."),
    ("pronunciation","n.", "the way a word is spoken",                 "Good pronunciation takes practice."),
    ("vocabulary",   "n.", "all the words a person knows",             "A rich vocabulary opens every door."),
    ("comprehension","n.", "the ability to understand",                "Reading improves your comprehension."),
    ("articulate",   "v.", "to express clearly in words",              "He articulated his ideas perfectly."),
    ("endeavour",    "n.", "an attempt to achieve a goal",             "Learning English is a worthy endeavour."),
    ("persistence",  "n.", "continuing firmly despite difficulty",     "Persistence is the key to fluency."),
    ("conquer",      "v.", "to successfully overcome something",       "You will conquer this language."),
    ("nuance",       "n.", "a subtle difference in meaning",           "Native speakers catch every nuance."),
    ("context",      "n.", "the setting that clarifies meaning",       "Always learn words in context."),
    ("instinctive",  "adj.", "done without thinking, natural",         "Grammar becomes instinctive over time."),
    ("exposure",     "n.", "being in contact with something often",    "Daily exposure is the fastest teacher."),
    ("pattern",      "n.", "a repeated arrangement",                   "Your brain loves finding patterns."),
    ("breakthrough", "n.", "a sudden achievement after struggle",      "Your breakthrough moment is coming."),
    ("habit",        "n.", "a regular practice hard to give up",       "Build the English habit — it stacks."),
    ("confidence",   "n.", "belief in your own abilities",             "Confidence comes from doing, not waiting."),
    ("absorb",       "v.", "to take in and understand",                "Your brain absorbs more than you think."),
    ("recall",       "v.", "to bring a memory back to mind",           "SRS cards train your recall speed."),
    ("native",       "adj.", "belonging to a place or person by birth", "Think like a native speaker."),
    ("accent",       "n.", "a distinctive way of pronouncing words",   "Your accent is part of your identity."),
    ("simulate",     "v.", "to imitate conditions of something real",  "Speaking practice simulates real life."),
    ("engage",       "v.", "to participate or involve yourself",       "Engage with English every single day."),
]


def get_word_of_day() -> tuple:
    day_of_year = date.today().timetuple().tm_yday
    return WORD_OF_DAY[day_of_year % len(WORD_OF_DAY)]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_date TEXT UNIQUE,
            duo_xp INTEGER DEFAULT 0,
            duo_total_xp INTEGER DEFAULT 0,
            reading_pages INTEGER DEFAULT 0,
            listening_min INTEGER DEFAULT 0,
            speaking_sessions INTEGER DEFAULT 0,
            srs_reviews INTEGER DEFAULT 0,
            writing_min INTEGER DEFAULT 0,
            writing_topic TEXT DEFAULT '',
            raw_xp REAL DEFAULT 0,
            total_xp REAL DEFAULT 0,
            streak INTEGER DEFAULT 0,
            multiplier REAL DEFAULT 1.0,
            status TEXT DEFAULT 'FAIL',
            penalty INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)
    conn.execute("ALTER TABLE daily_log ADD COLUMN duo_total_xp INTEGER DEFAULT 0" ) if False else None
    try:
        conn.execute("ALTER TABLE daily_log ADD COLUMN duo_total_xp INTEGER DEFAULT 0")
        conn.execute("ALTER TABLE daily_log ADD COLUMN writing_topic TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
    conn.close()


def get_config(key):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
    conn.close()
    return row[0] if row else None


def set_config(key, value):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)", (key, str(value)))
    conn.commit()
    conn.close()
    if _supa:
        try:
            _supa.table("english_config").upsert({"key": key, "value": str(value)}, on_conflict="key").execute()
        except Exception as e:
            logging.warning(f"Supabase set_config error: {e}")


def fetch_duolingo_xp():
    """Returns (total_xp, streak) from Duolingo API."""
    try:
        r = requests.get(
            f"https://www.duolingo.com/2017-06-30/users?username={DUOLINGO_USERNAME}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10
        )
        if r.status_code != 200:
            return 0, 0
        u = r.json().get("users", [{}])[0]
        return u.get("totalXp", 0), u.get("streak", 0)
    except Exception as e:
        log.error(f"Duolingo API: {e}")
        return 0, 0


def get_duo_delta(current_total_xp: int) -> int:
    """Calculate XP earned today = current total minus yesterday's saved total."""
    conn = sqlite3.connect(DB_PATH)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    today = date.today().isoformat()
    row = conn.execute(
        "SELECT duo_total_xp FROM daily_log WHERE log_date IN (?,?) ORDER BY log_date DESC LIMIT 1",
        (yesterday, today)
    ).fetchone()
    conn.close()
    prev = row[0] if row and row[0] else None
    if prev is None:
        saved = get_config("duo_total_xp_baseline")
        prev = int(saved) if saved else current_total_xp
    delta = max(0, current_total_xp - prev)
    return delta


def get_streak_multiplier(streak: int) -> float:
    for threshold, mult in STREAK_MULTIPLIERS:
        if streak >= threshold:
            return mult
    return 1.0


def skill_level(xp: float) -> int:
    for i, threshold in enumerate(reversed(SKILL_LEVEL_XP)):
        if xp >= threshold:
            return len(SKILL_LEVEL_XP) - 1 - i
    return 1


def xp_progress_bar(xp: float, level: int, width: int = 10) -> str:
    if level >= len(SKILL_LEVEL_XP) - 1:
        return "█" * width + " MAX"
    lo = SKILL_LEVEL_XP[level]
    hi = SKILL_LEVEL_XP[level + 1]
    pct = (xp - lo) / (hi - lo) if hi > lo else 1.0
    filled = int(pct * width)
    return "█" * filled + "░" * (width - filled) + f" {int(pct*100)}%"


def overall_progress_bar(total_xp: float, width: int = 15) -> str:
    level_thresholds = [0, 100, 300, 700, 1500, 3000, 6000, 10000]
    level = 1
    for i, t in enumerate(level_thresholds):
        if total_xp >= t:
            level = i + 1
    lo = level_thresholds[min(level - 1, len(level_thresholds) - 1)]
    hi = level_thresholds[min(level, len(level_thresholds) - 1)]
    if lo == hi:
        pct = 1.0
    else:
        pct = (total_xp - lo) / (hi - lo)
    filled = int(pct * width)
    return level, "█" * filled + "░" * (width - filled)


def get_all_stats():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT duo_xp, reading_pages, listening_min, speaking_sessions,
               srs_reviews, writing_min, total_xp, streak, status
        FROM daily_log ORDER BY log_date
    """).fetchall()
    conn.close()

    stats = {
        "total_xp": 0.0,
        "total_days": len([r for r in rows if r[8] == "PASS"]),
        "max_streak": 0,
        "current_streak": 0,
        "reading_pages": 0,
        "listening_minutes": 0,
        "speaking_sessions": 0,
        "srs_reviews": 0,
        "writing_essays": 0,
        "duo_days": 0,
        "skill_xp": {"reading": 0.0, "listening": 0.0, "speaking": 0.0, "srs": 0.0, "writing": 0.0, "duolingo": 0.0},
        "level": 1,
    }
    for row in rows:
        duo_xp, r_pages, l_min, s_sess, srs_rev, w_min, total_xp, streak, status = row
        if status == "PASS":
            stats["reading_pages"] += r_pages
            stats["listening_minutes"] += l_min
            stats["speaking_sessions"] += s_sess
            stats["srs_reviews"] += srs_rev
            stats["writing_essays"] += 1 if w_min > 0 else 0
            stats["duo_days"] += 1 if duo_xp > 0 else 0
            stats["skill_xp"]["reading"] += r_pages * XP_WEIGHTS["reading"]
            stats["skill_xp"]["listening"] += l_min * XP_WEIGHTS["listening"]
            stats["skill_xp"]["speaking"] += s_sess * XP_WEIGHTS["speaking"]
            stats["skill_xp"]["srs"] += srs_rev * XP_WEIGHTS["srs"]
            stats["skill_xp"]["writing"] += w_min * XP_WEIGHTS["writing"]
            stats["skill_xp"]["duolingo"] += duo_xp * XP_WEIGHTS["duolingo"]
        stats["max_streak"] = max(stats["max_streak"], streak)

    if rows:
        stats["current_streak"] = rows[-1][7]
        stats["total_xp"] = rows[-1][6] if rows[-1][6] else 0

    level, _ = overall_progress_bar(stats["total_xp"])
    stats["level"] = level
    return stats


def get_prev_total_xp() -> float:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT total_xp FROM daily_log ORDER BY log_date DESC LIMIT 1").fetchone()
    conn.close()
    return row[0] if row else 0.0


def get_prev_streak() -> int:
    conn = sqlite3.connect(DB_PATH)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    row = conn.execute("SELECT streak, status FROM daily_log WHERE log_date=?", (yesterday,)).fetchone()
    conn.close()
    if row and row[1] == "PASS":
        return row[0]
    return 0


def save_day(duo_xp, reading, listening, speaking, srs, writing, duo_total_xp=0, writing_topic=""):
    prev_total = get_prev_total_xp()
    prev_streak = get_prev_streak()

    raw_xp = (duo_xp * XP_WEIGHTS["duolingo"] +
              reading * XP_WEIGHTS["reading"] +
              listening * XP_WEIGHTS["listening"] +
              speaking * XP_WEIGHTS["speaking"] +
              srs * XP_WEIGHTS["srs"] +
              writing * XP_WEIGHTS["writing"])

    status = "PASS" if raw_xp >= MIN_XP_PASS else "FAIL"
    penalty = FAIL_PENALTY if status == "FAIL" else 0

    streak = (prev_streak + 1) if status == "PASS" else 0
    multiplier = get_streak_multiplier(streak)

    final_xp = raw_xp * multiplier if status == "PASS" else 0
    total_xp = max(0, prev_total + final_xp - penalty)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO daily_log(log_date, duo_xp, duo_total_xp, reading_pages, listening_min,
                              speaking_sessions, srs_reviews, writing_min, writing_topic,
                              raw_xp, total_xp, streak, multiplier, status, penalty, created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(log_date) DO UPDATE SET
            duo_xp=excluded.duo_xp, duo_total_xp=excluded.duo_total_xp,
            reading_pages=excluded.reading_pages, listening_min=excluded.listening_min,
            speaking_sessions=excluded.speaking_sessions, srs_reviews=excluded.srs_reviews,
            writing_min=excluded.writing_min, writing_topic=excluded.writing_topic,
            raw_xp=excluded.raw_xp, total_xp=excluded.total_xp, streak=excluded.streak,
            multiplier=excluded.multiplier, status=excluded.status, penalty=excluded.penalty,
            created_at=excluded.created_at
    """, (date.today().isoformat(), duo_xp, duo_total_xp, reading, listening, speaking, srs,
          writing, writing_topic, raw_xp, total_xp, streak, multiplier, status, penalty,
          datetime.now().isoformat()))
    conn.commit()
    conn.close()

    if _supa:
        try:
            row = {
                "log_date": date.today().isoformat(),
                "duo_xp": duo_xp, "duo_total_xp": duo_total_xp,
                "reading_pages": reading, "listening_min": listening,
                "speaking_sessions": speaking, "srs_reviews": srs,
                "writing_min": writing, "writing_topic": writing_topic,
                "raw_xp": raw_xp, "total_xp": total_xp, "streak": streak,
                "multiplier": multiplier, "status": status, "penalty": penalty,
                "created_at": datetime.now().isoformat(),
            }
            _supa.table("english_daily_log").upsert(row, on_conflict="log_date").execute()
        except Exception as e:
            logging.warning(f"Supabase save_day error: {e}")

    return {
        "raw_xp": raw_xp, "final_xp": final_xp, "total_xp": total_xp,
        "streak": streak, "multiplier": multiplier, "status": status, "penalty": penalty,
        "duo_xp": duo_xp, "reading": reading, "listening": listening,
        "speaking": speaking, "srs": srs, "writing": writing,
    }


def make_keyboard(values: list, prefix: str) -> InlineKeyboardMarkup:
    row = [InlineKeyboardButton(str(v), callback_data=f"{prefix}:{v}") for v in values]
    rows = [row[:3], row[3:]] if len(row) > 3 else [row]
    return InlineKeyboardMarkup(rows)


def build_result_card(data: dict) -> str:
    status_emoji = "✅" if data["status"] == "PASS" else "❌"
    streak_emoji = "🔥" if data["streak"] > 0 else "💔"
    mult_text = f"×{data['multiplier']}" if data['multiplier'] != 1.0 else "×1.0"

    lines_raw = []
    if data["duo_xp"]:    lines_raw.append(f"📱 Duolingo:  {data['duo_xp']} XP → +{data['duo_xp'] * XP_WEIGHTS['duolingo']:.0f}")
    if data["reading"]:   lines_raw.append(f"📖 Reading:   {data['reading']} pages → +{data['reading'] * XP_WEIGHTS['reading']:.0f}")
    if data["listening"]: lines_raw.append(f"🎧 Listening: {data['listening']} min → +{data['listening'] * XP_WEIGHTS['listening']:.0f}")
    if data["speaking"]:  lines_raw.append(f"🗣 Speaking:  {data['speaking']}x session → +{data['speaking'] * XP_WEIGHTS['speaking']:.0f}")
    if data["srs"]:       lines_raw.append(f"🃏 SRS:       {data['srs']} cards → +{data['srs'] * XP_WEIGHTS['srs']:.0f}")
    if data["writing"]:   lines_raw.append(f"✍️ Writing:   {data['writing']} min → +{data['writing'] * XP_WEIGHTS['writing']:.0f}")
    if not lines_raw:
        lines_raw.append("(nothing logged today)")

    level, bar = overall_progress_bar(data["total_xp"])

    pass_fail_quip = {
        "PASS": ["Boom! That's how it's done 😎", "Look at you, crushing it! 🔥",
                 "Solid day, Harvi! 💪", "Nice work — every day counts! ✅"],
        "FAIL": ["Rough one. Tomorrow we bounce back 💪", "Hey, you still showed up. That matters 🤝",
                 "Not your best day — but there will be more chances! 🎯"],
    }
    import random
    quip = random.choice(pass_fail_quip.get(data["status"], ["Keep going!"]))

    result = (
        f"⚔️ HARVI — {date.today().strftime('%d.%m.%Y')}\n"
        f"{'━' * 28}\n"
        f"{chr(10).join(lines_raw)}\n"
        f"{'━' * 28}\n"
        f"💥 Today's XP: {data['raw_xp']:.1f} {mult_text} = {data['final_xp']:.1f}\n"
        f"{status_emoji} STATUS: {data['status']}"
        + (f"  |  Penalty: -{data['penalty']} XP" if data["penalty"] else "") +
        f"\n\n"
        f"{streak_emoji} Streak: {data['streak']} days\n"
        f"⚡ Multiplier: {mult_text}\n"
        f"{'━' * 28}\n"
        f"📊 Total XP: {data['total_xp']:.1f}\n"
        f"⭐ Level {level}: {bar}\n"
        f"{'━' * 28}\n"
        f"😺 {quip}"
    )
    return result


def build_stats_card(stats: dict) -> str:
    level, bar = overall_progress_bar(stats["total_xp"])
    lines = [
        f"⚔️ HARVI — Character Card",
        f"{'━' * 28}",
        f"📊 Total XP:  {stats['total_xp']:.1f}",
        f"⭐ Level:     {level}   {bar}",
        f"🔥 Streak:   {stats['current_streak']} days  (best: {stats['max_streak']})",
        f"{'━' * 28}",
        f"📈 Skills:",
    ]
    skill_info = [
        ("📱", "Duolingo",  "duolingo"),
        ("📖", "Reading",   "reading"),
        ("🎧", "Listening", "listening"),
        ("🗣", "Speaking",  "speaking"),
        ("🃏", "SRS",       "srs"),
        ("✍️", "Writing",   "writing"),
    ]
    for emoji, name, key in skill_info:
        xp = stats["skill_xp"][key]
        lv = skill_level(xp)
        pb = xp_progress_bar(xp, lv, width=8)
        lines.append(f"{emoji} {name:<10} Lv{lv}  {pb}  ({xp:.0f} XP)")

    return "\n".join(lines)


def build_achievements_card(stats: dict) -> str:
    lines = ["🏆 ACHIEVEMENTS\n" + "━" * 24]
    for ach_id, name, emoji, condition in ACHIEVEMENTS:
        try:
            unlocked = condition(stats)
        except Exception:
            unlocked = False
        status = "✅" if unlocked else "🔒"
        lines.append(f"{status} {emoji} {name}")
    return "\n".join(lines)


def current_week_of_month() -> int:
    today = date.today()
    first_day = today.replace(day=1)
    return min(4, (today.day - 1) // 7 + 1)


def build_quests_card(stats: dict) -> str:
    week_num = current_week_of_month()
    quests = WEEKLY_QUESTS.get(week_num, WEEKLY_QUESTS[4])
    lines = [f"📋 QUESTS — Week {week_num}\n" + "━" * 24]
    for name, stat_key, target in quests:
        current = stats.get(stat_key, 0)
        done = current >= target
        bar_w = 8
        pct = min(1.0, current / target)
        bar = "█" * int(pct * bar_w) + "░" * (bar_w - int(pct * bar_w))
        status = "✅" if done else f"{bar}"
        lines.append(f"{status}  {name}: {current}/{target}")
    return "\n".join(lines)


async def cmd_edit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT status, raw_xp FROM daily_log WHERE log_date=?",
        (date.today().isoformat(),)
    ).fetchone()
    conn.close()
    if not row:
        await update.message.reply_text(
            "No check-in found for today yet.\nUse /checkin to log your day! 📝"
        )
        return
    status, xp = row
    icon = "✅" if status == "PASS" else "❌"
    await update.message.reply_text(
        f"Today's entry: {icon} {status} — {xp:.0f} raw XP\n\n"
        f"Starting a new check-in to replace it...",
    )
    return await cmd_checkin(update, ctx)


async def cmd_level(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("A1 — Just started learning", callback_data="lvl:A1")],
        [InlineKeyboardButton("A2 — Basic conversations", callback_data="lvl:A2")],
        [InlineKeyboardButton("B1 — Can express most ideas", callback_data="lvl:B1")],
        [InlineKeyboardButton("B2 — Upper intermediate", callback_data="lvl:B2")],
        [InlineKeyboardButton("C1 — Advanced, near fluent", callback_data="lvl:C1")],
        [InlineKeyboardButton("C2 — Mastery / proficient", callback_data="lvl:C2")],
    ])
    await update.message.reply_text(
        "🎓 *English Level Assessment*\n\n"
        "What's your current level? Be honest — I adapt my tips to where you actually are!\n\n"
        "_Based on CEFR international standard_",
        parse_mode="Markdown",
        reply_markup=kb
    )
    return ASK_LEVEL


async def level_choice_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chosen = query.data.split(":")[1]
    ctx.user_data["eng_level"] = chosen

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Speaking — hard to form sentences", callback_data="weak:speaking")],
        [InlineKeyboardButton("👂 Listening — can't follow native speakers", callback_data="weak:listening")],
        [InlineKeyboardButton("📝 Grammar — lots of mistakes", callback_data="weak:grammar")],
        [InlineKeyboardButton("📚 Vocabulary — I forget words constantly", callback_data="weak:vocabulary")],
        [InlineKeyboardButton("✍️ Writing — hard to structure thoughts", callback_data="weak:writing")],
    ])
    await query.edit_message_text(
        f"Got it — *{chosen}* level! 😺\n\n"
        f"Now tell me: what's your biggest challenge right now?",
        parse_mode="Markdown",
        reply_markup=kb
    )
    return ASK_WEAK


async def weak_choice_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    weak = query.data.split(":")[1]
    chosen = ctx.user_data.get("eng_level", "B1")

    set_config("english_level", chosen)
    set_config("english_weak", weak)

    vocab_map = {"A1": 500, "A2": 1500, "B1": 3000, "B2": 5000, "C1": 8000, "C2": 15000}
    vocab_est = vocab_map.get(chosen, 3000)
    set_config("vocab_estimate", str(vocab_est))

    tips = {
        "speaking": "Focus on Speaking sessions — even 5 minutes of self-talk counts! 🗣",
        "listening": "20+ min of English content daily. It compounds faster than you think 🎧",
        "grammar": "Read more native texts — grammar fixes itself intuitively over time 📖",
        "vocabulary": "SRS is your superpower. 10 Anki cards/day beats memorizing word lists 🃏",
        "writing": "Daily 10-min freewriting in English will genuinely shock you in a month ✍️",
    }
    tip = tips.get(weak, "Stay consistent — that IS the strategy! 💪")

    await query.edit_message_text(
        f"✅ *Profile saved!*\n\n"
        f"Level: *{chosen}*\n"
        f"Est. vocabulary: ~{vocab_est:,} words\n"
        f"Weak spot: *{weak.capitalize()}*\n\n"
        f"💡 {tip}\n\n"
        f"_I'll keep this in mind when giving you tips. You can update it anytime with /level_",
        parse_mode="Markdown"
    )
    return ConversationHandler.END


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    set_config("chat_id", chat_id)
    text = (
        "Hey! 😺 I'm *Bro* — your English study buddy!\n\n"
        "Every evening I'll check in with you.\n"
        "Just tap buttons — no typing needed.\n\n"
        "*Commands:*\n"
        "/checkin — Daily check-in\n"
        "/edit — Fix today's check-in\n"
        "/level — Set your English profile 🎓\n"
        "/stats — Character card\n"
        "/quests — Weekly challenges\n"
        "/achievements — Your badges\n"
        "/week — Last 7 days\n\n"
        "Let's build that streak! 🔥"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    stats = get_all_stats()
    await update.message.reply_text(f"```\n{build_stats_card(stats)}\n```", parse_mode="Markdown")


async def cmd_achievements(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    stats = get_all_stats()
    await update.message.reply_text(f"```\n{build_achievements_card(stats)}\n```", parse_mode="Markdown")


async def cmd_quests(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    stats = get_all_stats()
    await update.message.reply_text(f"```\n{build_quests_card(stats)}\n```", parse_mode="Markdown")


async def cmd_week(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT log_date, status, streak, total_xp, raw_xp
        FROM daily_log ORDER BY log_date DESC LIMIT 7
    """).fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("No data yet. Start with /checkin!")
        return
    lines = ["📅 LAST 7 DAYS\n" + "━" * 26]
    for r in rows:
        log_date, status, streak, total_xp, raw_xp = r
        s = "✅" if status == "PASS" else "❌"
        fire = "🔥" if streak > 0 else "  "
        lines.append(f"{s} {log_date}  XP:{raw_xp:.0f}  {fire}{streak}  Σ{total_xp:.0f}")
    await update.message.reply_text(f"```\n" + "\n".join(lines) + "\n```", parse_mode="Markdown")


async def cmd_checkin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    duo_total, duo_streak = fetch_duolingo_xp()
    duo_delta = get_duo_delta(duo_total)
    set_config("duo_total_xp_baseline", str(duo_total))
    ctx.user_data["duo_xp"] = duo_delta
    ctx.user_data["duo_total_xp"] = duo_total
    ctx.user_data["duo_streak_api"] = duo_streak

    streak_line = f"Duolingo: +{duo_delta} XP today  🔥 streak {duo_streak} days"

    kb = make_keyboard([0, 5, 10, 15, 20, 30], "reading")
    await update.message.reply_text(
        f"📚 *Daily Check-in — {date.today().strftime('%d.%m.%Y')}*\n\n"
        f"_{streak_line}_\n\n"
        f"Let's count your wins today, Harvi!\n\n"
        f"📖 *How many pages did you read in English?*",
        parse_mode="Markdown",
        reply_markup=kb
    )
    return ASK_READING


async def ask_reading_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["reading"] = int(query.data.split(":")[1])
    kb = make_keyboard([0, 10, 20, 30, 60, 90], "listening")
    await query.edit_message_text(
        "🎧 *Listening — how many minutes?*\n_(series, podcasts, YouTube — all counts!)_",
        parse_mode="Markdown",
        reply_markup=kb
    )
    return ASK_LISTENING


async def ask_listening_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["listening"] = int(query.data.split(":")[1])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Да — говорил!", callback_data="speaking:1")],
        [InlineKeyboardButton("❌ Нет", callback_data="speaking:0")],
    ])
    prompt = get_speaking_prompt()
    await query.edit_message_text(
        f"🗣 *Did you speak English today?*\n_(a few sentences out loud, chatbot, game — it counts!)_\n\n"
        f"💬 *Today's speaking topic:*\n_{prompt}_",
        parse_mode="Markdown",
        reply_markup=kb
    )
    return ASK_SPEAKING


async def ask_speaking_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["speaking"] = int(query.data.split(":")[1])
    kb = make_keyboard([0, 5, 10, 15, 20, 30], "srs")
    await query.edit_message_text(
        "🃏 *SRS flashcards — how many?*\n_(Anki, Quizlet, or any vocabulary app)_",
        parse_mode="Markdown",
        reply_markup=kb
    )
    return ASK_SRS


async def ask_srs_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["srs"] = int(query.data.split(":")[1])
    topic = get_todays_writing_topic()
    ctx.user_data["writing_topic"] = topic
    kb = make_keyboard([0, 5, 10, 15, 20, 30], "writing")
    await query.edit_message_text(
        f"✍️ *Writing time! How many minutes?*\n\n"
        f"💡 Today's topic:\n_{topic}_\n\n"
        f"_Even 5 minutes counts — just write freely!_",
        parse_mode="Markdown",
        reply_markup=kb
    )
    return ASK_WRITING


async def ask_writing_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["writing"] = int(query.data.split(":")[1])

    data = save_day(
        duo_xp=ctx.user_data.get("duo_xp", 0),
        duo_total_xp=ctx.user_data.get("duo_total_xp", 0),
        reading=ctx.user_data.get("reading", 0),
        listening=ctx.user_data.get("listening", 0),
        speaking=ctx.user_data.get("speaking", 0),
        srs=ctx.user_data.get("srs", 0),
        writing=ctx.user_data.get("writing", 0),
        writing_topic=ctx.user_data.get("writing_topic", ""),
    )

    card = build_result_card(data)

    stats = get_all_stats()
    new_achievements = []
    for ach_id, name, emoji, condition in ACHIEVEMENTS:
        try:
            if condition(stats):
                prev_key = f"ach_{ach_id}"
                if not get_config(prev_key):
                    set_config(prev_key, "1")
                    new_achievements.append(f"{emoji} {name}")
        except Exception:
            pass

    prev_level_xp = data["total_xp"] - data["final_xp"]
    old_lvl = sum(1 for t in OVERALL_LEVEL_XP if prev_level_xp >= t)
    new_lvl = sum(1 for t in OVERALL_LEVEL_XP if data["total_xp"] >= t)
    leveled_up = new_lvl > old_lvl

    result = f"```\n{card}\n```"
    if leveled_up:
        result += f"\n\n🎊 *LEVEL UP!* ⚔️ {old_lvl} → {new_lvl}\nHarvi, you just leveled up! 👑 Keep going!"
    if new_achievements:
        result += "\n\n🎉 *New achievements!*\n" + "\n".join(new_achievements)

    await query.edit_message_text(result, parse_mode="Markdown")
    return ConversationHandler.END


def build_morning_recommendation() -> str:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT log_date, duo_xp, reading_pages, listening_min, speaking_sessions,
               srs_reviews, writing_min, status, streak
        FROM daily_log
        WHERE log_date >= date('now', '-7 days')
        ORDER BY log_date
    """).fetchall()
    conn.close()

    week_totals = {"duo_days": 0, "reading_pages": 0, "listening_minutes": 0,
                   "speaking_sessions": 0, "srs_reviews": 0, "writing_essays": 0}
    current_streak = 0
    for r in rows:
        _, duo, reading, listening, speaking, srs, writing, status, streak = r
        if status == "PASS":
            week_totals["duo_days"] += 1 if duo > 0 else 0
            week_totals["reading_pages"] += reading
            week_totals["listening_minutes"] += listening
            week_totals["speaking_sessions"] += speaking
            week_totals["srs_reviews"] += srs
            week_totals["writing_essays"] += 1 if writing > 0 else 0
        current_streak = streak

    week_num = current_week_of_month()
    quests = {
        1: [("Duolingo", "duo_days", 5), ("Reading", "reading_pages", 30), ("Speaking", "speaking_sessions", 2), ("SRS", "srs_reviews", 3)],
        2: [("Duolingo", "duo_days", 6), ("Reading", "reading_pages", 50), ("Listening", "listening_minutes", 40), ("Speaking", "speaking_sessions", 3), ("SRS", "srs_reviews", 5)],
        3: [("Duolingo", "duo_days", 7), ("Reading", "reading_pages", 70), ("Listening", "listening_minutes", 60), ("Speaking", "speaking_sessions", 4), ("SRS", "srs_reviews", 7), ("Writing", "writing_essays", 2)],
        4: [("Duolingo", "duo_days", 9), ("Reading", "reading_pages", 100), ("Listening", "listening_minutes", 90), ("Speaking", "speaking_sessions", 5), ("SRS", "srs_reviews", 10), ("Writing", "writing_essays", 4)],
    }

    behind = []
    for name, key, target in quests.get(week_num, quests[4]):
        current = week_totals.get(key, 0)
        if current < target:
            gap = target - current
            behind.append((name, key, current, target, gap))

    behind.sort(key=lambda x: x[4] / x[3], reverse=True)

    skill_map = {
        "duo_days":          ("📱 Duolingo",   "lessons",  10),
        "reading_pages":     ("📖 Reading",    "pages",     8),
        "listening_minutes": ("🎧 Listening",  "min",      20),
        "speaking_sessions": ("🗣 Speaking",   "session",   1),
        "srs_reviews":       ("🃏 SRS",        "cards",    10),
        "writing_essays":    ("✍️ Writing",    "min",      15),
    }

    lines = [f"☀️ *Good morning, Harvi! {date.today().strftime('%d.%m.%Y')}*\n"]

    if current_streak > 0:
        lines.append(f"🔥 Streak: {current_streak} days — don't break it!\n")
    else:
        lines.append("💔 Streak reset. Today we start fresh — that's priority #1!\n")

    if behind:
        lines.append("*🎯 Today's game plan:*")
        for i, (name, key, current, target, gap) in enumerate(behind[:3], 1):
            emoji, unit, suggest = skill_map.get(key, (name, "units", 5))
            suggest = min(suggest, gap)
            pct = int(current / target * 100)
            lines.append(f"{i}. {emoji} — {suggest} {unit}  _{pct}% of quest done_")
        lines.append("")

        if behind[0][1] == "speaking_sessions":
            lines.append("💡 *Quick tip:* Chat with an AI bot for 5 minutes = 1 speaking session!")
        elif behind[0][1] == "reading_pages":
            lines.append("💡 *Quick tip:* Read one article during lunch — easy 5-10 pages!")
        elif behind[0][1] == "listening_minutes":
            lines.append("💡 *Quick tip:* Put on an English podcast while commuting — easiest XP ever!")
        elif behind[0][1] == "srs_reviews":
            lines.append("💡 *Quick tip:* 5 minutes in Anki in the morning — quest closed!")
        else:
            lines.append("💡 *Quick tip:* Even 20 consistent minutes daily = 140 minutes a week. Compound!")
    else:
        lines.append("🏆 *All weekly quests done!* Today is a bonus day — grind the weak skills.")

    # паттерн — слабый день недели
    conn2 = sqlite3.connect(DB_PATH)
    all_rows = conn2.execute(
        "SELECT log_date, status FROM daily_log ORDER BY log_date"
    ).fetchall()
    conn2.close()
    from collections import defaultdict
    dow_fails = defaultdict(int)
    dow_total = defaultdict(int)
    dow_names_en = ["Mondays","Tuesdays","Wednesdays","Thursdays","Fridays","Saturdays","Sundays"]
    for log_date_str, st in all_rows:
        try:
            d = datetime.strptime(log_date_str, "%Y-%m-%d")
            dow_total[d.weekday()] += 1
            if st == "FAIL":
                dow_fails[d.weekday()] += 1
        except Exception:
            pass
    today_dow = date.today().weekday()
    if dow_total[today_dow] >= 2:
        fail_rate = dow_fails[today_dow] / dow_total[today_dow]
        if fail_rate >= 0.4:
            lines.append(f"\n📊 *Pattern spotted:* You miss {dow_names_en[today_dow]} {int(fail_rate*100)}% of the time — extra important today!")

    word, pos, definition, example = get_word_of_day()
    lines.append(
        f"\n📖 *Word of the Day:*\n"
        f"*{word}* _{pos}_ — {definition}\n"
        f"_\"{example}\"_"
    )

    lines.append("\n_See you tonight at /checkin_ 😺")
    return "\n".join(lines)


def build_weekly_report() -> str:
    conn = sqlite3.connect(DB_PATH)
    last_week_start = (date.today() - timedelta(days=7)).isoformat()
    rows = conn.execute("""
        SELECT log_date, duo_xp, reading_pages, listening_min, speaking_sessions,
               srs_reviews, writing_min, status, streak, raw_xp, total_xp, multiplier
        FROM daily_log
        WHERE log_date >= ? AND log_date < date('now')
        ORDER BY log_date
    """, (last_week_start,)).fetchall()
    conn.close()

    if not rows:
        return ""

    pass_days = [r for r in rows if r[7] == "PASS"]
    fail_days = [r for r in rows if r[7] == "FAIL"]

    total_xp_earned = sum(r[9] * r[11] for r in pass_days)
    total_pages     = sum(r[2] for r in pass_days)
    total_listen    = sum(r[3] for r in pass_days)
    total_speaking  = sum(r[4] for r in pass_days)
    total_srs       = sum(r[5] for r in pass_days)
    total_writing   = sum(r[6] for r in pass_days)
    max_streak      = max((r[8] for r in rows), default=0)
    final_xp        = rows[-1][10] if rows else 0

    grade = "🏆 LEGEND" if len(fail_days) == 0 else (
            "💪 GREAT"  if len(fail_days) <= 1 else (
            "😊 GOOD"   if len(fail_days) <= 2 else (
            "😬 OK"     if len(fail_days) <= 3 else "💔 ROUGH WEEK")))

    lines = [
        f"📊 *Weekly Report — {(date.today() - timedelta(days=7)).strftime('%d.%m')} – {(date.today() - timedelta(days=1)).strftime('%d.%m')}*\n",
        f"Overall: *{grade}*",
        f"✅ PASS days: {len(pass_days)}/7   ❌ FAIL: {len(fail_days)}",
        f"🔥 Best streak this week: {max_streak} days",
        f"⭐ XP earned: {total_xp_earned:.0f}   |   Total: {final_xp:.0f}\n",
        f"*Activity breakdown:*",
        f"📱 Duolingo: {sum(r[1] for r in pass_days)} XP",
        f"📖 Reading: {total_pages} pages",
        f"🎧 Listening: {total_listen} min",
        f"🗣 Speaking: {total_speaking} sessions",
        f"🃏 SRS: {total_srs} cards",
        f"✍️ Writing: {total_writing} min",
    ]

    weak = []
    if total_speaking == 0: weak.append("Speaking (zero sessions!)")
    if total_srs < 5:       weak.append("SRS (under 5 cards)")
    if total_listen < 30:   weak.append("Listening (under 30 min)")
    if weak:
        lines.append(f"\n💡 *Weak spots this week:* {', '.join(weak)}")
        lines.append("_Focus on these next week — that's where your XP is hiding!_")

    if len(pass_days) == 7:
        lines.append("\n🎉 *Perfect week — 7/7!* You're absolutely unstoppable, Harvi!")

    lines.append("\n_New week, new quests. Let's make it better! 💪_")
    return "\n".join(lines)


async def morning_recommendation_job(ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = get_config("chat_id")
    if not chat_id:
        return
    if date.today().weekday() == 0:
        report = build_weekly_report()
        if report:
            await ctx.bot.send_message(chat_id=int(chat_id), text=report, parse_mode="Markdown")
    text = build_morning_recommendation()
    await ctx.bot.send_message(chat_id=int(chat_id), text=text, parse_mode="Markdown")


async def streak_warning_job(ctx: ContextTypes.DEFAULT_TYPE):
    """19:00 — предупреждение если чекин ещё не сделан."""
    chat_id = get_config("chat_id")
    if not chat_id:
        return
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT status FROM daily_log WHERE log_date=?", (date.today().isoformat(),)
    ).fetchone()
    conn.close()
    if row:
        return
    _, duo_streak = fetch_duolingo_xp()
    risk_line = f"🔥 {duo_streak}-day streak at risk!" if duo_streak > 0 else "💔 No streak yet — start one tonight!"
    await ctx.bot.send_message(
        chat_id=int(chat_id),
        text=(
            f"⚠️ *Hey Harvi! 2 hours left!*\n\n"
            f"{risk_line}\n\n"
            f"You haven't logged today yet.\n"
            f"/checkin takes 30 seconds — let's go! ⚡"
        ),
        parse_mode="Markdown"
    )


async def evening_checkin_job(ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = get_config("chat_id")
    if not chat_id:
        return
    duo_xp, duo_streak = fetch_duolingo_xp()
    risk = "⚠️ Keep it alive!" if duo_streak > 0 and duo_streak < 3 else ("🔥 Looking good!" if duo_streak >= 3 else "✅ Safe")
    await ctx.bot.send_message(
        chat_id=int(chat_id),
        text=(
            f"🌙 *Evening Check-in — {date.today().strftime('%d.%m.%Y')}*\n\n"
            f"🔥 Duolingo streak: {duo_streak} days  {risk}\n\n"
            f"How was today, Harvi?\n"
            f"Tap /checkin to log your day and earn XP! 🎮"
        ),
        parse_mode="Markdown"
    )


PID_FILE = os.path.join(os.path.dirname(__file__), "bot.pid")


def acquire_pid_lock():
    if os.path.exists(PID_FILE):
        try:
            old_pid = int(open(PID_FILE).read().strip())
            import psutil
            if psutil.pid_exists(old_pid):
                log.error(f"Bot already running (PID {old_pid}). Exiting.")
                raise SystemExit(1)
        except (ValueError, ImportError):
            pass
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def release_pid_lock():
    try:
        os.remove(PID_FILE)
    except FileNotFoundError:
        pass


def main():
    acquire_pid_lock()
    import atexit
    atexit.register(release_pid_lock)

    init_db()
    asyncio.set_event_loop(asyncio.new_event_loop())

    app = Application.builder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("checkin", cmd_checkin)],
        states={
            ASK_READING:   [CallbackQueryHandler(ask_reading_done,   pattern="^reading:")],
            ASK_LISTENING: [CallbackQueryHandler(ask_listening_done, pattern="^listening:")],
            ASK_SPEAKING:  [CallbackQueryHandler(ask_speaking_done,  pattern="^speaking:")],
            ASK_SRS:       [CallbackQueryHandler(ask_srs_done,       pattern="^srs:")],
            ASK_WRITING:   [CallbackQueryHandler(ask_writing_done,   pattern="^writing:")],
        },
        fallbacks=[],
    )

    level_conv = ConversationHandler(
        entry_points=[CommandHandler("level", cmd_level)],
        states={
            ASK_LEVEL: [CallbackQueryHandler(level_choice_done, pattern="^lvl:")],
            ASK_WEAK:  [CallbackQueryHandler(weak_choice_done,  pattern="^weak:")],
        },
        fallbacks=[],
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("achievements", cmd_achievements))
    app.add_handler(CommandHandler("quests", cmd_quests))
    app.add_handler(CommandHandler("week", cmd_week))
    app.add_handler(CommandHandler("edit", cmd_edit))
    app.add_handler(conv)
    app.add_handler(level_conv)

    app.job_queue.run_daily(morning_recommendation_job, time=dtime(hour=10, minute=0))
    app.job_queue.run_daily(streak_warning_job,         time=dtime(hour=19, minute=0))
    app.job_queue.run_daily(evening_checkin_job,        time=dtime(hour=EVENING_HOUR, minute=EVENING_MINUTE))

    log.info("Bot started.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
