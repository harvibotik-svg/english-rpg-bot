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

OPENROUTER_KEY = os.getenv("OPENROUTER_KEY", "")
OPENROUTER_MODEL = "openai/gpt-4o-mini"

EVENING_HOUR = 21
EVENING_MINUTE = 0
MIN_XP_PASS = 0
FAIL_PENALTY = 20

XP_WEIGHTS = {
    "duolingo":  0.5,
    "reading":   3.0,
    "listening": 0.5,
    "speaking":  5.0,
    "srs":       1.0,
    "writing":   2.0,
}

SKILL_LEVEL_XP   = [0, 50, 150, 350, 700, 1200, 2000]
OVERALL_LEVEL_XP = [0, 100, 300, 700, 1500, 3000, 6000, 10000]

STREAK_MULTIPLIERS = [(30, 2.5), (14, 2.0), (7, 1.5), (4, 1.2), (0, 1.0)]

# (id, name, emoji, tier, bonus_xp, description, condition, hidden)
ACHIEVEMENTS = [
    # ── FIRST STEPS ──────────────────────────────────────────────────────────
    ("first_day",     "First Step",         "🌱", "bronze",    10,
     "Complete your very first check-in",
     lambda s: s["total_days"] >= 1, False),

    # ── STREAK ───────────────────────────────────────────────────────────────
    ("streak_3",      "Spark",              "🔥", "bronze",    10,
     "3-day streak",                        lambda s: s["max_streak"] >= 3,   False),
    ("streak_7",      "On Fire",            "⚡", "silver",    25,
     "7-day streak",                        lambda s: s["max_streak"] >= 7,   False),
    ("streak_14",     "Two Weeks Strong",   "💎", "silver",    25,
     "14-day streak",                       lambda s: s["max_streak"] >= 14,  False),
    ("streak_30",     "Monthly Warrior",    "👑", "gold",      50,
     "30-day streak",                       lambda s: s["max_streak"] >= 30,  False),
    ("streak_60",     "Iron Will",          "🌙", "gold",      50,
     "60-day streak",                       lambda s: s["max_streak"] >= 60,  False),
    ("streak_100",    "Century",            "💫", "legendary", 100,
     "100-day streak",                      lambda s: s["max_streak"] >= 100, False),
    ("streak_180",    "Half Year Hero",     "🌠", "legendary", 100,
     "180-day streak",                      lambda s: s["max_streak"] >= 180, False),
    ("streak_365",    "Year Legend",        "🌍", "legendary", 100,
     "365-day streak — a full year",        lambda s: s["max_streak"] >= 365, False),

    # ── XP ───────────────────────────────────────────────────────────────────
    ("xp_100",        "First 100",          "💯", "bronze",    10,
     "Earn 100 total XP",                   lambda s: s["total_xp"] >= 100,   False),
    ("xp_500",        "Rising Star",        "⭐", "bronze",    10,
     "Earn 500 total XP",                   lambda s: s["total_xp"] >= 500,   False),
    ("xp_1000",       "1K Club",            "🏆", "silver",    25,
     "Earn 1,000 total XP",                 lambda s: s["total_xp"] >= 1000,  False),
    ("xp_2500",       "Grinder",            "🎯", "silver",    25,
     "Earn 2,500 total XP",                 lambda s: s["total_xp"] >= 2500,  False),
    ("xp_5000",       "5K Legend",          "🌟", "gold",      50,
     "Earn 5,000 total XP",                 lambda s: s["total_xp"] >= 5000,  False),
    ("xp_10000",      "Grandmaster",        "🔮", "legendary", 100,
     "Earn 10,000 total XP",                lambda s: s["total_xp"] >= 10000, False),

    # ── PASS DAYS ────────────────────────────────────────────────────────────
    ("pass_10",       "Getting Started",    "📅", "bronze",    10,
     "10 PASS days",                        lambda s: s["total_days"] >= 10,  False),
    ("pass_25",       "Habit Forming",      "📆", "bronze",    10,
     "25 PASS days",                        lambda s: s["total_days"] >= 25,  False),
    ("pass_50",       "Halfway Hero",       "🗓", "silver",    25,
     "50 PASS days",                        lambda s: s["total_days"] >= 50,  False),
    ("pass_100",      "Triple Digits",      "🏅", "gold",      50,
     "100 PASS days",                       lambda s: s["total_days"] >= 100, False),
    ("pass_200",      "Unstoppable",        "🎖", "legendary", 100,
     "200 PASS days",                       lambda s: s["total_days"] >= 200, False),
    ("pass_365",      "Year of English",    "🎓", "legendary", 100,
     "365 PASS days total",                 lambda s: s["total_days"] >= 365, False),

    # ── READING ──────────────────────────────────────────────────────────────
    ("read_50",       "Page Turner",        "📖", "bronze",    10,
     "Read 50 pages in English",            lambda s: s["reading_pages"] >= 50,   False),
    ("read_100",      "Bookworm",           "📚", "silver",    25,
     "Read 100 pages in English",           lambda s: s["reading_pages"] >= 100,  False),
    ("read_300",      "Avid Reader",        "📕", "gold",      50,
     "Read 300 pages in English",           lambda s: s["reading_pages"] >= 300,  False),
    ("read_1000",     "Literary Lion",      "🦁", "legendary", 100,
     "Read 1,000 pages in English",         lambda s: s["reading_pages"] >= 1000, False),

    # ── SPEAKING ─────────────────────────────────────────────────────────────
    ("speak_5",       "First Words",        "🗣", "bronze",    10,
     "5 speaking sessions",                 lambda s: s["speaking_sessions"] >= 5,   False),
    ("speak_20",      "Conversationalist",  "💬", "silver",    25,
     "20 speaking sessions",                lambda s: s["speaking_sessions"] >= 20,  False),
    ("speak_50",      "Smooth Talker",      "🎤", "gold",      50,
     "50 speaking sessions",                lambda s: s["speaking_sessions"] >= 50,  False),
    ("speak_100",     "Orator",             "🎭", "legendary", 100,
     "100 speaking sessions",               lambda s: s["speaking_sessions"] >= 100, False),

    # ── LISTENING ────────────────────────────────────────────────────────────
    ("listen_60",     "First Hour",         "🎧", "bronze",    10,
     "60 minutes of listening",             lambda s: s["listening_minutes"] >= 60,   False),
    ("listen_300",    "Tuned In",           "🎵", "silver",    25,
     "300 minutes of listening",            lambda s: s["listening_minutes"] >= 300,  False),
    ("listen_1000",   "Audio Addict",       "🎶", "gold",      50,
     "1,000 minutes of listening",          lambda s: s["listening_minutes"] >= 1000, False),

    # ── SRS ──────────────────────────────────────────────────────────────────
    ("srs_20",        "Card Collector",     "🃏", "bronze",    10,
     "20 SRS reviews",                      lambda s: s["srs_reviews"] >= 20,  False),
    ("srs_50",        "Flashcard Fan",      "🎴", "silver",    25,
     "50 SRS reviews",                      lambda s: s["srs_reviews"] >= 50,  False),
    ("srs_200",       "Memory Master",      "🧠", "gold",      50,
     "200 SRS reviews",                     lambda s: s["srs_reviews"] >= 200, False),

    # ── WRITING ──────────────────────────────────────────────────────────────
    ("write_5",       "First Draft",        "✍️", "bronze",    10,
     "5 writing sessions",                  lambda s: s["writing_essays"] >= 5,  False),
    ("write_20",      "Wordsmith",          "📝", "silver",    25,
     "20 writing sessions",                 lambda s: s["writing_essays"] >= 20, False),
    ("write_50",      "Author",             "📓", "gold",      50,
     "50 writing sessions",                 lambda s: s["writing_essays"] >= 50, False),

    # ── RECORDS ──────────────────────────────────────────────────────────────
    ("perfect_week",  "Perfect Week",       "🌈", "gold",      50,
     "7/7 PASS days in one calendar week",  lambda s: s.get("perfect_weeks", 0) >= 1,  False),
    ("perfect_month", "Flawless Month",     "🌕", "legendary", 100,
     "All days PASS in one full month",     lambda s: s.get("perfect_months", 0) >= 1, False),
    ("week_200xp",    "Power Week",         "🚀", "gold",      50,
     "200+ XP earned in a single week",     lambda s: s.get("best_week_xp", 0) >= 200, False),

    # ── LEVEL ────────────────────────────────────────────────────────────────
    ("level_3",       "Adventurer",         "⚔️", "silver",    25,
     "Reach Level 3",                       lambda s: s["level"] >= 3, False),
    ("level_5",       "Champion",           "🛡", "gold",      50,
     "Reach Level 5",                       lambda s: s["level"] >= 5, False),
    ("level_7",       "Elite",              "👑", "legendary", 100,
     "Reach Level 7",                       lambda s: s["level"] >= 7, False),

    # ── CONSISTENCY ──────────────────────────────────────────────────────────
    ("consistency",   "Consistency Master", "🎯", "gold",      50,
     "30 PASS days with streak 20+",
     lambda s: s["total_days"] >= 30 and s["max_streak"] >= 20, False),

    # ── SECRET / HIDDEN ──────────────────────────────────────────────────────
    ("comeback_kid",  "Comeback Kid",       "💪", "secret",    30,
     "PASS after 3 consecutive FAILs",      lambda s: s.get("comeback_kid", False),      True),
    ("night_owl",     "Night Owl",          "🦉", "secret",    30,
     "Check in after 22:00 on 3 occasions", lambda s: s.get("night_owl_count", 0) >= 3,  True),
    ("renaissance",   "Renaissance",        "🌟", "secret",    50,
     "Use all 6 skills in a single day",    lambda s: s.get("all_skills_day", False),     True),
    ("marathon_read", "Marathon Reader",    "📖", "secret",    30,
     "Read 20+ pages in a single day",      lambda s: s.get("max_day_pages", 0) >= 20,   True),
    ("curious_cat",   "Curious Cat",        "😺", "secret",    20,
     "Ask Harvi 10 questions",              lambda s: s.get("ai_questions", 0) >= 10,    True),
    ("speak_warrior", "Speaking Warrior",   "🗡", "secret",    40,
     "Speaking in 7 consecutive PASS days", lambda s: s.get("speak_streak_7", False),    True),
]

