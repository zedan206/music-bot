import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import asyncio
import os
import datetime

# ─── تحميل مكتبة Opus الصوتية ──────────────────────────────────────────────────
if not discord.opus.is_loaded():
    try:
        discord.opus.load_opus("libopus.so.0")
    except Exception:
        pass

# ─── إعدادات YT-DLP ────────────────────────────────────────────────────────────
YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    "skip_download": True,
    "ignoreerrors": True,
    "extractor_args": {"youtube": {"skip": ["dash", "hls"]}},
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

# ─── حالة كل سيرفر ─────────────────────────────────────────────────────────────
guild_states: dict[int, dict] = {}

def get_state(guild_id: int) -> dict:
    if guild_id not in guild_states:
        guild_states[guild_id] = {
            "queue": [],
            "current": None,
            "loop": False,
            "favorites": [],
            "voice_client": None,
            "start_time": None,
            "duration": 0,
            "message": None,
        }
    return guild_states[guild_id]

# ─── شريط التقدم ────────────────────────────────────────────────────────────────
def build_progress_bar(elapsed: int, total: int, length: int = 20) -> str:
    if total == 0:
        return "▬" * length
    filled = int((elapsed / total) * length)
    filled = min(filled, length - 1)
    bar = "▬" * filled + "●" + "▬" * (length - filled - 1)
    e = str(datetime.timedelta(seconds=elapsed))
    t = str(datetime.timedelta(seconds=total))
    return f"{bar}  {e}/{t}"

def format_time(seconds: int) -> str:
    return str(datetime.timedelta(seconds=seconds))

# ─── استخراج معلومات المقطع ─────────────────────────────────────────────────────
async def fetch_track(query: str) -> dict | None:
    loop = asyncio.get_event_loop()
    try:
        data = await loop.run_in_executor(
            None,
            lambda: ytdl.extract_info(
                query if query.startswith("http") else f"ytsearch:{query}",
                download=False,
            ),
        )
        if "entries" in data:
            data = data["entries"][0]
        return {
            "title": data.get("title", "غير معروف"),
            "url": data.get("url"),
            "webpage_url": data.get("webpage_url", ""),
            "thumbnail": data.get("thumbnail", ""),
            "duration": data.get("duration", 0),
        }
    except Exception:
        return None

# ─── بناء Embed الأغنية ─────────────────────────────────────────────────────────
def build_embed(track: dict, requester: discord.Member, state: dict) -> discord.Embed:
    elapsed = 0
    if state["start_time"]:
        elapsed = int((datetime.datetime.utcnow() - state["start_time"]).total_seconds())
        elapsed = min(elapsed, track["duration"])

    bar = build_progress_bar(elapsed, track["duration"])
    loop_text = "🔁 التكرار: مفعّل" if state["loop"] else "🔁 التكرار: معطّل"

    embed = discord.Embed(
        title="🎵 يتم الآن تشغيل",
        description=f"**[{track['title']}]({track['webpage_url']})**",
        color=discord.Color.blurple(),
    )
    embed.set_thumbnail(url=track["thumbnail"])
    embed.add_field(name="⏱️ التقدم", value=f"`{bar}`", inline=False)
    embed.add_field(name="المدة الكاملة", value=f"`{format_time(track['duration'])}`", inline=True)
    embed.add_field(name=loop_text, value="\u200b", inline=True)
    embed.set_footer(
        text=f"طلب بواسطة {requester.display_name}",
        icon_url=requester.display_avatar.url,
    )
    return embed

