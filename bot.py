import os
import sqlite3
from datetime import datetime, timedelta
import pytz
from flask import Flask
import threading


from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters, CommandHandler

TOKEN = "8223596389:AAFZ2JkhlziySUWLVzY7g0hNN0hwtm9PL-0"
DB_PATH = "database.db"
TZ = pytz.timezone("Europe/Warsaw")
GLASS_ML = 300
GOAL_WATER_GLASSES = 8
GOAL_CALORIES = 2750

# ================== DB ==================

def get_conn():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.executescript("""
DROP TABLE IF EXISTS food_dict;
DROP TABLE IF EXISTS meals;
DROP TABLE IF EXISTS snacks;
DROP TABLE IF EXISTS water;
DROP TABLE IF EXISTS expenses;
DROP TABLE IF EXISTS income;
DROP TABLE IF EXISTS supplements;

CREATE TABLE food_dict (
    name TEXT PRIMARY KEY,
    calories INTEGER
);

CREATE TABLE meals (
    day TEXT,
    type TEXT,
    time TEXT,
    items TEXT,
    calories INTEGER
);

CREATE TABLE snacks (
    day TEXT,
    items TEXT,
    calories INTEGER
);

CREATE TABLE water (
    day TEXT PRIMARY KEY,
    glasses INTEGER
);

CREATE TABLE expenses (
    day TEXT,
    amount REAL
);

CREATE TABLE income (
    day TEXT,
    amount REAL,
    currency TEXT
);

CREATE TABLE supplements (
    day TEXT,
    name TEXT,
    time TEXT
);
""")

    

    foods = {
        # гарніри
    "рис": 104, "макарони": 360, "гречка": 130, "картопля": 254, "хлібці": 40,

    # м’ясо / білок
    "фарш": 420, "курка": 209, "лосось": 200, "сосиски": 150, "тунець": 130, "бекон": 450, "кабанос": 450,

    # овочі
    "помідор": 23, "салат": 25, "овочі": 70, "огірок": 15, "кукурудза": 96, "паприка": 200, "брокколі": 35,
    "шпинат": 20, "морква": 25, "цибуля": 40, "бальзамік": 15,

    # фрукти
    "апельсин": 70, "яблуко": 120, "банан": 135, "фінік": 200, "полуниця": 35, "варення": 120,

    # солодке / молочка
    "цукор": 25, "шоколад": 190, "кремчіз": 300, "йогурт": 120, "творог": 160,

    # фастфуд
    "піца": 280, "макменю": 900, "кебаб": 750, "хотдог": 120,

    # соуси
    "майонез": 200, "кетчуп": 110, "аджика": 55
    }

    for k,v in foods.items():
        c.execute("INSERT INTO food_dict VALUES (?,?)", (k,v))

    conn.commit()
    conn.close()

# ================== UTILS ==================

def today():
    return datetime.now(TZ).strftime("%Y-%m-%d")

def now():
    return datetime.now(TZ).strftime("%H:%M")