TIER_LABEL = {"bronze": "🥉 Bronze", "silver": "🥈 Silver",
              "gold": "🥇 Gold",     "legendary": "💎 Legendary", "secret": "🎭 Secret"}

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

BOSSES = [
    ("Grammar Dragon",    "Complete 3 Writing sessions this week",  "writing_essays",    3,  150),
    ("Speaking Demon",    "Speak English 5 times this week",        "speaking_sessions", 5,  200),
    ("Reading Giant",     "Read 50 pages this week",                "reading_pages",     50, 175),
    ("Vocabulary Hydra",  "Review 30 SRS cards this week",          "srs_reviews",       30, 125),
    ("Listening Phantom", "Listen for 120 minutes this week",       "listening_minutes", 120, 150),
    ("Consistency Beast", "Get 7 PASS days this week",              "duo_days",          7,  300),
]

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


_config_cache: dict = {}


def get_config(key):
    if key in _config_cache:
        return _config_cache[key]
    if _supa:
        try:
            r = _supa.table("english_config").select("value").eq("key", key).execute()
            if r.data:
                val = r.data[0]["value"]
                _config_cache[key] = val
                return val
        except Exception:
            pass
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
    conn.close()
    val = row[0] if row else None
    if val is not None:
        _config_cache[key] = val
    return val


def set_config(key, value):
    _config_cache[key] = str(value)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)", (key, str(value)))
    conn.commit()
    conn.close()
    if _supa:
        try:
            _supa.table("english_config").upsert({"key": key, "value": str(value)}, on_conflict="key").execute()
        except Exception as e:
            logging.warning(f"Supabase set_config error: {e}")