# ─── أزرار التحكم ───────────────────────────────────────────────────────────────
class MusicControls(discord.ui.View):
    def __init__(self, guild_id: int, requester: discord.Member):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.requester = requester

    def _state(self):
        return get_state(self.guild_id)

    @discord.ui.button(label="إيقاف / استئناف", style=discord.ButtonStyle.primary, emoji="⏸️")
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc: discord.VoiceClient = self._state()["voice_client"]
        if vc is None:
            await interaction.response.send_message("البوت غير متصل بقناة صوتية.", ephemeral=True)
            return
        if vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ تم استئناف التشغيل.", ephemeral=True)
        elif vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸️ تم إيقاف التشغيل مؤقتاً.", ephemeral=True)
        else:
            await interaction.response.send_message("لا يوجد تشغيل نشط حالياً.", ephemeral=True)

    @discord.ui.button(label="تخطي", style=discord.ButtonStyle.secondary, emoji="⏭️")
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc: discord.VoiceClient = self._state()["voice_client"]
        if vc and vc.is_playing():
            self._state()["loop"] = False
            vc.stop()
            await interaction.response.send_message("⏭️ تم تخطي الأغنية الحالية.", ephemeral=True)
        else:
            await interaction.response.send_message("لا يوجد ما يمكن تخطيه.", ephemeral=True)

    @discord.ui.button(label="تكرار", style=discord.ButtonStyle.secondary, emoji="🔁")
    async def toggle_loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = self._state()
        state["loop"] = not state["loop"]
        status = "مفعّل ✅" if state["loop"] else "معطّل ❌"
        await interaction.response.send_message(f"🔁 وضع التكرار: **{status}**", ephemeral=True)

    @discord.ui.button(label="إضافة للمفضلة", style=discord.ButtonStyle.success, emoji="⭐")
    async def add_favorite(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = self._state()
        track = state.get("current")
        if track is None:
            await interaction.response.send_message("لا توجد أغنية نشطة لإضافتها.", ephemeral=True)
            return
        favs = state["favorites"]
        if any(f["webpage_url"] == track["webpage_url"] for f in favs):
            await interaction.response.send_message("⭐ هذه الأغنية موجودة في المفضلة بالفعل.", ephemeral=True)
        else:
            favs.append(track)
            await interaction.response.send_message(f"⭐ تمت إضافة **{track['title']}** إلى المفضلة.", ephemeral=True)

    @discord.ui.button(label="قائمة المفضلة", style=discord.ButtonStyle.danger, emoji="📋")
    async def show_favorites(self, interaction: discord.Interaction, button: discord.ui.Button):
        favs = self._state()["favorites"]
        if not favs:
            await interaction.response.send_message("📋 قائمة المفضلة فارغة.", ephemeral=True)
            return
        lines = "\n".join(
            f"**{i+1}.** [{t['title']}]({t['webpage_url']})" for i, t in enumerate(favs)
        )
        embed = discord.Embed(title="⭐ قائمة المفضلة", description=lines, color=discord.Color.gold())
        await interaction.response.send_message(embed=embed, ephemeral=True)

# ─── دالة تشغيل الأغنية ─────────────────────────────────────────────────────────
async def play_track(guild: discord.Guild, channel: discord.TextChannel, track: dict, requester: discord.Member):
    state = get_state(guild.id)
    vc: discord.VoiceClient = state["voice_client"]

    if vc is None or not vc.is_connected():
        return

    state["current"] = track
    state["start_time"] = datetime.datetime.utcnow()
    state["duration"] = track["duration"]

    source = discord.FFmpegPCMAudio(track["url"], **FFMPEG_OPTIONS)

    def after_play(error):
        if error:
            print(f"[خطأ في التشغيل] {error}")
        asyncio.run_coroutine_threadsafe(
            on_track_end(guild, channel, requester), guild._state.loop
        )

    vc.play(source, after=after_play)

    embed = build_embed(track, requester, state)
    view = MusicControls(guild.id, requester)

    if state["message"]:
        try:
            await state["message"].delete()
        except Exception:
            pass

    msg = await channel.send(embed=embed, view=view)
    state["message"] = msg

    asyncio.create_task(update_progress_bar(guild, channel, track, requester))

async def update_progress_bar(guild: discord.Guild, channel: discord.TextChannel, track: dict, requester: discord.Member):
    state = get_state(guild.id)
    while True:
        await asyncio.sleep(15)
        vc = state.get("voice_client")
        if vc is None or not vc.is_playing():
            break
        if state.get("current") != track:
            break
        elapsed = int((datetime.datetime.utcnow() - state["start_time"]).total_seconds())
        if elapsed >= track["duration"]:
            break
        embed = build_embed(track, requester, state)
        if state["message"]:
            try:
                await state["message"].edit(embed=embed)
            except Exception:
                break

async def on_track_end(guild: discord.Guild, channel: discord.TextChannel, requester: discord.Member):
    state = get_state(guild.id)

    if state["loop"] and state["current"]:
        await play_track(guild, channel, state["current"], requester)
        return

    if state["queue"]:
        next_track = state["queue"].pop(0)
        await play_track(guild, channel, next_track, requester)
    else:
        state["current"] = None
        state["start_time"] = None
        embed = discord.Embed(
            title="🎵 انتهت قائمة التشغيل",
            description="لا توجد أغانٍ أخرى في قائمة الانتظار. البوت سيبقى في القناة الصوتية.",
            color=discord.Color.orange(),
        )
        await channel.send(embed=embed)

# ─── إعداد البوت ────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    await bot.tree.sync()
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.listening, name="أوامركم 🎵")
    )
    print(f"[جاهز] تم تسجيل الدخول باسم: {bot.user} | المعرّف: {bot.user.id}")

