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

    # food dictionary
    foods = {
        "картопля":257,"рис":288,"яйця":156,"макарони":288,"фарш":384,
        "курка":323,"помідор":23,"мікс салат":123,"кабачок":12,
        "морква":20,"огірок":8,"броколі":17,"кукурудза":96,
        "квашені огірки":12,"хлібці + паста + фрукт":155,"яблуко":78,
        "банан":108,"апельсин":62,"мандарин":53,"шоколадка":130,
        "печиво":150,"кола":105,"хліб":80,"кава чорна":2,
        "чай чорний/зелений":2,"горіхи":150,"сушка":100,"авокадо":200
    }

    for k,v in foods.items():
        c.execute("INSERT OR IGNORE INTO food_dict VALUES (?,?)",(k,v))

    conn.commit()
    conn.close()

# ---------------- UTILS ----------------

def today():
    return datetime.now(TZ).strftime("%Y-%m-%d")

def now_time():
    return datetime.now(TZ).strftime("%H:%M")

def norm(t):
    return t.lower().strip()

# ---------------- HANDLER ----------------

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = norm(update.message.text)
    lines = [norm(l) for l in update.message.text.split("\n")]
    day = today()

    conn = get_conn()
    c = conn.cursor()

    # -------- WATER --------
    if text == "вода":
        c.execute("SELECT glasses FROM water WHERE day=?",(day,))
        row = c.fetchone()
        if row:
            c.execute("UPDATE water SET glasses=glasses+1 WHERE day=?",(day,))
            total = row[0]+1
        else:
            c.execute("INSERT INTO water VALUES (?,1)",(day,))
            total = 1
        conn.commit()
        await update.message.reply_text(f"Додано\nВода: +1 склянка\nРазом сьогодні: {total}")
        return

    # -------- FOOD --------
    if lines[0].startswith("їжа"):
        meal_type = lines[0].replace("їжа","").strip()
        if meal_type not in ["сніданок","обід","вечеря","перекус"]:
            await update.message.reply_text("Помилка: невідомий тип прийому їжі")
            return

        if len(lines) < 2:
            await update.message.reply_text("Помилка: немає списку продуктів")
            return

        products = [p.strip() for p in lines[1].split(",")]
        calories = 0

        for p in products:
            c.execute("SELECT calories FROM food_dict WHERE name=?",(p,))
            row = c.fetchone()
            if not row:
                await update.message.reply_text(f"Помилка: продукт «{p}» відсутній")
                return
            calories += row[0]

        if meal_type == "перекус":
            for p in products:
                c.execute("INSERT INTO snacks VALUES (?,?)",(day,p))
        else:
            c.execute("INSERT INTO meals VALUES (?,?,?,?,?)",
                (day,meal_type,now_time(),", ".join(products),calories))

        conn.commit()
        await update.message.reply_text(
            f"Додано\nЇжа: {meal_type}\nПродукти: {', '.join(products)}\nКкал: {calories}\nЧас: {now_time()}"
        )
        return

    # -------- EXPENSE --------
    if text == "витрати" and len(lines) > 1:
        amt = float(lines[1].replace(",","."))        
        c.execute("INSERT INTO expenses VALUES (?,?)",(day,amt))
        conn.commit()
        await update.message.reply_text(f"Додано\nВитрати: {amt:.2f} zł")
        return

    # -------- INCOME --------
    if text == "дохід" and len(lines) > 1:
        m = re.search(r"([\d.,]+)\s*(\w+)",lines[1])
        amt = float(m.group(1).replace(",","."))       
        cur = m.group(2)
        cur = "$" if "дол" in cur else "zł"
        c.execute("INSERT INTO income VALUES (?,?,?)",(day,amt,cur))
        conn.commit()
        await update.message.reply_text(f"Додано\nДохід: {amt:.2f} {cur}")
        return

    # -------- SUMMARY WATER --------
    if text == "підсумок вода":
        c.execute("SELECT glasses FROM water WHERE day=?",(day,))
        g = c.fetchone()
        await update.message.reply_text(f"вода – {g[0] if g else 0}")
        return

    # -------- SUMMARY FOOD --------
    if text == "підсумок їжа":
        out=[]
        total=0
        c.execute("SELECT type,time,items,calories FROM meals WHERE day=?",(day,))
        for m in c.fetchall():
            out.append(f"{m[0].capitalize()} ({m[1]})\n{m[2]}\n{m[3]} ккал\n")
            total+=m[3]

        c.execute("SELECT item FROM snacks WHERE day=?",(day,))
        sn = [s[0] for s in c.fetchall()]
        if sn:
            cnt = Counter(sn)
            out.append("Перекус:\n"+", ".join(f"{k} x{v}" for k,v in cnt.items()))

        out.append(f"\nЗАГАЛОМ ЗА ДЕНЬ: {total} ккал")
        await update.message.reply_text("\n".join(out))
        return

    # -------- SUMMARY DAY --------
    if text == "підсумок день":
        await handle(update,context)
        c.execute("SELECT SUM(amount) FROM expenses WHERE day=?",(day,))
        exp = c.fetchone()[0] or 0
        c.execute("SELECT currency,SUM(amount) FROM income WHERE day=? GROUP BY currency",(day,))
        inc = "\n".join(f"{r[0]} – {r[1]:.2f}" for r in c.fetchall())
        c.execute("SELECT glasses FROM water WHERE day=?",(day,))
        w = c.fetchone()
        await update.message.reply_text(
            f"Вода – {w[0] if w else 0}\n\nВитрати – {exp:.2f} zł\n\nДохід:\n{inc}"
        )
        return

# ---------------- MAIN ----------------

if __name__=="__main__":
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    app.run_polling()