def seed_from_supabase():
    """On startup: pull Supabase data into local SQLite so all queries work."""
    if not _supa:
        return
    try:
        rows = _supa.table("english_config").select("key,value").execute().data or []
        if rows:
            conn = sqlite3.connect(DB_PATH)
            for r in rows:
                conn.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)", (r["key"], r["value"]))
                _config_cache[r["key"]] = r["value"]
            conn.commit()
            conn.close()
            log.info(f"Seeded {len(rows)} config keys from Supabase")
    except Exception as e:
        log.warning(f"seed_from_supabase config: {e}")
    try:
        rows = _supa.table("english_daily_log").select("*").execute().data or []
        if rows:
            conn = sqlite3.connect(DB_PATH)
            for r in rows:
                conn.execute("""
                    INSERT OR REPLACE INTO daily_log
                    (log_date,duo_xp,duo_total_xp,reading_pages,listening_min,
                     speaking_sessions,srs_reviews,writing_min,writing_topic,
                     raw_xp,total_xp,streak,multiplier,status,penalty,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    r.get("log_date"), r.get("duo_xp",0), r.get("duo_total_xp",0),
                    r.get("reading_pages",0), r.get("listening_min",0),
                    r.get("speaking_sessions",0), r.get("srs_reviews",0),
                    r.get("writing_min",0), r.get("writing_topic",""),
                    r.get("raw_xp",0), r.get("total_xp",0), r.get("streak",0),
                    r.get("multiplier",1.0), r.get("status","FAIL"),
                    r.get("penalty",0), r.get("created_at","")
                ))
            conn.commit()
            conn.close()
            log.info(f"Seeded {len(rows)} daily_log rows from Supabase")
    except Exception as e:
        log.warning(f"seed_from_supabase daily_log: {e}")


# ── MEMORY ─────────────────────────────────────────────────────────────────────

_memory_cache: list = []
_memory_cache_ts: float = 0.0


def get_memories(limit: int = 40) -> list:
    """Return list of {category, key, value} from english_memory."""
    global _memory_cache, _memory_cache_ts
    import time
    now = time.time()
    if _memory_cache and now - _memory_cache_ts < 300:
        return _memory_cache
    if _supa:
        try:
            rows = (
                _supa.table("english_memory")
                .select("category,key,value,updated_at")
                .order("updated_at", desc=True)
                .limit(limit)
                .execute()
                .data or []
            )
            _memory_cache = rows
            _memory_cache_ts = now
            return rows
        except Exception as e:
            log.warning(f"get_memories error: {e}")
    return []


def save_memory(key: str, value: str, category: str = "general", source: str = "conversation"):
    """Upsert a memory entry in Supabase."""
    global _memory_cache_ts
    _memory_cache_ts = 0  # invalidate cache
    if not _supa:
        return
    try:
        _supa.table("english_memory").upsert(
            {"key": key, "value": value, "category": category, "source": source,
             "updated_at": datetime.utcnow().isoformat()},
            on_conflict="key"
        ).execute()
    except Exception as e:
        log.warning(f"save_memory error: {e}")


def extract_and_save_memories(conversation: list):
    """Ask AI to extract memorable facts from conversation and save them."""
    import json, re
    if not OPENROUTER_KEY or len(conversation) < 4:
        return
    history_text = "\n".join(
        f"{'Vladimir' if m['role'] == 'user' else 'Harvi'}: {m['content']}"
        for m in conversation[-12:]
    )
    prompt = (
        "Read this conversation and extract facts about Vladimir worth remembering long-term.\n"
        "Focus on: goals, progress, preferences, problems, milestones, study habits, personal info.\n"
        "Ignore greetings and small talk. Only extract specific, concrete, useful facts.\n\n"
        f"CONVERSATION:\n{history_text}\n\n"
        "Respond ONLY as a JSON array:\n"
        '[{"key":"snake_case_key","value":"fact description","category":"progress|goals|habits|personal|problems"}]\n'
        "If nothing worth remembering, respond: []"
    )
    try:
        result = call_openrouter(
            "You extract structured memory facts from conversations. Return ONLY valid JSON array, nothing else.",
            prompt, max_tokens=500
        )
        if not result:
            return
        match = re.search(r'\[.*?\]', result, re.DOTALL)
        if not match:
            return
        facts = json.loads(match.group())
        count = 0
        for fact in facts:
            if isinstance(fact, dict) and "key" in fact and "value" in fact:
                save_memory(
                    key=str(fact["key"])[:100],
                    value=str(fact["value"])[:500],
                    category=str(fact.get("category", "general"))[:50],
                )
                count += 1
        if count:
            log.info(f"Extracted {count} memories from conversation")
    except Exception as e:
        log.warning(f"extract_and_save_memories error: {e}")


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


def get_extended_stats() -> dict:
    """get_all_stats() + extra fields for achievements."""
    stats = get_all_stats()
    conn  = sqlite3.connect(DB_PATH)
    rows  = conn.execute(
        "SELECT log_date, status, reading_pages, speaking_sessions, "
        "duo_xp, listening_min, srs_reviews, writing_min, raw_xp, multiplier "
        "FROM daily_log ORDER BY log_date"
    ).fetchall()
    conn.close()

    import calendar as _cal
    from collections import defaultdict
    weeks_status  = defaultdict(list)
    months_status = defaultdict(list)
    week_xp       = defaultdict(float)

    for r in rows:
        log_date_str, status = r[0], r[1]
        try:
            d = datetime.strptime(log_date_str, "%Y-%m-%d").date()
        except Exception:
            continue
        iso = d.isocalendar()
        wk  = (iso[0], iso[1])
        mo  = (d.year, d.month)
        weeks_status[wk].append(status)
        months_status[mo].append(status)
        if status == "PASS":
            week_xp[wk] += r[8] * r[9]

    perfect_weeks  = sum(1 for days in weeks_status.values()
                         if len(days) == 7 and all(s == "PASS" for s in days))
    perfect_months = 0
    for (yr, mo), statuses in months_status.items():
        if len(statuses) == _cal.monthrange(yr, mo)[1] and all(s == "PASS" for s in statuses):
            perfect_months += 1

    best_week_xp   = max(week_xp.values(), default=0.0)
    max_day_pages  = max((r[2] for r in rows if r[1] == "PASS"), default=0)

    # speaking 7-day consecutive streak
    speak_streak_7 = False
    consec = 0
    for r in rows:
        if r[1] == "PASS" and r[3] > 0:
            consec += 1
            if consec >= 7:
                speak_streak_7 = True
                break
        else:
            consec = 0

    # all 6 skills in one day
    all_skills_day = any(
        r[1] == "PASS" and r[4] > 0 and r[2] > 0 and r[5] > 0
        and r[3] > 0 and r[6] > 0 and r[7] > 0
        for r in rows
    )

    # comeback kid: PASS after 3 consecutive FAILs
    comeback_kid = False
    for i in range(3, len(rows)):
        if (rows[i][1] == "PASS" and
                rows[i-1][1] == "FAIL" and
                rows[i-2][1] == "FAIL" and
                rows[i-3][1] == "FAIL"):
            comeback_kid = True
            break

    night_owl_count = int(get_config("night_owl_count")    or 0)
    ai_questions    = int(get_config("ai_questions_count") or 0)
    ach_bonus       = float(get_config("achievement_bonus_total") or 0)

    stats.update({
        "perfect_weeks":   perfect_weeks,
        "perfect_months":  perfect_months,
        "best_week_xp":    best_week_xp,
        "max_day_pages":   max_day_pages,
        "speak_streak_7":  speak_streak_7,
        "all_skills_day":  all_skills_day,
        "comeback_kid":    comeback_kid,
        "night_owl_count": night_owl_count,
        "ai_questions":    ai_questions,
        "achievement_bonus": ach_bonus,
    })
    stats["total_xp"] = stats["total_xp"] + ach_bonus
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


def get_yesterday_data() -> dict | None:
    """Return yesterday's log_date row as dict, or None."""
    conn = sqlite3.connect(DB_PATH)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    row = conn.execute(
        "SELECT status, raw_xp, streak FROM daily_log WHERE log_date=?", (yesterday,)
    ).fetchone()
    conn.close()
    if row:
        return {"status": row[0], "raw_xp": row[1], "streak": row[2]}
    return None


def save_day(duo_xp, reading, listening, speaking, srs, writing, duo_total_xp=0, writing_topic=""):
    prev_total = get_prev_total_xp()
    prev_streak = get_prev_streak()

    raw_xp = (duo_xp * XP_WEIGHTS["duolingo"] +
              reading * XP_WEIGHTS["reading"] +
              listening * XP_WEIGHTS["listening"] +
              speaking * XP_WEIGHTS["speaking"] +
              srs * XP_WEIGHTS["srs"] +
              writing * XP_WEIGHTS["writing"])

    status = "PASS" if raw_xp > 0 else "FAIL"
    penalty = FAIL_PENALTY if status == "FAIL" else 0

    # Streak Recovery: if yesterday was FAIL but today raw_xp >= 40, recover streak
    streak_recovered = False
    yesterday_data = get_yesterday_data()
    if (status == "PASS" and yesterday_data and
            yesterday_data["status"] == "FAIL" and raw_xp >= 40):
        # Recover: continue from the streak before yesterday's fail
        # Find the streak from 2 days ago
        conn = sqlite3.connect(DB_PATH)
        two_days_ago = (date.today() - timedelta(days=2)).isoformat()
        row2 = conn.execute(
            "SELECT streak, status FROM daily_log WHERE log_date=?", (two_days_ago,)
        ).fetchone()
        conn.close()
        if row2 and row2[1] == "PASS":
            prev_streak = row2[0]
            streak_recovered = True

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

    # track night owl (checkin after 22:00)
    if datetime.now().hour >= 22:
        owl = int(get_config("night_owl_count") or 0)
        set_config("night_owl_count", str(owl + 1))

    return {
        "raw_xp": raw_xp, "final_xp": final_xp, "total_xp": total_xp,
        "streak": streak, "multiplier": multiplier, "status": status, "penalty": penalty,
        "duo_xp": duo_xp, "reading": reading, "listening": listening,
        "speaking": speaking, "srs": srs, "writing": writing,
        "streak_recovered": streak_recovered,
    }


def fetch_duolingo_profile() -> dict:
    """Fetch enriched Duolingo profile from public API."""
    try:
        r = requests.get(
            f"https://www.duolingo.com/2017-06-30/users?username={DUOLINGO_USERNAME}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        if r.status_code != 200:
            return {}
        u = r.json().get("users", [{}])[0]
        streak_data = u.get("streakData", {}).get("currentStreak", {})
        courses = u.get("courses", [])
        en_course = next((c for c in courses if c.get("learningLanguage") == "en"), {})
        return {
            "duo_total_xp":   u.get("totalXp", 0),
            "duo_streak":     u.get("streak", 0),
            "streak_start":   streak_data.get("startDate", ""),
            "en_xp":          en_course.get("xp", 0),
            "courses_count":  len(courses),
            "learning_since": u.get("creationDate", ""),
        }
    except Exception:
        return {}


def build_harvi_system() -> str:
    stats   = get_all_stats()
    eng_lvl = get_config("english_level") or "B1"
    eng_wk  = get_config("english_weak")  or "speaking"
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT status, raw_xp FROM daily_log WHERE log_date=?",
        (date.today().isoformat(),)
    ).fetchone()
    conn.close()
    today_status = f"{row[0]} ({row[1]:.0f} raw XP)" if row else "not checked in yet"

    duo = fetch_duolingo_profile()
    duo_block = ""
    if duo:
        streak_start = duo.get("streak_start", "")
        months_learning = ""
        if streak_start:
            try:
                from datetime import datetime as dt
                start = dt.strptime(streak_start, "%Y-%m-%d").date()
                delta = (date.today() - start).days
                months_learning = f"{delta // 30} months ({delta} days) without breaking"
            except Exception:
                pass
        duo_block = f"""
DUOLINGO HISTORY (real data from API):
- Total Duolingo XP: {duo.get('duo_total_xp', 0):,} XP (English course only)
- Current Duolingo streak: {duo.get('duo_streak', 0)} days
- This streak runs since: {streak_start} — {months_learning}
- English XP on Duolingo: {duo.get('en_xp', 0):,}
- Assessment: With {duo.get('duo_total_xp', 0):,} XP and a {duo.get('duo_streak', 0)}-day unbroken streak \
the user has solid daily practice discipline. XP at this level typically reflects \
upper A2–B1 Duolingo progress with strong consistency."""

    memories = get_memories(20)
    memory_block = ""
    if memories:
        mem_lines = [f"- [{m.get('category','general')}] {m['value']}" for m in memories[:15]]
        memory_block = "\nWHAT YOU REMEMBER ABOUT VLADIMIR (use naturally, don't recite):\n" + "\n".join(mem_lines)

    return f"""You are Harvi — a chubby tabby cat with glasses who loves English.
You are Vladimir's personal English study buddy in Telegram. You know him well.

USER PROFILE:
- Self-assessed English level: {eng_lvl}
- Weak area: {eng_wk}
- RPG streak (this app): {stats['current_streak']} days
- Total RPG XP: {stats['total_xp']:.0f}
- Total PASS days: {stats['total_days']}
- Today: {today_status}
{duo_block}{memory_block}

YOUR PERSONALITY:
- Warm, witty, like a smart friend — never a teacher lecturing
- Light humor, occasional cat pun is fine
- Short answers (under 120 words) unless explaining grammar — then up to 200
- Adapt vocabulary and grammar complexity to {eng_lvl} level
- Always encouraging, never preachy
- When explaining grammar: give 2 real-life examples, keep it simple
- You can speak both English and Russian — mirror whatever language Vladimir uses
- Never repeat the same opener twice in a row
- When referencing his Duolingo history, use the real numbers above — be specific
- Reference remembered facts naturally when relevant, like a friend who pays attention"""


def call_openrouter(system: str, user_msg: str, history: list = None, max_tokens: int = 350) -> str:
    if not OPENROUTER_KEY:
        return ""
    messages = [{"role": "system", "content": system}]
    if history:
        messages.extend(history[-8:])
    messages.append({"role": "user", "content": user_msg})
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://t.me/MyEnglishBro_bot",
                "X-Title": "EnglishBro Harvi",
            },
            json={"model": OPENROUTER_MODEL, "messages": messages, "max_tokens": max_tokens},
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
        log.error(f"OpenRouter {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log.error(f"OpenRouter exception: {e}")
    return ""


async def handle_free_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_msg = update.message.text.strip()
    if not user_msg:
        return

    # Route to talk mode if active
    if ctx.user_data.get("talk_mode"):
        await handle_talk_message(update, ctx, user_msg)
        return

    system  = build_harvi_system()
    history = ctx.user_data.get("chat_history", [])
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    reply = call_openrouter(system, user_msg, history, max_tokens=400)
    if not reply:
        reply = "Sorry, my brain went offline for a sec. Try again! 😅"
    history.append({"role": "user",      "content": user_msg})
    history.append({"role": "assistant", "content": reply})
    ctx.user_data["chat_history"] = history[-10:]
    await update.message.reply_text(reply)

    # track questions for Curious Cat achievement
    q_count = int(get_config("ai_questions_count") or 0) + 1
    set_config("ai_questions_count", str(q_count))
    if q_count in (10, 25, 50):
        ext = get_extended_stats()
        chat_id_str = get_config("chat_id")
        if chat_id_str:
            await check_and_unlock_achievements(ext, bot=ctx.bot, chat_id=int(chat_id_str))

    # Auto-extract memories every 10 messages
    full_history = ctx.user_data.get("chat_history", [])
    if len(full_history) >= 2 and len(full_history) % 10 == 0:
        extract_and_save_memories(full_history)


async def handle_talk_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user_msg: str):
    """Handle a message during an active talk session."""
    talk_history = ctx.user_data.get("talk_history", [])
    talk_history.append({"role": "user", "content": user_msg})

    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    system = build_harvi_system()

    # Build a talk-specific system prompt
    talk_system = system + (
        "\n\nYou are in CONVERSATION PRACTICE mode. Rules:\n"
        "- Respond naturally to what Vladimir said (continue the conversation)\n"
        "- Keep your response under 80 words\n"
        "- At the end, quietly note 1-2 grammar/vocabulary fixes with format: "
        "'[✏️ fix: original → corrected]' on a new line\n"
        "- Then ask a follow-up question to keep the conversation going\n"
        "- Be warm, not a grammar teacher"
    )

    try:
        reply = call_openrouter(talk_system, user_msg, talk_history[:-1], max_tokens=200)
        if not reply:
            reply = "That's interesting! Tell me more — what happened next? 😺"
    except Exception:
        reply = "That's interesting! Tell me more — what happened next? 😺"

    talk_history.append({"role": "assistant", "content": reply})
    ctx.user_data["talk_history"] = talk_history

    await update.message.reply_text(reply)


