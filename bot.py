import os
import sqlite3
from datetime import datetime, date, timedelta
import pytz
import re
from collections import Counter
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters

TZ = pytz.timezone("Europe/Warsaw")
DB_PATH = "database.db"
TOKEN = os.environ.get("BOT_TOKEN")

# ================= DATABASE =================

def get_conn():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS food_dict (
        name TEXT PRIMARY KEY,
        calories INTEGER
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS meals (
        day TEXT,
        type TEXT,
        time TEXT,
        items TEXT,
        calories INTEGER
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS snacks (
        day TEXT,
        item TEXT,
        calories INTEGER
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS water (
        day TEXT PRIMARY KEY,
        glasses INTEGER
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS expenses (
        day TEXT,
        amount REAL
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS income (
        day TEXT,
        amount REAL,
        currency TEXT
    )""")

    foods = {
        "картопля":257,"рис":288,"яйця":156,"макарони":288,"фарш":384,
        "курка":323,"помідор":23,"мікс салат":123,"кабачок":12,
        "морква":20,"огірок":8,"броколі":17,"кукурудза":96,
        "квашені огірки":12,"хлібці + паста + фрукт":155,"яблуко":78,
        "банан":108,"апельсин":62,"мандарин":53,"шоколадка":130,
        "печиво":150,"кола":105,"хліб":80,"кава чорна":2,
        "чай чорний/зелений":2,"горіхи":150,"сушка":100,"авокадо":200
    }

    for k, v in foods.items():
        c.execute("INSERT OR IGNORE INTO food_dict VALUES (?,?)", (k, v))

    conn.commit()
    conn.close()

# ================= UTILS =================

def today():
    return datetime.now(TZ).strftime("%Y-%m-%d")

def now_time():
    return datetime.now(TZ).strftime("%H:%M")

def norm(t):
    return t.lower().strip()

# ================= HANDLER =================

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    raw = update.message.text
    lines = [norm(l) for l in raw.split("\n")]
    text = lines[0]
    day = today()

    conn = get_conn()
    c = conn.cursor()

    # ---------- WATER ----------
    if text == "вода":
        c.execute("SELECT glasses FROM water WHERE day=?", (day,))
        row = c.fetchone()
        if row:
            total = row[0] + 1
            c.execute("UPDATE water SET glasses=? WHERE day=?", (total, day))
        else:
            total = 1
            c.execute("INSERT INTO water VALUES (?,?)", (day, 1))
        conn.commit()
        await update.message.reply_text(f"Вода +1\nРазом сьогодні: {total}")
        return

    # ---------- FOOD ----------
    if text.startswith("їжа"):
        meal_type = text.replace("їжа", "").strip()
        if meal_type not in ["сніданок", "обід", "вечеря", "перекус"]:
            await update.message.reply_text("Невідомий тип їжі")
            return

        if len(lines) < 2:
            await update.message.reply_text("Немає списку продуктів")
            return

        products = [p.strip() for p in lines[1].split(",")]
        calories = 0

        for p in products:
            c.execute("SELECT calories FROM food_dict WHERE name=?", (p,))
            row = c.fetchone()
            if not row:
                await update.message.reply_text(f"Продукт «{p}» не знайдено")
                return
            calories += row[0]

        if meal_type == "перекус":
            for p in products:
                c.execute("SELECT calories FROM food_dict WHERE name=?", (p,))
                cal = c.fetchone()[0]
                c.execute("INSERT INTO snacks VALUES (?,?,?)", (day, p, cal))
        else:
            c.execute(
                "INSERT INTO meals VALUES (?,?,?,?,?)",
                (day, meal_type, now_time(), ", ".join(products), calories)
            )

        conn.commit()
        await update.message.reply_text(
            f"Додано: {meal_type}\nКкал: {calories}"
        )
        return

    # ---------- EXPENSE ----------
    if text == "витрати" and len(lines) > 1:
        try:
            amt = float(lines[1].replace(",", "."))
        except:
            await update.message.reply_text("Невірна сума")
            return
        c.execute("INSERT INTO expenses VALUES (?,?)", (day, amt))
        conn.commit()
        await update.message.reply_text(f"Витрати: {amt:.2f} zł")
        return

    # ---------- INCOME (supports minus) ----------
    if text == "дохід" and len(lines) > 1:
        m = re.search(r"(-?[\d.,]+)\s*(\w+)?", lines[1])
        if not m:
            await update.message.reply_text("Невірний формат доходу")
            return

        amt = float(m.group(1).replace(",", "."))
        cur_raw = (m.group(2) or "").lower()

        if "дол" in cur_raw or "$" in cur_raw or "usd" in cur_raw:
            cur = "$"
        else:
            cur = "zł"

        c.execute("INSERT INTO income VALUES (?,?,?)", (day, amt, cur))
        conn.commit()
        await update.message.reply_text(f"Дохід: {amt:+.2f} {cur}")
        return

    # ---------- SUMMARY WATER ----------
    if text == "підсумок вода":
        c.execute("SELECT glasses FROM water WHERE day=?", (day,))
        g = c.fetchone()
        await update.message.reply_text(f"Вода: {g[0] if g else 0}")
        return

    # ---------- SUMMARY FOOD ----------
    if text == "підсумок їжа":
        out = []
        total = 0

        c.execute("SELECT type,time,items,calories FROM meals WHERE day=?", (day,))
        for t, tm, it, cal in c.fetchall():
            out.append(f"{t} ({tm})\n{it}\n{cal} ккал\n")
            total += cal

        c.execute("SELECT item,calories FROM snacks WHERE day=?", (day,))
        snacks = c.fetchall()
        if snacks:
            cnt = Counter(i for i, _ in snacks)
            snack_cal = sum(cal for _, cal in snacks)
            total += snack_cal
            out.append("Перекуси:\n" + ", ".join(f"{k} x{v}" for k, v in cnt.items()))
            out.append(f"Ккал перекусів: {snack_cal}")

        out.append(f"\nРАЗОМ: {total} ккал")
        await update.message.reply_text("\n".join(out))
        return

    # ---------- SUMMARY DAY ----------
    if text == "підсумок день":
        c.execute("SELECT glasses FROM water WHERE day=?", (day,))
        w = c.fetchone()
        water = w[0] if w else 0

        c.execute("SELECT SUM(calories) FROM meals WHERE day=?", (day,))
        food = c.fetchone()[0] or 0
        c.execute("SELECT SUM(calories) FROM snacks WHERE d