# ================== HANDLER ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot is running and working properly.")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 Довідка по командах бота\n\n"

        "🍽 ЇЖА\n"
        "сніданок <продукти> — запис сніданку\n"
        "обід <продукти> — запис обіду\n"
        "вечеря <продукти> — запис вечері\n"
        "перекус <продукти> — запис перекусу\n\n"

        "💊 ДОБАВКИ / ЛІКИ\n"
        "добавки <назва> — запис добавок або ліків\n\n"

        "💧 ВОДА\n"
        "вода — +1 склянка води (300 мл)\n\n"

        "💰 ФІНАНСИ\n"
        "витрати <сума> — запис витрат (PLN)\n"
        "дохід <сума> д — дохід у доларах (USD)\n"
        "дохід <сума> з — дохід у злотих (PLN)\n\n"

        "📊 ПІДСУМКИ\n"
        "підсумок їжа — калорії за день\n"
        "підсумок вода — випита вода за день\n"
        "підсумок витрати — витрати за день\n"
        "підсумок дохід — дохід за день\n"
        "підсумок добавки — добавки / ліки за день\n"
        "підсумок день — повний підсумок дня\n"
        "підсумок тиждень — фінанси за тиждень\n"
        "підсумок місяць — фінанси за місяць\n\n"

        "ℹ️ СИСТЕМА\n"
        "/start — перевірка роботи бота\n"
        "/help — ця довідка"
    )

    await update.message.reply_text(text)

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower().strip()
    parts = text.split()
    day = today()

    conn = get_conn()
    c = conn.cursor()

    
    # ===== ДОБАВКИ =====
    if parts[0] == "добавки" and len(parts) > 1:
        name = " ".join(parts[1:])
        time_now = now()

        c.execute(
            "INSERT INTO supplements VALUES (?,?,?)",
            (day, name, time_now)
        )
        conn.commit()

        await update.message.reply_text(f"💊 {name} {time_now}")
        return

    # ===== ВОДА =====
    if text == "вода":
        c.execute("SELECT glasses FROM water WHERE day=?", (day,))
        row = c.fetchone()
        g = row[0] + 1 if row else 1
        c.execute("REPLACE INTO water VALUES (?,?)", (day, g))
        conn.commit()
        await update.message.reply_text(f"💧 {g} скл = {g*GLASS_ML} мл")
        return

    # ===== ЇЖА =====
    if parts[0] in ("сніданок","обід","вечеря","перекус"):
        meal = parts[0]
        items = parts[1:]
        if not items:
            await update.message.reply_text("❌ нема продуктів")
            return

        cal = 0
        for i in items:
            c.execute("SELECT calories FROM food_dict WHERE name=?", (i,))
            r = c.fetchone()
            if not r:
                await update.message.reply_text(f"❌ нема: {i}")
                return
            cal += r[0]

        if meal == "перекус":
            c.execute("INSERT INTO snacks VALUES (?,?,?)", (day,", ".join(items),cal))
        else:
            c.execute("INSERT INTO meals VALUES (?,?,?,?,?)",
                      (day,meal,now(),", ".join(items),cal))
        conn.commit()
        await update.message.reply_text(f"🍽 {meal} — {cal} ккал")
        return

    # ===== ВИТРАТИ =====
    if parts[0] == "витрати":
        amt = float(parts[1])
        c.execute("INSERT INTO expenses VALUES (?,?)", (day,amt))
        conn.commit()
        await update.message.reply_text(f"💸 {amt} zł")
        return

    # ===== ДОХІД =====
    if parts[0] == "дохід":
        amt = float(parts[1])
        cur = "USD" if parts[2].startswith("д") else "PLN"
        c.execute("INSERT INTO income VALUES (?,?,?)", (day,amt,cur))
        conn.commit()
        await update.message.reply_text(f"💰 {amt} {cur}")
        return