def generate_achievement_message(name: str, desc: str, tier: str, bonus_xp: int) -> str:
    tier_label = TIER_LABEL.get(tier, tier)
    system = build_harvi_system()
    prompt = (
        f"Vladimir just unlocked the achievement '{name}' ({tier_label}) — {desc}. "
        f"He earns +{bonus_xp} bonus XP. Write a short, genuine congratulation "
        f"(2-3 sentences). Be specific about this achievement. Make it feel earned."
    )
    return call_openrouter(system, prompt, max_tokens=120) or f"🎉 *{name}* — {desc}! +{bonus_xp} XP!"


async def check_and_unlock_achievements(
    stats: dict,
    bot=None,
    chat_id: int = None,
) -> list:
    """Check all achievements, unlock new ones, optionally send Telegram messages."""
    newly = []
    for ach_id, name, emoji, tier, bonus_xp, desc, condition, hidden in ACHIEVEMENTS:
        try:
            if not condition(stats):
                continue
        except Exception:
            continue
        if get_config(f"ach_{ach_id}"):
            continue
        # ── unlock ──
        set_config(f"ach_{ach_id}", "1")
        prev_bonus = float(get_config("achievement_bonus_total") or 0)
        set_config("achievement_bonus_total", str(prev_bonus + bonus_xp))
        newly.append((name, emoji, tier, bonus_xp, desc))
        if bot and chat_id:
            harvi_msg = generate_achievement_message(name, desc, tier, bonus_xp)
            text = (
                f"{emoji} *Achievement Unlocked!*\n"
                f"{TIER_LABEL[tier]} — *{name}*\n"
                f"_{desc}_\n\n"
                f"💰 +{bonus_xp} XP bonus!\n\n"
                f"{harvi_msg}"
            )
            try:
                await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
            except Exception as e:
                log.warning(f"Achievement message failed: {e}")
    return newly


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

    streak_recovered_line = "\n🔄 Streak recovered!" if data.get("streak_recovered") else ""

    result = (
        f"⚔️ HARVI — {date.today().strftime('%d.%m.%Y')}\n"
        f"{'━' * 28}\n"
        f"{chr(10).join(lines_raw)}\n"
        f"{'━' * 28}\n"
        f"💥 Today's XP: {data['raw_xp']:.1f} {mult_text} = {data['final_xp']:.1f}\n"
        f"{status_emoji} STATUS: {data['status']}"
        + (f"  |  Penalty: -{data['penalty']} XP" if data["penalty"] else "") +
        streak_recovered_line +
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


def get_7day_avg_xp() -> float:
    """Return average raw_xp*multiplier per PASS day over last 7 days."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT raw_xp, multiplier FROM daily_log
        WHERE log_date >= date('now', '-7 days') AND status='PASS'
    """).fetchall()
    conn.close()
    if not rows:
        return 0.0
    return sum(r[0] * r[1] for r in rows) / 7.0  # avg over 7-day window


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

    # Forecast: days to next level
    avg_xp = get_7day_avg_xp()
    if avg_xp > 0:
        next_level_idx = min(level, len(OVERALL_LEVEL_XP) - 1)
        next_threshold = OVERALL_LEVEL_XP[next_level_idx] if next_level_idx < len(OVERALL_LEVEL_XP) else None
        if next_threshold and stats["total_xp"] < next_threshold:
            xp_needed = next_threshold - stats["total_xp"]
            days_needed = int(xp_needed / avg_xp) + 1
            lines.append(f"{'━' * 28}")
            lines.append(f"📈 At this pace: Level {level + 1} in ~{days_needed} days")

    return "\n".join(lines)


