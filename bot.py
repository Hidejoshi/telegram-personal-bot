import os
import sqlite3
import re
from datetime import datetime, timedelta
import pytz

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    ContextTypes,
    filters
)

# ================== БАЗОВІ НАЛАШТУВАННЯ ==================

TOKEN = os.environ.get("BOT_TOKEN")
DB_PATH = "database.db"
TZ = pytz.timezone("Europe/Warsaw")

# ================== DB ==================

def get_conn():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_conn()
    c = conn.cursor()

    # словник продуктів
    c.execute("""
        CREATE TABLE IF NOT EXISTS food_dict (
            name TEXT PRIMARY KEY,
            calories INTEGER
        )
    """)

    # основні прийоми їжі
    c.execute("""
        CREATE TABLE IF NOT EXISTS meals (
            day TEXT,
            type TEXT,
            time TEXT,
            items TEXT,
            calories INTEGER
        )
    """)

    # перекуси (КОЖЕН ОКРЕМО)
    c.execute("""
        CREATE TABLE IF NOT EXISTS snacks (
            day TEXT,
            item TEXT,
            calories INTEGER
        )
    """)

    # вода
    c.execute("""
        CREATE TABLE IF NOT EXISTS water (
            day TEXT PRIMARY KEY,
            amount INTEGER
        )
    """)

    # витрати
    c.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            day TEXT,
            amount REAL
        )
    """)

    # дохід
    c.execute("""
        CREATE TABLE IF NOT EXISTS income (
            day TEXT,
            amount REAL,
            currency TEXT
        )
    """)

    # продукти
    foods = {
        "картопля":257,"рис":288,"яйця":156,"макарони":288,"фарш":384,
        "курка":323,"помідор":23,"мікс салат":123,"кабачок":12,
        "морква":20,"огірок":8,"броколі":17,"кукурудза":96,
        "квашені огірки":12,"яблуко":78,"банан":108,
        "шоколадка":130,"печиво":150,
        "кола":110,"паста":190,"хлібець":15,"авокадо":120,
        "горіхи":100,"сушка":100,"кебаб":800,"мак":1350,"хліб":255
    }

    for k, v in foods.items():
        c.execute("INSERT OR IGNORE INTO food_dict VALUES (?,?)", (k, v))

    conn.commit()
    conn.close()

# ================== UTILS ==================

def today():
    return datetime.now(TZ).strftime("%Y-%m-%d")

def now_time():
    return datetime.now(TZ).strftime("%H:%M")

def norm(t):
    return t.lower().strip()

# ================== MAIN HANDLER ==================

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = norm(update.message.text)
    lines = [norm(l) for l in update.message.text.split("\n")]
    day = today()

    conn = get_conn()
    c = conn.cursor()

    # ================== ВОДА ==================

    if text == "випив":
        c.execute("SELECT amount FROM water WHERE day=?", (day,))
        row = c.fetchone()

        if row:
            total = row[0] + 1
            c.execute("UPDATE water SET amount=? WHERE day=?", (total, day))
        else:
            total = 1
            c.execute("INSERT INTO water VALUES (?,?)", (day, total))

        conn.commit()
        await update.message.reply_text(f"💧 Вода +1\nРазом: {total}")
        return

    # ================== ЇЖА ==================

    if lines[0].startswith("їжа"):
        meal_type = lines[0].replace("їжа", "").strip()
        products = [p.strip() for p in lines[1].split(",")]

        calories = 0
        for p in products:
            c.execute("SELECT calories FROM food_dict WHERE name=?", (p,))
            row = c.fetchone()
            if not row:
                await update.message.reply_text(f"❌ Немає продукту: {p}")
                return
            calories += row[0]

        if meal_type == "перекус":
            for p in products:
                c.execute("SELECT calories FROM food_dict WHERE name=?", (p,))
                cal = c.fetchone()[0]
                c.execute(
                    "INSERT INTO snacks VALUES (?,?,?)",
                    (day, p, cal)
                )
        else:
            c.execute(
                "INSERT INTO meals VALUES (?,?,?,?,?)",
                (day, meal_type, now_time(), ", ".join(products), calories)
            )

        conn.commit()
        await update.message.reply_text(f"🍽 {meal_type} додано\nКкал: {calories}")
        return

    # ================== ВИТРАТИ ==================

    if lines[0] == "витрати":
        amt = float(lines[1].replace(",", "."))
        c.execute("INSERT INTO expenses VALUES (?,?)", (day, amt))
        conn.commit()
        await update.message.reply_text(f"💸 Витрати: {amt:.2f} zł")
        return

    # ================== ДОХІД (+ і -) ==================

    if lines[0] == "дохід":
        m = re.search(r"(-?[\d.,]+)\s*(\w+)", lines[1])
        amt = float(m.group(1).replace(",", "."))
        cur = "USD" if "usd" in m.group(2) or "дол" in m.group(2) else "PLN"

        c.execute(
            "INSERT INTO income VALUES (?,?,?)",
            (day, amt, cur)
        )
        conn.commit()
        await update.message.reply_text(f"💰 Дохід: {amt:.2f} {cur}")
        return

    # ================== ПІДСУМОК ДНЯ ==================

    if text == "день":
        out = []
        total_cal = 0

        # їжа
        c.execute("SELECT type,time,items,calories FROM meals WHERE day=?", (day,))
        for t, tm, items, cal in c.fetchall():
            out.append(f"{t.capitalize()} ({tm})")
            out.append(items)
            out.append(f"{cal} ккал\n")
            total_cal += cal

        # перекуси
        c.execute("SELECT item,calories FROM snacks WHERE day=?", (day,))
        snacks = c.fetchall()
        if snacks:
            out.append("Перекус:")
            for i, cal in snacks:
                out.append(f"- {i} ({cal} ккал)")
                total_cal += cal

        # вода
        c.execute("SELECT amount FROM water WHERE day=?", (day,))
        water = c.fetchone()
        water = water[0] if water else 0

        # витрати
        c.execute("SELECT SUM(amount) FROM expenses WHERE day=?", (day,))
        expenses = c.fetchone()[0] or 0

        # дохід по валютам
        c.execute("""
            SELECT currency, SUM(amount)
            FROM income
            WHERE day=?
            GROUP BY currency
        """, (day,))
        incomes = c.fetchall()

        out.append(f"\nЗагалом: {total_cal} ккал")
        out.append(f"Вода: {water}")
        out.append(f"Витрати: {expenses:.2f} zł")

        if incomes:
            out.append("Дохід:")
            for cur, total in incomes:
                out.append(f"- {total:.2f} {cur}")

        await update.message.reply_text("\n".join(out))
        return

    # ================== ТІЛЬКИ ЇЖА ==================

    if text == "підсумок їжа":
        out = []
        total = 0

        c.execute("SELECT type,time,items,calories FROM meals WHERE day=?", (day,))
        for t, tm, items, cal in c.fetchall():
            out.append(f"{t.capitalize()} ({tm}) — {cal} ккал")
            total += cal

        c.execute("SELECT calories FROM snacks WHERE day=?", (day,))
        snack_cal = sum(r[0] for r in c.fetchall())
        total += snack_cal

        out.append(f"\nРазом: {total} ккал")
        await update.message.reply_text("\n".join(out))
        return

    # ================== ВОДА ==================

    if text == "підсумок вода":
        c.execute("SELECT amount FROM water WHERE day=?", (day,))
        row = c.fetchone()
        await update.message.reply_text(f"💧 {row[0] if row else 0}")
        return

    # ================== ТИЖДЕНЬ / МІСЯЦЬ ==================

    if text in ("підсумок тиждень", "підсумок місяць"):
        today_dt = datetime.now(TZ).date()
        if text == "тиждень":
            start = today_dt - timedelta(days=today_dt.weekday())
        else:
            start = today_dt.replace(day=1)

        c.execute("SELECT SUM(calories) FROM meals WHERE day BETWEEN ? AND ?", (start, day))
        food = c.fetchone()[0] or 0

        c.execute("SELECT SUM(calories) FROM snacks WHERE day BETWEEN ? AND ?", (start, day))
        food += c.fetchone()[0] or 0

        c.execute("""
            SELECT currency, SUM(amount)
            FROM income
            WHERE day BETWEEN ? AND ?
            GROUP BY currency
        """, (start, day))
        incomes = c.fetchall()

        await update.message.reply_text(
            f"Період {start} → {day}\n"
            f"Калорії: {food}\n" +
            "\n".join(f"{cur}: {total:.2f}" for cur, total in incomes)
        )
        return

# ================== RUN ==================

if __name__ == "__main__":
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    app.run_polling()
