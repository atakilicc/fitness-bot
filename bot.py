"""
Kişisel Fitness Takip Botu
---------------------------
Komutlar:
  /start          -> Botu tanıt, kullanıcıyı kaydet
  /kilo 78.5      -> Kiloyu kaydet
  /ogun kahvalti 2 yumurta peynir  -> Öğün kaydet
  /program        -> Bu haftanın antrenman programını gönder
  /ozet           -> Son 7 günün kilo/öğün özetini gönder
  /yardim         -> Komut listesi

Veritabanı: SQLite (fitness.db) - aynı klasörde otomatik oluşturulur.
"""

import logging
import sqlite3
import datetime
import random
import os

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# ---------------------------------------------------------------------------
# AYARLAR
# ---------------------------------------------------------------------------
# Token'ı doğrudan koda yazmak yerine ortam değişkeninden okuyoruz.
# Render.com üzerinde "Environment" sekmesinden BOT_TOKEN olarak ekleyeceksin.
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8807887111:AAFYQGM3NyRFNmLKuR3cxHvjoDrbbFknGaA")

DB_PATH = os.path.join(os.path.dirname(__file__), "fitness.db")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# VERİTABANI
# ---------------------------------------------------------------------------
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,
            name TEXT,
            created_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS weights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            weight REAL,
            logged_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS meals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            meal_type TEXT,
            content TEXT,
            logged_at TEXT
        )"""
    )
    return conn


def register_user(chat_id: int, name: str):
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO users (chat_id, name, created_at) VALUES (?, ?, ?)",
        (chat_id, name, datetime.datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def log_weight(chat_id: int, weight: float):
    conn = get_conn()
    conn.execute(
        "INSERT INTO weights (chat_id, weight, logged_at) VALUES (?, ?, ?)",
        (chat_id, weight, datetime.datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def log_meal(chat_id: int, meal_type: str, content: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO meals (chat_id, meal_type, content, logged_at) VALUES (?, ?, ?, ?)",
        (chat_id, meal_type, content, datetime.datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_recent_weights(chat_id: int, days: int = 7):
    conn = get_conn()
    cur = conn.execute(
        "SELECT weight, logged_at FROM weights WHERE chat_id=? ORDER BY logged_at DESC LIMIT ?",
        (chat_id, days),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_recent_meals(chat_id: int, days: int = 7):
    conn = get_conn()
    cur = conn.execute(
        "SELECT meal_type, content, logged_at FROM meals WHERE chat_id=? ORDER BY logged_at DESC LIMIT 30",
        (chat_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# ANTRENMAN PROGRAMI (Kilo verme hedefi, haftada 3-4 gün, akşam)
# ---------------------------------------------------------------------------
WORKOUT_POOL = {
    "Pazartesi": {
        "title": "Full Body + Kardiyo",
        "items": [
            "5 dk ısınma (tempolu yürüyüş / ip atlama)",
            "Squat - 3 set x 15 tekrar",
            "Push-up (şınav) - 3 set x 10-12 tekrar",
            "Lunge (öne adım) - 3 set x 12 tekrar (her bacak)",
            "Plank - 3 set x 30-45 sn",
            "20 dk tempolu yürüyüş veya hafif koşu",
            "5 dk esneme",
        ],
    },
    "Çarşamba": {
        "title": "Üst Vücut + HIIT",
        "items": [
            "5 dk ısınma",
            "Push-up - 3 set x 10 tekrar",
            "Dumbbell/şişe ile shoulder press - 3 set x 12 tekrar",
            "Bent-over row (eğilerek çekiş) - 3 set x 12 tekrar",
            "HIIT: 30 sn yüksek tempo / 30 sn dinlenme x 8 round (jumping jack, burpee, mountain climber karışık)",
            "5 dk esneme",
        ],
    },
    "Cuma": {
        "title": "Alt Vücut + Kardiyo",
        "items": [
            "5 dk ısınma",
            "Squat - 4 set x 15 tekrar",
            "Glute bridge - 3 set x 15 tekrar",
            "Calf raise - 3 set x 20 tekrar",
            "Step-up (sandalye/merdiven basamağı) - 3 set x 12 tekrar (her bacak)",
            "25 dk orta tempolu kardiyo (yürüyüş, bisiklet, ip atlama)",
            "5 dk esneme",
        ],
    },
    "Pazar": {
        "title": "Aktif Toparlanma + Kardiyo",
        "items": [
            "30-40 dk tempolu yürüyüş veya hafif bisiklet",
            "10 dk genel esneme / mobilite çalışması",
            "İsteğe bağlı: 10 dk core çalışması (plank, bicycle crunch)",
        ],
    },
}


def build_week_program() -> str:
    lines = ["🗓️ *Bu Haftanın Programı* (Kilo Verme Odaklı)\n"]
    for day, plan in WORKOUT_POOL.items():
        lines.append(f"*{day} – {plan['title']}*")
        for item in plan["items"]:
            lines.append(f"  • {item}")
        lines.append("")
    lines.append("💡 Akşamları antrenmandan ~1.5 saat önce hafif beslen, sonrasında bol su iç.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# KOMUT HANDLER'LARI
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    name = update.effective_user.first_name or "Sporcu"
    register_user(chat_id, name)
    await update.message.reply_text(
        f"Merhaba {name}! 💪\n\n"
        "Ben senin kişisel fitness takip botunum. Kilo verme hedefine göre "
        "haftalık antrenman programı hazırlıyorum.\n\n"
        "Komutlar:\n"
        "/kilo 78.5  -> kiloyu kaydet\n"
        "/ogun kahvalti yumurta peynir  -> öğün kaydet\n"
        "/program  -> haftalık antrenman programı\n"
        "/ozet  -> son 7 günün özeti\n"
        "/yardim  -> tüm komutlar"
    )


async def yardim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 Komutlar:\n"
        "/kilo <sayı> -> örn: /kilo 78.5\n"
        "/ogun <öğün_adı> <içerik> -> örn: /ogun kahvalti 2 yumurta peynir\n"
        "/program -> haftalık antrenman programını gösterir\n"
        "/ozet -> son 7 günün kilo ve öğün özetini gösterir"
    )


async def kilo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Kullanım: /kilo 78.5")
        return
    try:
        weight = float(context.args[0].replace(",", "."))
    except ValueError:
        await update.message.reply_text("Lütfen geçerli bir sayı gir. Örn: /kilo 78.5")
        return

    log_weight(chat_id, weight)

    recent = get_recent_weights(chat_id, days=2)
    msg = f"✅ Kilo kaydedildi: {weight} kg"
    if len(recent) >= 2:
        diff = recent[0][0] - recent[1][0]
        if diff < 0:
            msg += f"\n📉 Önceki ölçüme göre {abs(diff):.1f} kg verdin, harika!"
        elif diff > 0:
            msg += f"\n📈 Önceki ölçüme göre {diff:.1f} kg artış var, takipte kal."
        else:
            msg += "\n➡️ Önceki ölçümle aynı."
    await update.message.reply_text(msg)


async def ogun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if len(context.args) < 2:
        await update.message.reply_text(
            "Kullanım: /ogun <öğün_adı> <içerik>\nÖrn: /ogun kahvalti 2 yumurta peynir"
        )
        return
    meal_type = context.args[0]
    content = " ".join(context.args[1:])
    log_meal(chat_id, meal_type, content)
    await update.message.reply_text(f"✅ '{meal_type}' kaydedildi: {content}")


async def program(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(build_week_program(), parse_mode="Markdown")


async def ozet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    weights = get_recent_weights(chat_id, days=7)
    meals = get_recent_meals(chat_id, days=7)

    lines = ["📊 *Son 7 Gün Özet*\n"]
    if weights:
        lines.append("⚖️ Kilo kayıtları:")
        for w, t in weights:
            tarih = t.split("T")[0]
            lines.append(f"  • {tarih}: {w} kg")
        if len(weights) >= 2:
            fark = weights[0][0] - weights[-1][0]
            lines.append(f"\nToplam değişim: {fark:+.1f} kg")
    else:
        lines.append("⚖️ Henüz kilo kaydı yok. /kilo 78.5 ile başlayabilirsin.")

    lines.append("")
    if meals:
        lines.append("🍽️ Son öğünler:")
        for mt, content, t in meals[:10]:
            tarih = t.split("T")[0]
            lines.append(f"  • {tarih} [{mt}]: {content}")
    else:
        lines.append("🍽️ Henüz öğün kaydı yok.")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ---------------------------------------------------------------------------
# ÇALIŞTIRMA
# ---------------------------------------------------------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("yardim", yardim))
    app.add_handler(CommandHandler("kilo", kilo))
    app.add_handler(CommandHandler("ogun", ogun))
    app.add_handler(CommandHandler("program", program))
    app.add_handler(CommandHandler("ozet", ozet))

    logger.info("Bot başlatılıyor...")
    app.run_polling()


if __name__ == "__main__":
    main()
