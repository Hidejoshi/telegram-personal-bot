import os
import sqlite3
import re
import pytz
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from collections import Counter

from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters

# ---------------- CONFIG ----------------

TOKEN = os.environ.get("BOT_TOKEN")
DB_PATH = "database.db"
TZ = pytz.timezone("Europe/Warsaw")

PORT = int(os.environ.get("PORT", 10000))

# ---------------- DUMMY WEB SERVER (RENDER NEEDS PORT) ----------------

class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_http_server():
    server = HTTPServer(("0.0.0.0", PORT), DummyHandler)
    server.serve_forever()

# ---------------- DATABASE ----------------

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
        item TEXT
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

# ---------------- UTILS ----------------

def today():
    return datetime.now(TZ).strftime("%Y-%m-%d")

def now_time():
    return datetime.now(TZ).strftime("%H:%M")

def norm(t: str):
    return t.lower().strip()

# ---------------- MAIN HANDLER ----------------

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text_raw = update.message.text
    text = norm(text_raw)
    lines = [norm(l) for l in text_raw.split("\n")]
    day = today()

    conn = get_conn()
    c = conn.cursor()

    # ----- WATER -----
    if text == "вода":
        c.execute("SELECT glasses FROM water WHERE day=?", (day,))
        row = c.fetchone()
        if row:
            total = row[0] + 1
            c.execute("UPDATE water SET glasses=? WHERE day=?", (total, day))
        else:
            total = 1
            c.execute("INSERT INTO water VALUES (?,?)", (day, total))
        conn.commit()
        await update.message.reply_text(f"Додано\nВода: +1\nРазом: {total}")
        return

    # ----- FOOD -----
    if lines[0].startswith("їжа"):
        meal_type = lines[0].replace("їжа", "").strip()
        if meal_type not in ["сніданок", "обід", "вечеря", "перекус"]:
            await update.message.reply_text("Помилка: тип їжі")
            return

        if len(lines) < 2:
            await update.message.reply_text("Помилка: немає продуктів")
            return

        products = [p.strip() for p in lines[1].split(",")]
        calories = 0

        for p in products:
            c.execute("SELECT calories FROM food_dict WHERE name=?", (p,))
            r = c.fetchone()
            if not r:
                await update.message.reply_text(f"Немає продукту: {p}")
                return
            calories += r[0]

        if meal_type == "перекус":
            for p in products:
                c.execute("INSERT INTO snacks VALUES (?,?)", (day, p))
        else:
            c.execute(
                "INSERT INTO meals VALUES (?,?,?,?,?)",
                (day, meal_type, now_time(), ", ".join(products), calories)
            )

        conn.commit()
        await update.message.reply_text(
            f"Додано\nЇжа: {meal_type}\nПродукти: {', '.join(products)}\nКкал: {calories}\nЧас: {now_time()}"
        )
        return

    # ----- EXPENSE -----
    if text == "витрати" and len(lines) > 1:
        amt = float(lines[1].replace(",", "."))
        c.execute("INSERT INTO expenses VALUES (?,?)", (day, amt))
        conn.commit()
        await update.message.reply_text(f"Додано\nВитрати: {amt:.2f} zł")
        return

    # ----- INCOME -----
    if text == "дохід" and len(lines) > 1:
        m = re.search(r"([\d.,]+)\s*(\w+)", lines[1])
        amt = float(m.group(1).replace(",", "."))
        cur_raw = m.group(2)
        cur = "$" if "дол" in cur_raw else "zł"
        c.execute("INSERT INTO income VALUES (?,?,?)", (day, amt, cur))
        conn.commit()
        await update.message.reply_text(f"Додано\nДохід: {amt:.2f} {cur}")
        return

    # ----- SUMMARY WATER -----
    if text == "підсумок вода":
        c.execute("SELECT glasses FROM water WHERE day=?", (day,))
        r = c.fetchone()
        await update.message.reply_text(f"вода – {r[0] if r else 0}")
        return

    # ----- SUMMARY FOOD -----
    if text == "підсумок їжа":
        out = []
        total = 0

        c.execute("SELECT type,time,items,calories FROM meals WHERE day=?", (day,))
        for m in c.fetchall():
            out.append(f"{m[0]} ({m[1]})\n{m[2]}\n{m[3]} ккал\n")
            total += m[3]

        c.execute("SELECT item FROM snacks WHERE day=?", (day,))
        snacks = [s[0] for s in c.fetchall()]
        if snacks:
            cnt = Counter(snacks)
            out.append("Перекус:\n" + ", ".join(f"{k} x{v}" for k, v in cnt.items()))

        out.append(f"\nЗАГАЛОМ ЗА ДЕНЬ: {total} ккал")
        await update.message.reply_text("\n".join(out))
        return

    # ----- SUMMARY DAY -----
    if text == "підсумок день":
        c.execute("SELECT SUM(glasses) FROM water WHERE day=?", (day,))
        w = c.fetchone()[0] or 0

        c.execute("SELECT SUM(amount) FROM expenses WHERE day=?", (day,))
        exp = c.fetchone()[0] or 0

        c.execute("SELECT currency, SUM(amount) FROM income WHERE day=? GROUP BY currency", (day,))
        inc = "\n".join(f"{r[0]} – {r[1]:.2f}" for r in c.fetchall())

        await update.message.reply_text(
            f"ПІДСУМОК ЗА ДЕНЬ\n\nВода – {w}\n\nВитрати – {exp:.2f} zł\n\nДохід:\n{inc}"
        )
        return

# ---------------- START ----------------

if __name__ == "__main__":
    init_db()

    threading.Thread(target=run_http_server, daemon=True).start()

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    app.run_polling()
