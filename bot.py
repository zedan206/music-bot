import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import asyncio
import os
import datetime

# ─── تحميل مكتبة Opus الصوتية ──────────────────────────────────────────────────
if not discord.opus.is_loaded():
    for _lib in ("libopus.so.0", "libopus.so", "opus"):
        try:
            discord.opus.load_opus(_lib)
            break
        except Exception:
            continue

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
    "extractor_args": {
        "youtube": {
            "player_client": ["ios", "android_music"],
        }
    },
    "socket_timeout": 30,
}

FFMPEG_OPTIONS = {
    "before_options": (
        "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
    ),
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
            "pause_time": None,
            "paused_elapsed": 0,
            "duration": 0,
            "message": None,
            "requester": None,
        }
    return guild_states[guild_id]

# ─── حساب الوقت المنقضي بدقة (يراعي الإيقاف المؤقت) ───────────────────────────
def get_elapsed(state: dict) -> int:
    if state["start_time"] is None:
        return 0
    if state["pause_time"] is not None:
        return state["paused_elapsed"]
    elapsed = state["paused_elapsed"] + int(
        (datetime.datetime.utcnow() - state["start_time"]).total_seconds()
    )
    return min(elapsed, state["duration"])

# ─── شريط التقدم ────────────────────────────────────────────────────────────────
def build_progress_bar(elapsed: int, total: int, length: int = 20) -> str:
    if total == 0:
        return "▬" * length + "  ⏳"
    pct = elapsed / total
    filled = min(int(pct * length), length - 1)
    bar = "▬" * filled + "●" + "▬" * (length - filled - 1)
    def fmt(s: int) -> str:
        m, sec = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"
    return f"{bar}  {fmt(elapsed)} / {fmt(total)}"

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
        if data is None:
            return None
        if "entries" in data:
            entries = [e for e in data["entries"] if e]
            if not entries:
                return None
            data = entries[0]
        return {
            "title": data.get("title", "غير معروف"),
            "url": data.get("url"),
            "webpage_url": data.get("webpage_url", ""),
            "thumbnail": data.get("thumbnail", ""),
            "duration": data.get("duration") or 0,
        }
    except Exception:
        return None