# ================== ПІДСУМКИ ==================
    
    # ===== ПІДСУМОК ЇЖІ =====
    if text == "підсумок їжа":
        out, total = [], 0
        c.execute("SELECT type,time,items,calories FROM meals WHERE day=?", (day,))
        for t,tm,it,cal in c.fetchall():
            out.append(f"{t} ({tm})\n{it} — {cal} ккал\n")
            total += cal

        c.execute("SELECT items,calories FROM snacks WHERE day=?", (day,))
        snacks = c.fetchall()
        if snacks:
            sc = sum(s[1] for s in snacks)
            out.append("Перекус:")
            for it,cal in snacks:
                out.append(f"{it} — {cal}")
            out.append(f"Разом перекус: {sc}")
            total += sc

        out.append(f"🔥 Калорії: {total} / {GOAL_CALORIES}")
        await update.message.reply_text("\n".join(out))
        return

    # ===== ПІДСУМОК води =====
    if text == "підсумок вода":
        c.execute("SELECT glasses FROM water WHERE day=?", (day,))
        row = c.fetchone()

        glasses = row[0] if row else 0
        ml = glasses * 300

        await update.message.reply_text(
            f"💧 Вода: {glasses} / {GOAL_WATER_GLASSES} скл ({glasses * GLASS_ML} мл)"
        )
        return

    # ===== ПІДСУМОК витрати =====
    if text == "підсумок витрати":
        c.execute("SELECT SUM(amount) FROM expenses WHERE day=?", (day,))
        total = c.fetchone()[0] or 0

        await update.message.reply_text(
            f"💸 Витрати за день: {total:.2f} zł"
        )
        return

    # ===== ПІДСУМОК дохід =====
    if text == "підсумок дохід":
        c.execute("""
            SELECT currency, SUM(amount)
            FROM income
            WHERE day=?
            GROUP BY currency
        """, (day,))
        rows = c.fetchall()

        if not rows:
            await update.message.reply_text("💰 Дохід за день: 0")
            return

        out = ["💰 Дохід за день:"]
        for cur, total in rows:
            out.append(f"- {total:.2f} {cur}")

        await update.message.reply_text("\n".join(out))
        return
    
     # ===== ПІДСУМОК ДОБАВОК =====
    if text == "підсумок добавки":
        c.execute(
            "SELECT name, time FROM supplements WHERE day=?",
            (day,)
        )
        rows = c.fetchall()

        if not rows:
            await update.message.reply_text("💊 Добавок за день нема")
            return

        out = ["💊 Добавки / ліки:"]
        for name, tm in rows:
            out.append(f"{name} {tm}")

        await update.message.reply_text("\n".join(out))
        return
        
    # ===== ПІДСУМОК ДЕНЬ =====
        
    if text == "підсумок день":
        out = []
        total_cal = 0
        out.append(f"📅 {datetime.now(TZ).strftime('%d.%m.%Y')} — підсумок дня\n")
        
        # основні прийоми їжі
        c.execute("SELECT type, time, items, calories FROM meals WHERE day=?", (day,))
        meals = c.fetchall()
        for t, tm, items, cal in meals:
            out.append(f"{t.capitalize()} ({tm})")
            out.append(f"{items}")
            out.append(f"{cal} ккал\n")
            total_cal += cal

        # перекуси
        c.execute("SELECT items, calories FROM snacks WHERE day=?", (day,))
        snacks = c.fetchall()
        if snacks:
            out.append("Перекус:")
            snack_total = 0
            for items, cal in snacks:
                out.append(f"- {items} ({cal} ккал)")
                snack_total += cal
            out.append(f"Разом перекус: {snack_total} ккал")
            total_cal += snack_total

        # 🔥 загалом калорії — ОДРАЗУ після перекусу
        out.append(f"🔥 Калорії: {total_cal} / {GOAL_CALORIES}")

        # вода — наступним рядком
        c.execute("SELECT glasses FROM water WHERE day=?", (day,))
        w = c.fetchone()
        glasses = w[0] if w else 0
        out.append(f"💧 Вода: {glasses} / {GOAL_WATER_GLASSES} скл ({glasses * GLASS_ML} мл)")

        # добавки
        c.execute(
            "SELECT name, time FROM supplements WHERE day=?",
            (day,)
        )
        supps = c.fetchall()

        if supps:
            out.append("\n💊 Добавки / ліки:")
            for name, tm in supps:
                out.append(f"{name} {tm}")

        # витрати
        c.execute("SELECT SUM(amount) FROM expenses WHERE day=?", (day,))
        expenses = c.fetchone()[0] or 0
        out.append(f"\n💸 Витрати: {expenses} zł")

        # дохід
        c.execute("""
            SELECT currency, SUM(amount)
            FROM income
            WHERE day=?
            GROUP BY currency
        """, (day,))
        incomes = c.fetchall()

        if incomes:
            out.append("💰 Дохід:")
            for cur, val in incomes:
                out.append(f"- {val} {cur}")

        await update.message.reply_text("\n".join(out))
        return

    # ===== СТАТУС =====
    if text == "статус":
        # калорії
        total_cal = 0
        c.execute("SELECT calories FROM meals WHERE day=?", (day,))
        total_cal += sum(r[0] for r in c.fetchall())

        c.execute("SELECT calories FROM snacks WHERE day=?", (day,))
        total_cal += sum(r[0] for r in c.fetchall())

        # вода
        c.execute("SELECT glasses FROM water WHERE day=?", (day,))
        w = c.fetchone()
        glasses = w[0] if w else 0

        # витрати
        c.execute("SELECT SUM(amount) FROM expenses WHERE day=?", (day,))
        expenses = c.fetchone()[0] or 0

        await update.message.reply_text(
            f"📊 Статус\n"
            f"🔥 {total_cal} / {GOAL_CALORIES} ккал\n"
            f"💧 {glasses} / {GOAL_WATER_GLASSES} скл\n"
            f"💸 {expenses:.2f} zł"
        )
        return



    # ===== ПІДСУМОК ТИЖ / МІС =====
    if text in ("підсумок тиждень", "підсумок місяць"):
        nowd = datetime.now(TZ).date()

        if "тиждень" in text:
            start_date = nowd - timedelta(days=nowd.weekday())
        else:
            start_date = nowd.replace(day=1)

        start = start_date.strftime("%Y-%m-%d")
        end = day  # day у тебе вже рядок YYYY-MM-DD

        # витрати
        c.execute(
            "SELECT SUM(amount) FROM expenses WHERE day BETWEEN ? AND ?",
            (start, end)
        )
        expenses = c.fetchone()[0] or 0

        # дохід
        c.execute(
            """SELECT currency, SUM(amount)
               FROM income
               WHERE day BETWEEN ? AND ?
               GROUP BY currency""",
            (start, end)
        )
        incomes = c.fetchall()

        msg = [f"📊 {text.capitalize()}"]
        msg.append(f"💸 Витрати: {expenses:.2f} zł")

        if incomes:
            msg.append("💰 Дохід:")
            for cur, val in incomes:
                msg.append(f"- {val:.2f} {cur}")
        else:
            msg.append("💰 Дохід: 0")

        await update.message.reply_text("\n".join(msg))
        return


def keep_alive():
    app_flask = Flask(__name__)

    @app_flask.route("/")
    def home():
        return "OK"

    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)

threading.Thread(target=keep_alive, daemon=True).start()

# ================== RUN ==================

if __name__ == "__main__":
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

    app.run_polling()
