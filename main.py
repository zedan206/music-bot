import threading
import os
from flask import Flask

# ─── سيرفر Flask للبقاء نشطاً ──────────────────────────────────────────────────
app = Flask(__name__)

@app.route("/")
def index():
    return "🎵 بوت الموسيقى يعمل بنجاح!", 200

@app.route("/health")
def health():
    return {"status": "ok"}, 200

def run_flask():
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port, use_reloader=False)

# ─── تشغيل Flask في الخلفية ────────────────────────────────────────────────────
flask_thread = threading.Thread(target=run_flask, daemon=True)
flask_thread.start()

# ─── طباعة رابط الويب للاستخدام في UptimeRobot ─────────────────────────────────
railway_url = os.getenv("RAILWAY_STATIC_URL") or os.getenv("RAILWAY_PUBLIC_DOMAIN")
replit_url   = os.getenv("REPLIT_DOMAINS", "")

if railway_url:
    web_url = f"https://{railway_url}"
elif replit_url:
    web_url = f"https://{replit_url.split(',')[0]}"
else:
    web_url = f"http://localhost:{os.getenv('PORT', 8000)}"

print("=" * 60)
print(f"  🌐 رابط UptimeRobot / Freshping: {web_url}")
print(f"     → أضفه في موقع المراقبة كـ HTTP Monitor")
print("=" * 60)

# ─── تشغيل البوت ────────────────────────────────────────────────────────────────
import bot

token = os.getenv("DISCORD_TOKEN")
if not token:
    raise ValueError("❌ لم يتم تعيين متغير البيئة DISCORD_TOKEN")

bot.bot.run(token)