# ─── بناء Embed الأغنية ─────────────────────────────────────────────────────────
def build_embed(track: dict, requester: discord.Member, state: dict) -> discord.Embed:
    elapsed = get_elapsed(state)
    bar = build_progress_bar(elapsed, track["duration"])
    loop_icon = "🔁 **مفعّل**" if state["loop"] else "🔁 معطّل"
    paused = state["pause_time"] is not None
    status = "⏸️ موقوف مؤقتاً" if paused else "▶️ قيد التشغيل"

    embed = discord.Embed(
        title="🎵 يتم الآن تشغيل",
        description=f"**[{track['title']}]({track['webpage_url']})**",
        color=discord.Color.from_rgb(88, 101, 242),
    )
    if track["thumbnail"]:
        embed.set_thumbnail(url=track["thumbnail"])
    embed.add_field(name="⏱️ التقدم", value=f"`{bar}`", inline=False)
    embed.add_field(name="الحالة", value=status, inline=True)
    embed.add_field(name="التكرار", value=loop_icon, inline=True)
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

    def _state(self) -> dict:
        return get_state(self.guild_id)

    async def _refresh_embed(self, interaction: discord.Interaction):
        state = self._state()
        track = state.get("current")
        if track and state.get("message"):
            try:
                embed = build_embed(track, self.requester, state)
                await state["message"].edit(embed=embed)
            except Exception:
                pass

    @discord.ui.button(label="إيقاف / استئناف", style=discord.ButtonStyle.primary, emoji="⏸️", row=0)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = self._state()
        vc: discord.VoiceClient | None = state["voice_client"]
        if vc is None or not vc.is_connected():
            await interaction.response.send_message("البوت غير متصل بقناة صوتية.", ephemeral=True)
            return
        if vc.is_paused():
            vc.resume()
            paused_duration = int(
                (datetime.datetime.utcnow() - state["pause_time"]).total_seconds()
            ) if state["pause_time"] else 0
            state["start_time"] = datetime.datetime.utcnow() - datetime.timedelta(
                seconds=state["paused_elapsed"]
            )
            state["pause_time"] = None
            await interaction.response.send_message("▶️ تم استئناف التشغيل.", ephemeral=True)
        elif vc.is_playing():
            vc.pause()
            state["paused_elapsed"] = get_elapsed(state)
            state["pause_time"] = datetime.datetime.utcnow()
            await interaction.response.send_message("⏸️ تم إيقاف التشغيل مؤقتاً.", ephemeral=True)
        else:
            await interaction.response.send_message("لا يوجد تشغيل نشط حالياً.", ephemeral=True)
            return
        await self._refresh_embed(interaction)

    @discord.ui.button(label="تخطي", style=discord.ButtonStyle.secondary, emoji="⏭️", row=0)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = self._state()
        vc: discord.VoiceClient | None = state["voice_client"]
        if vc and (vc.is_playing() or vc.is_paused()):
            state["loop"] = False
            state["pause_time"] = None
            vc.stop()
            await interaction.response.send_message("⏭️ تم تخطي الأغنية الحالية.", ephemeral=True)
        else:
            await interaction.response.send_message("لا يوجد ما يمكن تخطيه.", ephemeral=True)

    @discord.ui.button(label="تكرار", style=discord.ButtonStyle.secondary, emoji="🔁", row=0)
    async def toggle_loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = self._state()
        state["loop"] = not state["loop"]
        status = "مفعّل ✅" if state["loop"] else "معطّل ❌"
        await interaction.response.send_message(f"🔁 وضع التكرار: **{status}**", ephemeral=True)
        await self._refresh_embed(interaction)

    @discord.ui.button(label="إضافة للمفضلة", style=discord.ButtonStyle.success, emoji="⭐", row=1)
    async def add_favorite(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = self._state()
        track = state.get("current")
        if not track:
            await interaction.response.send_message("لا توجد أغنية نشطة لإضافتها.", ephemeral=True)
            return
        favs = state["favorites"]
        if any(f["webpage_url"] == track["webpage_url"] for f in favs):
            await interaction.response.send_message("⭐ هذه الأغنية موجودة في المفضلة بالفعل.", ephemeral=True)
        else:
            favs.append(track)
            await interaction.response.send_message(
                f"⭐ تمت إضافة **{track['title']}** إلى المفضلة.", ephemeral=True
            )

    @discord.ui.button(label="قائمة المفضلة", style=discord.ButtonStyle.danger, emoji="📋", row=1)
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

# ─── تحديث شريط التقدم كل 20 ثانية ─────────────────────────────────────────────
async def update_progress_bar(guild_id: int, track: dict):
    state = get_state(guild_id)
    while True:
        await asyncio.sleep(20)
        if state.get("current") is not track:
            break
        vc = state.get("voice_client")
        if vc is None or (not vc.is_playing() and not vc.is_paused()):
            break
        requester = state.get("requester")
        if not requester or not state.get("message"):
            break
        elapsed = get_elapsed(state)
        if elapsed >= track["duration"] > 0:
            break
        try:
            embed = build_embed(track, requester, state)
            await state["message"].edit(embed=embed)
        except Exception:
            break

# ─── تشغيل أغنية ────────────────────────────────────────────────────────────────
async def play_track(
    guild: discord.Guild,
    channel: discord.abc.Messageable,
    track: dict,
    requester: discord.Member,
):
    state = get_state(guild.id)
    vc: discord.VoiceClient | None = state["voice_client"]
    if vc is None or not vc.is_connected():
        return

    state["current"] = track
    state["requester"] = requester
    state["start_time"] = datetime.datetime.utcnow()
    state["pause_time"] = None
    state["paused_elapsed"] = 0
    state["duration"] = track["duration"]

    source = discord.FFmpegPCMAudio(track["url"], **FFMPEG_OPTIONS)

    def after_play(error):
        if error:
            print(f"[خطأ في التشغيل] {error}")
        asyncio.run_coroutine_threadsafe(
            on_track_end(guild, channel, requester),
            bot.loop,
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

    asyncio.create_task(update_progress_bar(guild.id, track))

# ─── نهاية الأغنية ──────────────────────────────────────────────────────────────
async def on_track_end(
    guild: discord.Guild,
    channel: discord.abc.Messageable,
    requester: discord.Member,
):
    state = get_state(guild.id)

    if state["loop"] and state["current"]:
        track = state["current"]
        fresh = await fetch_track(track["webpage_url"] or track["title"])
        await play_track(guild, channel, fresh or track, requester)
        return

    if state["queue"]:
        next_track = state["queue"].pop(0)
        next_requester = state.get("requester") or requester
        await play_track(guild, channel, next_track, next_requester)
    else:
        state["current"] = None
        state["start_time"] = None
        embed = discord.Embed(
            title="🎵 انتهت قائمة التشغيل",
            description=(
                "لا توجد أغانٍ أخرى في قائمة الانتظار.\n"
                "البوت سيبقى في القناة الصوتية وينتظر طلباتكم."
            ),
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
    print("=" * 60)
    print(f"  ✅ البوت جاهز: {bot.user} | المعرّف: {bot.user.id}")
    # رابط UptimeRobot — استخدمه في موقع uptimerobot.com
    domains = os.getenv("REPLIT_DOMAINS", "")
    if domains:
        url = f"https://{domains.split(',')[0]}"
        print(f"  🌐 رابط UptimeRobot: {url}")
        print(f"     → أضفه في uptimerobot.com كـ HTTP Monitor")
    else:
        port = os.getenv("PORT", "8000")
        print(f"  🌐 السيرفر يعمل على المنفذ: {port}")
    print("=" * 60)

# ─── أمر /play ──────────────────────────────────────────────────────────────────
@bot.tree.command(name="play", description="ابحث عن أغنية أو شغّلها مباشرة من رابط")
@app_commands.describe(query="اسم الأغنية أو الرابط المباشر")
async def play(interaction: discord.Interaction, query: str):
    await interaction.response.defer(thinking=True)

    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.followup.send(
            embed=discord.Embed(
                title="❌ خطأ",
                description="يجب أن تكون في قناة صوتية أولاً.",
                color=discord.Color.red(),
            )
        )
        return

    voice_channel = interaction.user.voice.channel
    state = get_state(interaction.guild.id)

    if state["voice_client"] is None or not state["voice_client"].is_connected():
        vc = await voice_channel.connect(self_deaf=True)
        state["voice_client"] = vc
    elif state["voice_client"].channel != voice_channel:
        await state["voice_client"].move_to(voice_channel)

    await interaction.followup.send(
        embed=discord.Embed(
            title="🔍 جارٍ البحث...",
            description=f"يتم البحث عن: **{query}**",
            color=discord.Color.blurple(),
        )
    )

    track = await fetch_track(query)

    if track is None or not track.get("url"):
        await interaction.channel.send(
            embed=discord.Embed(
                title="❌ لم يتم العثور على نتائج",
                description=f"تعذّر العثور على أي نتيجة لـ: **{query}**",
                color=discord.Color.red(),
            )
        )
        return

    vc: discord.VoiceClient = state["voice_client"]

    if vc.is_playing() or vc.is_paused():
        state["queue"].append(track)
        embed = discord.Embed(
            title="➕ تمت الإضافة إلى قائمة الانتظار",
            description=(
                f"**[{track['title']}]({track['webpage_url']})**\n"
                f"الموضع في القائمة: **{len(state['queue'])}**"
            ),
            color=discord.Color.green(),
        )
        if track["thumbnail"]:
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
    vc: discord.VoiceClient | None = state["voice_client"]

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
    state["pause_time"] = None
    state["paused_elapsed"] = 0

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