def build_achievements_card(stats: dict) -> str:
    unlocked, locked = [], []
    for ach_id, name, emoji, tier, bonus_xp, desc, condition, hidden in ACHIEVEMENTS:
        try:
            met = condition(stats)
        except Exception:
            met = False
        if hidden and not get_config(f"ach_{ach_id}"):
            continue  # secret — don't reveal
        tier_lbl = TIER_LABEL.get(tier, tier)
        if met or get_config(f"ach_{ach_id}"):
            unlocked.append(f"✅ {emoji} {name}  [{tier_lbl}]")
        else:
            locked.append(f"🔒 {emoji} {name}  [{tier_lbl}]")

    lines = [f"🏆 ACHIEVEMENTS — {len(unlocked)}/{len(unlocked)+len(locked)}\n" + "━" * 28]
    if unlocked:
        lines.append("✨ UNLOCKED:")
        lines.extend(unlocked)
    if locked:
        lines.append("\n🔒 LOCKED:")
        lines.extend(locked[:8])
        if len(locked) > 8:
            lines.append(f"  … and {len(locked)-8} more")
    return "\n".join(lines)


def current_week_of_month() -> int:
    today = date.today()
    return min(4, (today.day - 1) // 7 + 1)


def get_week_stats() -> dict:
    """Stats for Mon–today of the current calendar week."""
    today = date.today()
    week_start = (today - timedelta(days=today.weekday())).isoformat()
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT duo_xp, reading_pages, listening_min, speaking_sessions,
               srs_reviews, writing_min, status
        FROM daily_log WHERE log_date >= ? AND log_date <= ? ORDER BY log_date
    """, (week_start, today.isoformat())).fetchall()
    conn.close()
    stats = {"duo_days": 0, "reading_pages": 0, "listening_minutes": 0,
             "speaking_sessions": 0, "srs_reviews": 0, "writing_essays": 0}
    for duo_xp, reading, listening, speaking, srs, writing, status in rows:
        if status == "PASS":
            stats["duo_days"]          += 1 if duo_xp > 0 else 0
            stats["reading_pages"]     += reading
            stats["listening_minutes"] += listening
            stats["speaking_sessions"] += speaking
            stats["srs_reviews"]       += srs
            stats["writing_essays"]    += 1 if writing > 0 else 0
    return stats


def build_quests_card() -> str:
    week_num = current_week_of_month()
    week_stats = get_week_stats()
    quests = WEEKLY_QUESTS.get(week_num, WEEKLY_QUESTS[4])
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    lines = [f"📋 QUESTS — Week {week_num} of {today.strftime('%B')}\n"
             f"({week_start.strftime('%d.%m')} – this week)\n" + "━" * 24]
    for name, stat_key, target in quests:
        current = week_stats.get(stat_key, 0)
        done = current >= target
        bar_w = 8
        pct = min(1.0, current / target)
        bar = "█" * int(pct * bar_w) + "░" * (bar_w - int(pct * bar_w))
        status = "✅" if done else f"{bar}"
        lines.append(f"{status}  {name}: {current}/{target}")

    # Boss Fight section
    boss = get_current_boss()
    if boss:
        lines.append("\n" + "━" * 24)
        defeated = get_config("boss_defeated") == "1"
        current = week_stats.get(boss["target_key"], 0)
        target = boss["target_val"]
        bar_w = 10
        pct = min(1.0, current / target) if target > 0 else 1.0
        bar = "█" * int(pct * bar_w) + "░" * (bar_w - int(pct * bar_w))
        status_icon = "☠️ DEFEATED" if defeated else f"{bar} {current}/{target}"
        lines.append(f"⚔️ BOSS FIGHT — {boss['name']}")
        lines.append(f"_{boss['description']}_")
        lines.append(f"{status_icon}")
        lines.append(f"💰 Reward: +{boss['bonus_xp']} XP")
    return "\n".join(lines)


def get_current_boss() -> dict | None:
    """Return current boss dict if it's the same ISO week, else None."""
    import datetime as _dt
    iso_week = str(_dt.date.today().isocalendar()[1])
    stored_week = get_config("boss_week")
    if stored_week != iso_week:
        return None
    name = get_config("boss_name")
    if not name:
        return None
    return {
        "name":       name,
        "description": get_config("boss_description") or "",
        "target_key": get_config("boss_target_key") or "",
        "target_val": int(get_config("boss_target_val") or 0),
        "bonus_xp":   int(get_config("boss_bonus_xp") or 0),
        "week":       iso_week,
    }


def assign_new_boss() -> dict:
    """Pick a random boss for this week and save to config."""
    import random, datetime as _dt
    iso_week = str(_dt.date.today().isocalendar()[1])
    boss = random.choice(BOSSES)
    name, description, target_key, target_val, bonus_xp = boss
    set_config("boss_name",       name)
    set_config("boss_description", description)
    set_config("boss_target_key", target_key)
    set_config("boss_target_val", str(target_val))
    set_config("boss_bonus_xp",   str(bonus_xp))
    set_config("boss_week",       iso_week)
    set_config("boss_defeated",   "0")
    return {
        "name": name, "description": description,
        "target_key": target_key, "target_val": target_val,
        "bonus_xp": bonus_xp, "week": iso_week,
    }


def boss_fight_check(week_stats: dict, bot=None, chat_id: int = None) -> str:
    """Check if boss is defeated; return message string or ''."""
    boss = get_current_boss()
    if not boss:
        return ""
    if get_config("boss_defeated") == "1":
        return ""
    current = week_stats.get(boss["target_key"], 0)
    if current >= boss["target_val"]:
        set_config("boss_defeated", "1")
        # Award bonus XP
        prev_bonus = float(get_config("achievement_bonus_total") or 0)
        set_config("achievement_bonus_total", str(prev_bonus + boss["bonus_xp"]))
        msg = (
            f"⚔️ *BOSS DEFEATED!* 🎉\n\n"
            f"You defeated the *{boss['name']}*!\n"
            f"_{boss['description']}_\n\n"
            f"💰 Bonus: +{boss['bonus_xp']} XP awarded!\n\n"
        )
        try:
            harvi = call_openrouter(
                build_harvi_system(),
                f"Vladimir just defeated the Boss '{boss['name']}' — {boss['description']}. "
                f"Give a heroic 2-sentence congratulation as Harvi the cat!",
                max_tokens=100,
            )
            if harvi:
                msg += harvi
        except Exception:
            pass
        return msg
    return ""


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
        "/month — This month's report 📅\n"
        "/achievements — Your badges\n"
        "/week — Last 7 days\n\n"
        "Let's build that streak! 🔥"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    stats = get_all_stats()
    await update.message.reply_text(f"```\n{build_stats_card(stats)}\n```", parse_mode="Markdown")


async def cmd_achievements(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    stats = get_extended_stats()
    await update.message.reply_text(f"```\n{build_achievements_card(stats)}\n```", parse_mode="Markdown")


async def cmd_quests(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"```\n{build_quests_card()}\n```", parse_mode="Markdown")


def get_week_comparison() -> dict:
    """Returns dict with this_week and last_week summary stats."""
    today = date.today()
    this_week_start = (today - timedelta(days=today.weekday())).isoformat()
    last_week_start = (today - timedelta(days=today.weekday() + 7)).isoformat()
    last_week_end   = (today - timedelta(days=today.weekday() + 1)).isoformat()

    conn = sqlite3.connect(DB_PATH)
    this_rows = conn.execute("""
        SELECT raw_xp, multiplier, status, speaking_sessions
        FROM daily_log WHERE log_date >= ? ORDER BY log_date
    """, (this_week_start,)).fetchall()
    last_rows = conn.execute("""
        SELECT raw_xp, multiplier, status, speaking_sessions
        FROM daily_log WHERE log_date >= ? AND log_date <= ? ORDER BY log_date
    """, (last_week_start, last_week_end)).fetchall()
    conn.close()

    def summarize(rows):
        xp = sum(r[0] * r[1] for r in rows if r[2] == "PASS")
        pass_days = sum(1 for r in rows if r[2] == "PASS")
        active_skills = 0  # count days with speaking > 0 as proxy for active skills
        speaking = sum(r[3] for r in rows if r[2] == "PASS")
        return {"xp": xp, "pass_days": pass_days, "speaking": speaking}

    return {
        "this_week": summarize(this_rows),
        "last_week": summarize(last_rows),
    }


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

    # Week-over-week comparison
    try:
        cmp = get_week_comparison()
        tw = cmp["this_week"]
        lw = cmp["last_week"]
        if lw["xp"] > 0 or lw["pass_days"] > 0:
            lines.append("━" * 26)
            # XP comparison
            if lw["xp"] > 0:
                xp_diff_pct = ((tw["xp"] - lw["xp"]) / lw["xp"]) * 100
                xp_arrow = "📈" if xp_diff_pct >= 0 else "📉"
                sign = "+" if xp_diff_pct >= 0 else ""
                lines.append(f"vs last week: XP {sign}{xp_diff_pct:.0f}% {xp_arrow}")
            else:
                lines.append(f"vs last week: XP {tw['xp']:.0f} (no data last week)")
            # PASS days comparison
            pass_diff = tw["pass_days"] - lw["pass_days"]
            pass_arrow = "📈" if pass_diff > 0 else ("📉" if pass_diff < 0 else "➡️")
            sign = "+" if pass_diff > 0 else ""
            lines.append(f"PASS days: {tw['pass_days']} ({sign}{pass_diff} vs last week) {pass_arrow}")
    except Exception:
        pass

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

    prev_level_xp = data["total_xp"] - data["final_xp"]
    old_lvl = sum(1 for t in OVERALL_LEVEL_XP if prev_level_xp >= t)
    new_lvl = sum(1 for t in OVERALL_LEVEL_XP if data["total_xp"] >= t)
    leveled_up = new_lvl > old_lvl

    result = f"```\n{card}\n```"
    if leveled_up:
        result += f"\n\n🎊 *LEVEL UP!* ⚔️ {old_lvl} → {new_lvl}\nHarvi, you just leveled up! 👑 Keep going!"

    await query.edit_message_text(result, parse_mode="Markdown")

    # check achievements after checkin — send separately as individual messages
    chat_id_str = get_config("chat_id")
    if chat_id_str:
        ext_stats = get_extended_stats()
        await check_and_unlock_achievements(
            ext_stats,
            bot=query.get_bot(),
            chat_id=int(chat_id_str),
        )
        # Boss fight check
        try:
            week_stats = get_week_stats()
            boss_msg = boss_fight_check(week_stats)
            if boss_msg:
                await query.get_bot().send_message(
                    chat_id=int(chat_id_str), text=boss_msg, parse_mode="Markdown"
                )
        except Exception as e:
            log.warning(f"boss_fight_check error: {e}")

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


def build_month_card(year: int = None, month: int = None) -> str:
    import calendar
    today = date.today()
    if year is None:  year  = today.year
    if month is None: month = today.month
    month_start = f"{year}-{month:02d}-01"
    next_y, next_m = (year + 1, 1) if month == 12 else (year, month + 1)
    month_end = f"{next_y}-{next_m:02d}-01"

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT log_date, duo_xp, reading_pages, listening_min, speaking_sessions,
               srs_reviews, writing_min, status, streak, raw_xp, multiplier, total_xp
        FROM daily_log WHERE log_date >= ? AND log_date < ? ORDER BY log_date
    """, (month_start, month_end)).fetchall()
    conn.close()

    month_name = calendar.month_name[month]
    if not rows:
        return f"📅 {month_name} {year} — no data yet."

    pass_days  = [r for r in rows if r[7] == "PASS"]
    fail_days  = [r for r in rows if r[7] == "FAIL"]
    xp_earned  = sum(r[9] * r[10] for r in pass_days)
    max_streak = max((r[8] for r in rows), default=0)
    final_xp   = rows[-1][11]

    grade = ("🏆 LEGEND" if len(fail_days) == 0 else
             "💪 GREAT"  if len(fail_days) <= 2 else
             "😊 GOOD"   if len(fail_days) <= 5 else
             "😬 OK"     if len(fail_days) <= 10 else "💔 TOUGH MONTH")

    lines = [
        f"📅 *{month_name} {year} — Monthly Report*\n",
        f"Overall: *{grade}*",
        f"✅ PASS: {len(pass_days)}/{len(rows)}   ❌ FAIL: {len(fail_days)}",
        f"🔥 Best streak: {max_streak} days",
        f"⭐ XP earned: {xp_earned:.0f}   |   Total: {final_xp:.0f}\n",
        f"*Activity:*",
        f"📱 Duolingo: {sum(r[1] for r in pass_days)} XP",
        f"📖 Reading:  {sum(r[2] for r in pass_days)} pages",
        f"🎧 Listening: {sum(r[3] for r in pass_days)} min",
        f"🗣 Speaking: {sum(r[4] for r in pass_days)} sessions",
        f"🃏 SRS:      {sum(r[5] for r in pass_days)} cards",
        f"✍️ Writing:  {sum(r[6] for r in pass_days)} min",
    ]
    if len(pass_days) == len(rows):
        lines.append("\n🎉 *Perfect month — zero fails!* Legendary, Harvi! 🏆")
    return "\n".join(lines)


async def cmd_month(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    card = build_month_card()
    await update.message.reply_text(card, parse_mode="Markdown")


async def morning_recommendation_job(ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = get_config("chat_id")
    if not chat_id:
        return
    today = date.today()
    if today.weekday() == 0:
        report = build_weekly_report()
        if report:
            await ctx.bot.send_message(chat_id=int(chat_id), text=report, parse_mode="Markdown")
        # Assign new boss fight for the week
        try:
            boss = assign_new_boss()
            boss_announce = (
                f"⚔️ *NEW BOSS FIGHT — Week {boss['week']}!*\n\n"
                f"🐉 *{boss['name']}*\n"
                f"_{boss['description']}_\n\n"
                f"💰 Reward: +{boss['bonus_xp']} XP if you win!\n\n"
                f"_Defeat it by completing the challenge this week!_"
            )
            await ctx.bot.send_message(chat_id=int(chat_id), text=boss_announce, parse_mode="Markdown")
        except Exception as e:
            log.warning(f"Boss assignment error: {e}")
    if today.day == 1:
        last = (today.replace(day=1) - timedelta(days=1))
        monthly = build_month_card(last.year, last.month)
        await ctx.bot.send_message(chat_id=int(chat_id), text=monthly, parse_mode="Markdown")
    text = build_morning_recommendation()
    await ctx.bot.send_message(chat_id=int(chat_id), text=text, parse_mode="Markdown")

    # Personalized daily task from Harvi
    try:
        conn = sqlite3.connect(DB_PATH)
        last7 = conn.execute("""
            SELECT log_date, duo_xp, reading_pages, listening_min, speaking_sessions,
                   srs_reviews, writing_min, status
            FROM daily_log WHERE log_date >= date('now', '-7 days') ORDER BY log_date
        """).fetchall()
        conn.close()
        data_summary = "; ".join(
            f"{r[0]}:{r[7]}(duo={r[1]},read={r[2]},listen={r[3]},speak={r[4]},srs={r[5]},write={r[6]})"
            for r in last7
        )
        system = build_harvi_system()
        task_prompt = (
            f"Vladimir's last 7 days data: {data_summary}. "
            f"Look at this data. Give him ONE specific task for today. Max 2 sentences. "
            f"Be concrete (e.g. 'Watch 1 Friends episode' not 'watch something'). "
            f"Address him directly. No intro, just the task."
        )
        task_reply = call_openrouter(system, task_prompt, max_tokens=80)
        if task_reply:
            await ctx.bot.send_message(
                chat_id=int(chat_id),
                text=f"🎯 *Today's mission from Harvi:*\n\n{task_reply}",
                parse_mode="Markdown"
            )
    except Exception as e:
        log.warning(f"Personalized task error: {e}")


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


async def checkin_final_reminder_job(ctx: ContextTypes.DEFAULT_TYPE):
    """20:30 — last call if no checkin yet."""
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
    risk = f"🔥 {duo_streak}-day streak ends at midnight!" if duo_streak > 0 else "💔 No streak yet — start one NOW!"
    await ctx.bot.send_message(
        chat_id=int(chat_id),
        text=(
            f"⏰ *Last call, Harvi! 30 minutes left!*\n\n"
            f"{risk}\n\n"
            f"30 seconds, buttons only — /checkin 🚀"
        ),
        parse_mode="Markdown"
    )


async def midday_message_job(ctx: ContextTypes.DEFAULT_TYPE):
    """13:00 — proactive AI message: question, mini-story, tip or friendly check-in."""
    chat_id = get_config("chat_id")
    if not chat_id:
        return
    import random
    system = build_harvi_system()
    prompt = random.choice([
        "Send a short friendly midday message. Ask one fun question about their day "
        "and sneak in a short English practice — one sentence to translate or complete.",
        "Give Vladimir a mini writing prompt for today — 2 sentences max, fun topic, "
        "appropriate for his level. Encourage him to reply.",
        "Share one practical English phrase or idiom he can use TODAY. "
        "Give a real example, keep it punchy.",
        "Ask Vladimir one interesting question in English he should think about and "
        "answer out loud (speaking practice). Make it relevant to his life.",
        "Give a quick grammar tip that fixes a common mistake at his level. "
        "One rule, two examples, done.",
    ])
    text = call_openrouter(system, prompt, max_tokens=180)
    if text:
        await ctx.bot.send_message(chat_id=int(chat_id), text=text)


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


async def cmd_grammar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Check grammar of user-provided text."""
    args = ctx.args
    if not args:
        await update.message.reply_text(
            "📝 *Grammar Check*\n\nUsage: `/grammar I go to shop yesterday`\n\n"
            "Send me a sentence and I'll fix it! 😺",
            parse_mode="Markdown"
        )
        return
    text_to_check = " ".join(args)
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    system = build_harvi_system()
    prompt = (
        f"The user wrote: \"{text_to_check}\"\n\n"
        f"Check this for grammar mistakes. If there are errors:\n"
        f"1. Show the corrected version\n"
        f"2. Briefly explain the main error(s) in 2-3 sentences\n"
        f"If it's already correct, say so and give a small compliment.\n"
        f"Keep it friendly and under 150 words."
    )
    try:
        reply = call_openrouter(system, prompt, max_tokens=200)
        if not reply:
            reply = "Sorry, I couldn't check that right now. Try again in a moment! 😅"
    except Exception:
        reply = "Sorry, I couldn't check that right now. Try again in a moment! 😅"
    await update.message.reply_text(f"📝 *Grammar Check:*\n\n{reply}", parse_mode="Markdown")


async def cmd_talk(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Start a conversation practice session with Harvi."""
    ctx.user_data["talk_mode"] = True
    ctx.user_data["talk_history"] = []
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    system = build_harvi_system()
    prompt = (
        "Start a friendly English conversation practice session with Vladimir. "
        "Pick an interesting topic (could be travel, technology, daily life, movies, etc.) "
        "and ask him one engaging question in English. "
        "Keep it under 50 words. Be warm and encouraging."
    )
    try:
        opening = call_openrouter(system, prompt, max_tokens=100)
        if not opening:
            opening = "Let's practice English! 🗣 Tell me — what's the most interesting place you've visited? Describe it in a few sentences!"
    except Exception:
        opening = "Let's practice English! 🗣 Tell me — what's the most interesting place you've visited? Describe it in a few sentences!"
    ctx.user_data["talk_history"].append({"role": "assistant", "content": opening})
    await update.message.reply_text(
        f"🗣 *Conversation Practice started!*\n\n{opening}\n\n_Type your reply freely. Use /endtalk to finish._",
        parse_mode="Markdown"
    )


async def cmd_endtalk(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """End the conversation practice session."""
    if not ctx.user_data.get("talk_mode"):
        await update.message.reply_text("No active conversation session. Use /talk to start one! 😺")
        return
    history = ctx.user_data.get("talk_history", [])
    # Count user messages
    user_msgs = [m for m in history if m["role"] == "user"]
    msg_count = len(user_msgs)

    ctx.user_data["talk_mode"] = False
    ctx.user_data["talk_history"] = []

    if msg_count == 0:
        await update.message.reply_text(
            "Session ended — but you didn't say anything! 😸 Start again with /talk whenever you're ready."
        )
        return

    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    system = build_harvi_system()
    history_text = "\n".join(
        f"{'Vladimir' if m['role'] == 'user' else 'Harvi'}: {m['content']}"
        for m in history
    )
    prompt = (
        f"Here is the conversation we just had:\n{history_text}\n\n"
        f"Give a short session report (3-4 sentences):\n"
        f"1. How many messages Vladimir sent ({msg_count} messages)\n"
        f"2. 2-3 specific grammar/vocabulary improvements he could make (be concrete)\n"
        f"3. One genuine compliment about his English\n"
        f"Be warm and encouraging, not preachy."
    )
    try:
        report = call_openrouter(system, prompt, max_tokens=200)
        if not report:
            report = f"Great session! You sent {msg_count} messages. Keep practicing — every conversation counts! 🎉"
    except Exception:
        report = f"Great session! You sent {msg_count} messages. Keep practicing — every conversation counts! 🎉"

    await update.message.reply_text(
        f"✅ *Conversation session ended!*\n\n"
        f"📊 Messages: {msg_count}\n\n"
        f"{report}",
        parse_mode="Markdown"
    )


async def cmd_skilltree(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show the skill tree with visual progress bars."""
    stats = get_all_stats()
    skill_info = [
        ("📱", "Duolingo",  "duolingo"),
        ("📖", "Reading",   "reading"),
        ("🎧", "Listening", "listening"),
        ("🗣", "Speaking",  "speaking"),
        ("🃏", "SRS",       "srs"),
        ("✍️", "Writing",   "writing"),
    ]
    lines = [
        "⚔️ SKILL TREE",
        "═" * 20,
    ]
    for emoji, name, key in skill_info:
        xp = stats["skill_xp"][key]
        lv = skill_level(xp)
        if lv >= len(SKILL_LEVEL_XP) - 1:
            bar = "█" * 12
        else:
            lo = SKILL_LEVEL_XP[lv]
            hi = SKILL_LEVEL_XP[lv + 1]
            pct = (xp - lo) / (hi - lo) if hi > lo else 1.0
            filled = int(pct * 12)
            bar = "█" * filled + "░" * (12 - filled)
        lines.append(f"{emoji} {name:<10} Lv{lv} {bar}")
    lines.append("═" * 20)
    lines.append(f"Total skill XP: {sum(stats['skill_xp'].values()):.0f}")
    await update.message.reply_text(f"```\n" + "\n".join(lines) + "\n```", parse_mode="Markdown")


async def cmd_memory(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show what Harvi remembers about Vladimir."""
    memories = get_memories(50)
    if not memories:
        await update.message.reply_text(
            "🧠 *Harvi's Memory*\n\nNothing stored yet! "
            "Chat with me for a while and I'll start remembering things about you. 🐱",
            parse_mode="Markdown"
        )
        return

    cat_icons = {
        "progress": "📊", "goals": "🎯", "habits": "📅",
        "personal": "👤", "problems": "⚠️", "general": "💡",
    }
    by_cat: dict = {}
    for m in memories:
        cat = m.get("category", "general").lower()
        by_cat.setdefault(cat, []).append(m["value"])

    lines = ["🧠 *What Harvi Remembers About You*\n"]
    for cat in ["progress", "goals", "habits", "personal", "problems", "general"]:
        items = by_cat.get(cat, [])
        if not items:
            continue
        icon = cat_icons.get(cat, "💬")
        lines.append(f"{icon} *{cat.capitalize()}*")
        for v in items[:6]:
            lines.append(f"  • {v}")
        lines.append("")

    lines.append(f"_Total: {len(memories)} memories stored_")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_forget(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Clear all Harvi's memories."""
    if not _supa:
        await update.message.reply_text("No Supabase connection — nothing to forget.")
        return
    try:
        _supa.table("english_memory").delete().neq("id", 0).execute()
        global _memory_cache, _memory_cache_ts
        _memory_cache = []
        _memory_cache_ts = 0
        await update.message.reply_text("🗑 Done — my memory has been cleared. Fresh start! 🐱")
    except Exception as e:
        await update.message.reply_text(f"Error clearing memory: {e}")


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
    seed_from_supabase()
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

    from telegram.ext import MessageHandler, filters

    app.add_handler(CommandHandler("start",        cmd_start))
    app.add_handler(CommandHandler("stats",        cmd_stats))
    app.add_handler(CommandHandler("achievements", cmd_achievements))
    app.add_handler(CommandHandler("quests",       cmd_quests))
    app.add_handler(CommandHandler("month",        cmd_month))
    app.add_handler(CommandHandler("week",         cmd_week))
    app.add_handler(CommandHandler("edit",         cmd_edit))
    app.add_handler(CommandHandler("grammar",      cmd_grammar))
    app.add_handler(CommandHandler("talk",         cmd_talk))
    app.add_handler(CommandHandler("endtalk",      cmd_endtalk))
    app.add_handler(CommandHandler("skilltree",    cmd_skilltree))
    app.add_handler(CommandHandler("memory",       cmd_memory))
    app.add_handler(CommandHandler("forget",       cmd_forget))
    app.add_handler(conv)
    app.add_handler(level_conv)
    # free-text AI — must be last
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_free_text))

    app.job_queue.run_daily(morning_recommendation_job, time=dtime(hour=10, minute=0))
    app.job_queue.run_daily(midday_message_job,         time=dtime(hour=13, minute=0))
    app.job_queue.run_daily(streak_warning_job,         time=dtime(hour=19, minute=0))
    app.job_queue.run_daily(checkin_final_reminder_job, time=dtime(hour=20, minute=30))
    app.job_queue.run_daily(evening_checkin_job,        time=dtime(hour=EVENING_HOUR, minute=EVENING_MINUTE))

    log.info("Bot started.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
