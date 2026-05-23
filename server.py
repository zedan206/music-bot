from flask import Flask
import threading
import os

app = Flask(__name__)

@app.route("/")
def index():
    return "🎵 بوت الموسيقى يعمل بنجاح!", 200

@app.route("/health")
def health():
    return {"status": "ok"}, 200

def run_flask():
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port)

def start_server():
    thread = threading.Thread(target=run_flask, daemon=True)
    thread.start()