# ─── أمر /play ──────────────────────────────────────────────────────────────────
@bot.tree.command(name="play", description="ابحث عن أغنية أو شغّلها مباشرة من رابط")
@app_commands.describe(query="اسم الأغنية أو الرابط المباشر")
async def play(interaction: discord.Interaction, query: str):
    await interaction.response.defer(thinking=True)

    if not interaction.user.voice or not interaction.user.voice.channel:
        embed = discord.Embed(
            title="❌ خطأ",
            description="يجب أن تكون في قناة صوتية أولاً.",
            color=discord.Color.red(),
        )
        await interaction.followup.send(embed=embed)
        return

    voice_channel = interaction.user.voice.channel
    state = get_state(interaction.guild.id)

    if state["voice_client"] is None or not state["voice_client"].is_connected():
        vc = await voice_channel.connect(self_deaf=True)
        state["voice_client"] = vc
    elif state["voice_client"].channel != voice_channel:
        await state["voice_client"].move_to(voice_channel)

    loading_embed = discord.Embed(
        title="🔍 جارٍ البحث...",
        description=f"يتم البحث عن: **{query}**",
        color=discord.Color.blurple(),
    )
    await interaction.followup.send(embed=loading_embed)

    track = await fetch_track(query)

    if track is None:
        embed = discord.Embed(
            title="❌ لم يتم العثور على نتائج",
            description=f"تعذّر العثور على أي نتيجة لـ: **{query}**",
            color=discord.Color.red(),
        )
        await interaction.channel.send(embed=embed)
        return

    vc: discord.VoiceClient = state["voice_client"]

    if vc.is_playing() or vc.is_paused():
        state["queue"].append(track)
        embed = discord.Embed(
            title="➕ تمت الإضافة إلى قائمة الانتظار",
            description=f"**[{track['title']}]({track['webpage_url']})**\nالموضع في القائمة: **{len(state['queue'])}**",
            color=discord.Color.green(),
        )
        embed.set_thumbnail(url=track["thumbnail"])
        embed.set_footer(
            text=f"طلب بواسطة {interaction.user.display_name}",
            icon_url=interaction.user.display_avatar.url,
        )
        await interaction.channel.send(embed=embed)
    else:
        await play_track(interaction.guild, interaction.channel, track, interaction.user)

# ─── أمر /stop ──────────────────────────────────────────────────────────────────
@bot.tree.command(name="stop", description="أوقف التشغيل وافصل البوت عن القناة الصوتية")
async def stop(interaction: discord.Interaction):
    state = get_state(interaction.guild.id)
    vc: discord.VoiceClient = state["voice_client"]

    if vc is None or not vc.is_connected():
        await interaction.response.send_message(
            embed=discord.Embed(
                title="❌ البوت غير متصل",
                description="البوت ليس في أي قناة صوتية حالياً.",
                color=discord.Color.red(),
            )
        )
        return

    state["queue"].clear()
    state["current"] = None
    state["loop"] = False

    if vc.is_playing() or vc.is_paused():
        vc.stop()

    await vc.disconnect()
    state["voice_client"] = None

    await interaction.response.send_message(
        embed=discord.Embed(
            title="⏹️ تم الإيقاف",
            description="تم إيقاف التشغيل ومسح قائمة الانتظار والخروج من القناة الصوتية.",
            color=discord.Color.red(),
        )
    )

# ─── تشغيل البوت ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise ValueError("❌ لم يتم تعيين متغير البيئة DISCORD_TOKEN")
    bot.run(token)
