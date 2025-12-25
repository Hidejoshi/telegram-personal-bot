import os
import sqlite3
from datetime import datetime, timedelta
import pytz
import re
from collections import Counter
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters

TZ = pytz.timezone("Europe/Warsaw")
DB_PATH = "database.db"
TOKEN = os.environ.get("BOT_TOKEN")

# ---------- DATABASE ----------

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
        "квашені огірки":12,"яблуко":78,"банан":108,
        "шоколадка":130,"печиво":150
    }

    for k, v in foods.items():
        c.execute("INSERT OR IGNORE INTO food_dict VALUES (?, ?)", (k, v))

    conn.commit()
    conn.close()

# ---------- UTILS ----------

def today():
    return datetime.now(TZ).strftime("%Y-%m-%d")

def now_time():
    return datetime.now(TZ).strftime("%H:%M")

def norm(t):
    return t.lower().strip()

# ---------- HANDLER ----------

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = norm(update.message.text)
    lines = [norm(l) for l in update.message.text.split("\n")]
    day = today()

    conn = get_conn()
    c = conn.cursor()

    # ---- WATER ----
    if text == "вода":
        c.execute("SELECT glasses FROM water WHERE day=?", (day,))
        row = c.fetchone()
        if row:
            c.execute("UPDATE water SET glasses=glasses+1 WHERE day=?", (day,))
            total = row[0] + 1
        else:
            c.execute("INSERT INTO water VALUES (?, 1)", (day,))
            total = 1
        conn.commit()
        await update.message.reply_text(f"Вода +1\nРазом сьогодні: {total}")
        return

    # ---- FOOD ----
    if lines[0].startswith("їжа"):
        meal_type = lines[0].replace("їжа", "").strip()
        products = [p.strip() for p in lines[1].split(",")]
        calories = 0

        for p in products:
            c.execute("SELECT calories FROM food_dict WHERE name=?", (p,))
            row = c.fetchone()
            if not row:
                await update.message.reply_text(f"Немає продукту: {p}")
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
        await update.message.reply_text(f"{meal_type.capitalize()} додано\nКкал: {calories}")
        return

    # ---- EXPENSE ----
    if lines[0] == "витрати":
        amt = float(lines[1].replace(",", "."))
        c.execute("INSERT INTO expenses VALUES (?, ?)", (day, amt))
        conn.commit()
        await update.message.reply_text(f"Витрати: {amt:.2f} PLN")
        return

    # ---- INCOME (+ / -) ----
    if lines[0] == "дохід":
        m = re.search(r"(-?[\d.,]+)\s*(\w+)", lines[1])
        amt = float(m.group(1).replace(",", "."))
        cur = "USD" if "дол" in m.group(2) else "PLN"
        c.execute("INSERT INTO income VALUES (?, ?, ?)", (day, amt, cur))
        conn.commit()
        await update.message.reply_text(f"Дохід: {amt:.2f} {cur}")
        return

    # ---- SUMMARY DAY ----
    if text == "підсумок день":
        out = []
        total_cal = 0

        c.execute("SELECT type, time, items, calories FROM meals WHERE day=?", (day,))
        meals = c.fetchall()
        for m in meals:
            out.append(f"{m[0].capitalize()} ({m[1]})\n{m[2]}\n{m[3]} ккал")
            total_cal += m[3]

        c.execute("SELECT item, calories FROM snacks WHERE day=?", (day,))
        snacks = c.fetchall()
        if snacks:
            out.append("Перекуси:")
            for s in snacks:
                out.append(f"- {s[0]} ({s[1]} ккал)")
                total_cal += s[1]

        c.execute("SELECT glasses FROM water WHERE day=?", (day,))
        w = c.fetchone()
        water = w[0] if w else 0

        c.execute("SELECT SUM(amount) FROM expenses WHERE day=?", (day,))
        expenses = c.fetchone()[0] or 0

        c.execute(
            "SELECT currency, SUM(amount) FROM income WHERE day=? GROUP BY currency",
            (day,)
        )
        for cur, total in c.fetchall():
            out.append(f"Дохід: {total:.2f} {cur}")

        out.append(f"\nЗАГАЛОМ ЗА ДЕНЬ: {total_cal} ккал")
        out.append(f"Вода: {water}")
        out.append(f"Витрати: {expenses:.2f} PLN")

        await update.message.reply_text("\n".join(out))
        return

    # -------- SUMMARY FOOD (TODAY) --------
if text == "підсумок їжа":
    out = []
    total_cal = 0

    # основні прийоми їжі
    c.execute(
        "SELECT type, time, items, calories FROM meals WHERE day=? ORDER BY time",
        (day,)
    )
    meals = c.fetchall()

    for m in meals:
        out.append(
            f"{m[0].capitalize()} ({m[1]})\n"
            f"{m[2]}\n"
            f"{m[3]} ккал"
        )
        total_cal += m[3]

    # перекуси
    c.execute(
        "SELECT item, calories FROM snacks WHERE day=?",
        (day,)
    )
    snacks = c.fetchall()

    if snacks:
        out.append("Перекус:")
        for item, cal in snacks:
            out.append(f"- {item} ({cal} ккал)")
            total_cal += cal

    # загальна сума
    out.append(f"\nЗАГАЛОМ ЗА ДЕНЬ: {total_cal} ккал")

    await update.message.reply_text("\n".join(out))
    return

    # ---- SUMMARY WEEK ----
    if text == "підсумок тиждень":
        today_dt = datetime.now(TZ).date()
        start = today_dt - timedelta(days=today_dt.weekday())
        end = today_dt

        c.execute(
            "SELECT SUM(amount) FROM expenses WHERE day BETWEEN ? AND ?",
            (start.isoformat(), end.isoformat())
        )
        expenses = c.fetchone()[0] or 0

        c.execute(
            "SELECT currency, SUM(amount) FROM income WHERE day BETWEEN ? AND ? GROUP BY currency",
            (start.isoformat(), end.isoformat())
        )
        income_lines = [f"Дохід – {t:.2f} {c}" for c, t in c.fe]()_
