from server import start_server
import bot

if __name__ == "__main__":
    start_server()
    import os
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise ValueError("❌ لم يتم تعيين متغير البيئة DISCORD_TOKEN")
    bot.bot.run(token)
