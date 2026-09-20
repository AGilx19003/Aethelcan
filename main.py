import os
import sys
import json
import logging
import asyncio
import random
import time
from datetime import timedelta
import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import Modal, TextInput, View, Button
from dotenv import load_dotenv
from huggingface_hub import InferenceClient
import yt_dlp

# ==========================================
# 1. ORTAM DEĞİŞKENLERİ & LOGLAMA & VERİ SAKLAMA
# ==========================================
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

logger = logging.getLogger("discord_bot")
logger.setLevel(logging.INFO)

log_formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

file_handler = logging.FileHandler(filename="bot.log", encoding="utf-8", mode="a")
file_handler.setFormatter(log_formatter)
logger.addHandler(file_handler)

stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(log_formatter)
logger.addHandler(stream_handler)

# Sabitler & ID'ler
SPECIAL_USER_ID = 1095004764368015451
TARGET_GUILD_ID = 1544776459908812882
AI_CHANNEL_ID = 1545830545668313169
XP_LOG_CHANNEL_ID = 1545848935371898921
TAG_ROLE_ID = 1544776460349214747

# Yetkili Alım Sistemi ID'leri
AUTHORIZED_ROLE_ID = 1544776460349214747  # Başvuru gelince etiketlenen rol ID
LOG_CHANNEL_ID = 1547666391388131338       # Başvuruların düşeceği kanal ID
MOD_ROLE_ID = 1544776460349214743          # Moderatör Rol ID
KAYIT_ROLE_ID = 1544776460332695641        # Kayıt Sorumlusu Rol ID
SORUN_ROLE_ID = 1544776460349214741        # Sorun Çözücü Rol ID

START_TIME = time.time()

TICKET_STAFF_ROLES = [
    1544776460349214747,
    1544776460349214743,
    1544776460349214744,
    1544776460349214741,
    1544776460349214742
]

DUYURU_ROLES = [1544776460349214747, 1544776460349214744]
MOD_ROLES = [1544776460349214743, 1544776460349214744, 1544776460349214747]

RANDOM_IMAGES = [
    "https://i.pinimg.com/originals/40/3d/e8/403de8860f806deec8e807497533af34.jpg",
    "https://i.pinimg.com/736x/c9/23/a8/c923a805362f3913682b3c124895ddc1.jpg",
    "https://tse4.mm.bing.net/th/id/OIP.t7PH0iq42GTGmzWteeSpwQHaIw?r=0&w=609&h=720&rs=1&pid=ImgDetMain&o=7&rm=3",
    "https://i.pinimg.com/474x/bd/ba/18/bdba182ef599d9bd687f4749ae602bb8.jpg",
    "https://i.ytimg.com/vi/oAsDyvS0M40/hqdefault.jpg",
    "https://tse1.explicit.bing.net/th/id/OIP._fEbt4On3IT_EGcXHv9kcQHaLZ?r=0&rs=1&pid=ImgDetMain&o=7&rm=3"
]

# JSON Veri Yükleme ve Kaydetme
DATA_FILE = "data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {int(k): v for k, v in data.get("user_xp", {}).items()}
        except Exception as e:
            logger.error(f"Veri yükleme hatası: {e}")
            return {}
    return {}

def save_data():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({"user_xp": user_xp}, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Veri kaydetme hatası: {e}")

# Veri Depoları
user_xp = load_data()
voice_times = {}
voice_weekly = {}
voice_active = {}

def add_xp(user_id: int, amount: int):
    old_xp = user_xp.get(user_id, 0)
    new_xp = old_xp + amount
    user_xp[user_id] = new_xp
    save_data()
    return old_xp, new_xp

def check_roles(ctx_or_interaction, allowed_roles: list) -> bool:
    user = getattr(ctx_or_interaction, "user", getattr(ctx_or_interaction, "author", None))
    guild = getattr(ctx_or_interaction, "guild", None)
    
    if not user:
        return False
        
    if user.id == SPECIAL_USER_ID:
        return True
        
    if guild and guild.owner_id == user.id:
        return True

    if hasattr(user, "guild_permissions") and user.guild_permissions.administrator:
        return True

    if hasattr(user, "roles"):
        user_role_ids = [role.id for role in user.roles]
        return any(role_id in user_role_ids for role_id in allowed_roles)

    return False

# ==========================================
# 2. YETKİLİ BAŞVURU SİSTEMİ (MODAL & VIEWS)
# ==========================================
class ApplicationModal(Modal, title="Yetkili Alım Formu"):
    name_age = TextInput(
        label="İsim ve Yaşınız",
        placeholder="Örn: Ahmet, 18",
        required=True
    )
    discord_username = TextInput(
        label="Discord Kullanıcı Adınız",
        placeholder="Örn: Narrator",
        required=True
    )
    time_range = TextInput(
        label="Saat Aralığınız",
        placeholder="Örn: Sabah 10 - Gece 05:00",
        required=True
    )
    hours_active = TextInput(
        label="Kaç Saat Sunucuyla İlgilenirsiniz?",
        placeholder="Örn: Her saniye / 8 saat",
        required=True
    )
    chat_vc_activity = TextInput(
        label="Chat, VC ve Etkinlikte Aktif Olur musunuz?",
        placeholder="Örn: Olurum / Evet",
        style=discord.TextStyle.paragraph,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID) or interaction.client.get_channel(LOG_CHANNEL_ID)
        
        if not log_channel:
            try:
                log_channel = await interaction.client.fetch_channel(LOG_CHANNEL_ID)
            except Exception as e:
                await interaction.response.send_message(f"Log kanalı bulunamadı! Hata: {e}", ephemeral=True)
                return

        embed = discord.Embed(
            title="📥 Yeni Yetkili Başvurusu",
            color=discord.Color.blue()
        )
        embed.add_field(name="İsim ve Yaş", value=self.name_age.value, inline=False)
        embed.add_field(name="Discord Kullanıcı Adı", value=self.discord_username.value, inline=False)
        embed.add_field(name="Saat Aralığı", value=self.time_range.value, inline=False)
        embed.add_field(name="İlgilenme Süresi", value=self.hours_active.value, inline=False)
        embed.add_field(name="Chat / VC / Etkinlik Aktifliği", value=self.chat_vc_activity.value, inline=False)
        embed.add_field(name="Başvuran Kullanıcı", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
        embed.set_footer(text=f"Başvuran ID: {interaction.user.id}")

        try:
            await log_channel.send(
                content=f"<@&{AUTHORIZED_ROLE_ID}> Yeni bir yetkili başvurusu var!",
                embed=embed, 
                view=ApplicationActionView(applicant_id=interaction.user.id)
            )
            await interaction.response.send_message("Başvurunuz başarıyla alındı! Sonuç tarafınıza DM üzerinden bildirilecektir.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("Botun log kanalına mesaj atma veya Embed gönderme yetkisi yok!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Hata oluştu: {e}", ephemeral=True)

class ApplicationActionView(View):
    def __init__(self, applicant_id: int):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id

    async def check_permission(self, interaction: discord.Interaction) -> bool:
        if not any(role.id == AUTHORIZED_ROLE_ID for role in interaction.user.roles):
            await interaction.response.send_message("Bu işlemi yapmak için yetkiniz yok!", ephemeral=True)
            return False
        return True

    async def handle_role_assignment(self, interaction: discord.Interaction, role_id: int, role_name: str):
        if not await self.check_permission(interaction):
            return

        guild = interaction.guild
        role = guild.get_role(role_id)
        
        member = guild.get_member(self.applicant_id)
        if not member:
            try:
                member = await guild.fetch_member(self.applicant_id)
            except Exception:
                member = None

        if not role:
            await interaction.response.send_message(f"Hata: `{role_id}` ID'li rol bu sunucuda bulunamadı!", ephemeral=True)
            return

        if not member:
            await interaction.response.send_message("Hata: Başvuran kullanıcı sunucuda bulunamadı!", ephemeral=True)
            return

        try:
            await member.add_roles(role)
            try:
                await member.send(f"Tebrikler! **{guild.name}** sunucusundaki yetkili başvurunuz onaylandı ve **{role_name}** rolünüz verildi.")
            except discord.Forbidden:
                pass
            await interaction.response.send_message(f"{member.mention} kullanıcısına **{role_name}** rolü başarıyla verildi.", ephemeral=False)

            for item in self.children:
                item.disabled = True
            await interaction.message.edit(view=self)

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ **Rol Verilemedi!** Botun kendi rolü, vermek istediğiniz rolden daha aşağıda veya botun 'Rolleri Yönet' yetkisi yok. Lütfen botun rolünü sunucu ayarlarında üst sıralara taşıyın.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"Hata oluştu: {e}", ephemeral=True)

    @discord.ui.button(label="Moderatör olarak al", style=discord.ButtonStyle.success)
    async def approve_mod(self, interaction: discord.Interaction, button: Button):
        await self.handle_role_assignment(interaction, MOD_ROLE_ID, "Moderatör")

    @discord.ui.button(label="Sorun Çözücü olarak al", style=discord.ButtonStyle.primary)
    async def approve_sorun(self, interaction: discord.Interaction, button: Button):
        await self.handle_role_assignment(interaction, SORUN_ROLE_ID, "Sorun Çözücü")

    @discord.ui.button(label="Kayıt sorumlusu olarak al", style=discord.ButtonStyle.secondary)
    async def approve_kayit(self, interaction: discord.Interaction, button: Button):
        await self.handle_role_assignment(interaction, KAYIT_ROLE_ID, "Kayıt Sorumlusu")

    @discord.ui.button(label="Reddet", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: Button):
        if not await self.check_permission(interaction):
            return

        member = interaction.guild.get_member(self.applicant_id)
        if member:
            try:
                await member.send(f"Merhaba, **{interaction.guild.name}** sunucusundaki yetkili başvurunuz reddedilmiştir.")
            except discord.Forbidden:
                pass
            await interaction.response.send_message(f"{member.mention} kullanıcısının başvurusu reddedildi ve DM atıldı.", ephemeral=False)

        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

class ApplicationLaunchView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📝 Başvuru Yap", style=discord.ButtonStyle.primary, custom_id="apply_button")
    async def open_modal(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(ApplicationModal())

# ==========================================
# 3. OYUN BİLEŞENLERİ (VAMPİR KÖYLÜ & KÖSTEBEK KİM)
# ==========================================
class VampirKoyluLobbyView(discord.ui.View):
    def __init__(self, host: discord.Member):
        super().__init__(timeout=180)
        self.host = host
        self.players = set()

    @discord.ui.button(label="Katıl / Ayrıl", style=discord.ButtonStyle.success, emoji="🎮")
    async def join_game(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user in self.players:
            self.players.remove(interaction.user)
            await interaction.response.send_message("Oyundan ayrıldın.", ephemeral=True)
        else:
            self.players.add(interaction.user)
            await interaction.response.send_message("Oyun lobisine katıldın!", ephemeral=True)

    @discord.ui.button(label="Oyunu Başlat", style=discord.ButtonStyle.primary, emoji="🚀")
    async def start_game(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.host and interaction.user.id != SPECIAL_USER_ID:
            return await interaction.response.send_message("Oyunu sadece başlatan kişi başlatabilir!", ephemeral=True)

        if len(self.players) < 3:
            return await interaction.response.send_message("Vampir-Köylü oynamak için en az 3 kişi olmalısınız!", ephemeral=True)

        player_list = list(self.players)
        random.shuffle(player_list)

        vampire = player_list.pop()
        doctor = player_list.pop() if len(player_list) > 2 else None
        villagers = player_list

        try:
            await vampire.send("🩸 **Rolün: VAMPİR!** Her gece birini avlamalısın. Kimseye belli etme!")
            if doctor:
                await doctor.send("💉 **Rolün: DOKTOR!** Her gece birini koruyabilirsin.")
            for v in villagers:
                await v.send("🧑‍🌾 **Rolün: KÖYLÜ!** Hayatta kal ve vampirin kim olduğunu bul!")

            await interaction.response.send_message("🎭 **Roller tüm oyuncuların DM kutularına gizlice gönderildi!** Oyun başladı!")
            self.stop()
        except discord.Forbidden:
            await interaction.response.send_message("❌ Bazı oyuncuların DM kutusu kapalı olduğu için roller gönderilemedi!", ephemeral=True)

class KostebekLobbyView(discord.ui.View):
    def __init__(self, host: discord.Member):
        super().__init__(timeout=180)
        self.host = host
        self.players = set()
        self.words = ["Elma", "Futbol", "Sinema", "Televizyon", "Bilgisayar", "Güneş", "Araba", "Klavye", "Kulaklık", "Yazılım", "Pizza"]

    @discord.ui.button(label="Katıl / Ayrıl", style=discord.ButtonStyle.success, emoji="🕵️")
    async def join_game(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user in self.players:
            self.players.remove(interaction.user)
            await interaction.response.send_message("Oyundan ayrıldın.", ephemeral=True)
        else:
            self.players.add(interaction.user)
            await interaction.response.send_message("Köstebek Kim lobisine katıldın!", ephemeral=True)

    @discord.ui.button(label="Oyunu Başlat", style=discord.ButtonStyle.primary, emoji="🚀")
    async def start_game(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.host and interaction.user.id != SPECIAL_USER_ID:
            return await interaction.response.send_message("Oyunu sadece başlatan kişi başlatabilir!", ephemeral=True)

        if len(self.players) < 3:
            return await interaction.response.send_message("Köstebek Kim oynamak için en az 3 kişi olmalısınız!", ephemeral=True)

        player_list = list(self.players)
        secret_word = random.choice(self.words)
        mole = random.choice(player_list)

        try:
            for p in player_list:
                if p == mole:
                    await p.send("🕵️ **Sen KÖSTEBEKSİN!** Gizli kelimeyi bilmiyorsun. Çaktırmadan muhabbete uyum sağla!")
                else:
                    await p.send(f"🔑 **Gizli Kelimen:** `{secret_word}` — Aramızdaki köstebeği bulun!")

            await interaction.response.send_message("🕵️‍♂️ **Gizli kelimeler DM üzerinden dağıtıldı!** Köstebek kim? Sırayla kelimeyi anlatmaya başlayın!")
            self.stop()
        except discord.Forbidden:
            await interaction.response.send_message("❌ Bazı oyuncuların DM kutusu kapalı olduğu için mesaj gönderilemedi!", ephemeral=True)

# ==========================================
# 4. TİCKET & ÇEKİLİŞ SİSTEMİ
# ==========================================
class TicketUserAddSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(placeholder="Bilete eklenecek üyeyi seçin...", min_values=1, max_values=1, custom_id="ticket_user_select")

    async def callback(self, interaction: discord.Interaction):
        selected_user = self.values[0]
        await interaction.channel.set_permissions(selected_user, read_messages=True, send_messages=True)
        await interaction.response.send_message(f"✅ {selected_user.mention} bilete başarıyla eklendi.", ephemeral=False)

class TicketControlView(discord.ui.View):
    def __init__(self, creator_id: int):
        super().__init__(timeout=None)
        self.creator_id = creator_id
        self.add_item(TicketUserAddSelect())

    @discord.ui.button(label="Bileti Kapat", style=discord.ButtonStyle.red, custom_id="ticket_close", emoji="🔒")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_staff = any(role.id in TICKET_STAFF_ROLES for role in interaction.user.roles)
        is_admin = interaction.user.guild_permissions.administrator
        is_special = interaction.user.id in [SPECIAL_USER_ID, interaction.guild.owner_id]

        if not (is_staff or is_admin or is_special) or interaction.user.id == self.creator_id:
            return await interaction.response.send_message("❌ Bileti yalnızca ticket yetkilileri silebilir!", ephemeral=True)

        await interaction.response.send_message("⚙️ Bilet 5 saniye içinde kapatılıyor...", ephemeral=False)
        await asyncio.sleep(5)
        await interaction.channel.delete()

class TicketCategorySelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Sunucu İçi Destek", value="destek", description="Genel destek talepleri için", emoji="🛠️"),
            discord.SelectOption(label="Şikayet", value="sikayet", description="Kullanıcı veya durum şikayetleri için", emoji="⚠️"),
            discord.SelectOption(label="Owner'a Ulaşma", value="owner", description="Doğrudan üst yönetime ulaşmak için", emoji="👑")
        ]
        super().__init__(placeholder="Kategori seçiniz...", min_values=1, max_values=1, custom_id="ticket_category_select", options=options)

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        user = interaction.user
        category_choice = self.values[0]
        channel_name = f"bilet-{user.name}".lower()

        existing_channel = discord.utils.get(guild.channels, name=channel_name)
        if existing_channel:
            return await interaction.response.send_message(f"Zaten açık bir biletiniz var: {existing_channel.mention}", ephemeral=True)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        ping_roles = []
        if category_choice == "owner":
            role = guild.get_role(1544776460349214747)
            if role:
                ping_roles.append(role)
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        elif category_choice in ["destek", "sikayet"]:
            for rid in [1544776460349214747, 1544776460349214743]:
                role = guild.get_role(rid)
                if role:
                    ping_roles.append(role)
                    overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        ticket_channel = await guild.create_text_channel(name=channel_name, overwrites=overwrites)
        await interaction.response.send_message(f"✅ Biletiniz oluşturuldu: {ticket_channel.mention}", ephemeral=True)

        pings_text = " ".join([r.mention for r in ping_roles])
        welcome_embed = discord.Embed(
            title="Destek Talebi",
            description=f"Merhaba {user.mention}, talebiniz alındı. En kısa sürede ilgilenecektir.\n\n"
                        f"**Kategori:** {self.values[0].capitalize()}\n"
                        f"**Üye Ekleme:** Aşağıdaki listeden üye seçerek bilete ekleyebilirsiniz.",
            color=discord.Color.blue()
        )
        await ticket_channel.send(content=f"{user.mention} {pings_text}", embed=welcome_embed, view=TicketControlView(creator_id=user.id))

class TicketLaunchView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketCategorySelect())

class GiveawayView(discord.ui.View):
    def __init__(self, host_id: int, winner_count: int, prize: str, end_time: float):
        super().__init__(timeout=None)
        self.host_id = host_id
        self.winner_count = winner_count
        self.prize = prize
        self.end_time = end_time
        self.participants = set()
        self.ended = False

    @discord.ui.button(emoji="🎉", style=discord.ButtonStyle.primary, custom_id="giveaway_join")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.ended:
            return await interaction.response.send_message("Bu çekiliş sona erdi.", ephemeral=True)
        if interaction.user.id in self.participants:
            return await interaction.response.send_message("Çekilişe zaten katıldın.", ephemeral=True)
        
        self.participants.add(interaction.user.id)
        await interaction.response.send_message("Çekilişe başarıyla katıldın!", ephemeral=True)

    @discord.ui.button(label="Erken Bitir", style=discord.ButtonStyle.danger, custom_id="giveaway_end_early")
    async def end_early(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.host_id and interaction.user.id != SPECIAL_USER_ID:
            return await interaction.response.send_message("Bu işlemi sadece çekilişi başlatan kişi yapabilir!", ephemeral=True)
        
        await interaction.response.send_message("Çekiliş erken bitiriliyor...", ephemeral=True)
        await finish_giveaway(interaction.channel, self)

async def finish_giveaway(channel, g_view: GiveawayView):
    if g_view.ended:
        return
    g_view.ended = True

    if not g_view.participants:
        await channel.send(f"🎉 **{g_view.prize}** çekilişine yeterli katılım olmadığı için kazanan belirlenemedi.")
        return

    winners_count = min(len(g_view.participants), g_view.winner_count)
    winner_ids = random.sample(list(g_view.participants), winners_count)
    winners_mentions = [f"<@{wid}>" for wid in winner_ids]

    await channel.send(f"🎉 **ÇEKİLİŞ SONUÇLANDI!**\nÖdül: **{g_view.prize}**\nKazananlar: {', '.join(winners_mentions)}")

# ==========================================
# 5. BOT SINIFI & ARKA PLAN GÖREVLERİ
# ==========================================
class AdvancedBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.voice_states = True
        
        super().__init__(
            command_prefix="!", 
            intents=intents,
            help_command=None
        )

    async def setup_hook(self):
        # Kalıcı View'leri yüklüyoruz
        self.add_view(TicketLaunchView())
        self.add_view(ApplicationLaunchView())
        
        self.voice_xp_loop.start()
        
        logger.info("Slash komutları senkronize ediliyor...")
        await self.tree.sync()
        logger.info("Slash komutları senkronize edildi.")

    async def on_ready(self):
        logger.info(f"Bot aktif! Kullanıcı: {self.user} (ID: {self.user.id})")
        
        for guild in self.guilds:
            for channel in guild.voice_channels:
                for member in channel.members:
                    if not member.bot:
                        voice_active[member.id] = time.time()
                        
        activity = discord.Activity(type=discord.ActivityType.listening, name="Destek Talepleri | /ping")
        await self.change_presence(status=discord.Status.online, activity=activity)

    @tasks.loop(minutes=1)
    async def voice_xp_loop(self):
        now = time.time()
        for uid, join_time in list(voice_active.items()):
            elapsed = int(now - join_time)
            if elapsed >= 1800:
                voice_active[uid] = now
                old_xp, new_xp = add_xp(uid, 30)
                
                log_channel = self.get_channel(XP_LOG_CHANNEL_ID)
                if log_channel:
                    await log_channel.send(f"🎙️ <@{uid}> ses kanalında 30 dakika geçirdiği için **30 XP** kazandı! Toplam XP: **{new_xp}**")

    @voice_xp_loop.before_loop
    async def before_voice_xp(self):
        await self.wait_until_ready()

bot = AdvancedBot()

# ==========================================
# 6. ETKİNLİK DİNLEYİCİLERİ (EVENTS)
# ==========================================
@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    user_id = member.id
    now = time.time()

    if before.channel is None and after.channel is not None:
        voice_active[user_id] = now
    elif before.channel is not None and after.channel is None:
        if user_id in voice_active:
            duration = int(now - voice_active.pop(user_id))
            voice_times[user_id] = voice_times.get(user_id, 0) + duration
            voice_weekly[user_id] = voice_weekly.get(user_id, 0) + duration
    elif before.channel is not None and after.channel is not None and before.channel.id != after.channel.id:
        if user_id not in voice_active:
            voice_active[user_id] = now

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Sınırsız AI Yanıt Sistemi
    if message.channel.id == AI_CHANNEL_ID:
        async with message.channel.typing():
            try:
                user_msg = message.content.lower().strip()
                ai_reply = ""

                if any(phrase in user_msg for phrase in ["seni kim yap", "seni kim kodla", "yapan kim", "kodlayan kim", "geliştiricin kim"]):
                    ai_reply = "Geliştiricim <@1095004764368015451>"
                elif any(phrase in user_msg for phrase in ["aethel sunucusu", "sunucu hakkında", "sunucu bilgisi", "aethel hakkında"]):
                    ai_reply = "Merhaba. Aethel sunucusunun sahibi <@1145707357498769499>'dır. sunucumuzun amacı arkadaşlar arasında eğlenmektir. kurallara uyarak keyifli sohbetler yapabilirsiniz. iyi eğlenceler."
                else:
                    def get_ai_response():
                        client = InferenceClient(api_key="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")
                        response = client.chat.completions.create(
                            model="Qwen/Qwen2.5-Coder-32B-Instruct",
                            messages=[
                                {"role": "system", "content": "Sen Aethel sunucusunun yapay zeka asistanısın."},
                                {"role": "user", "content": message.content}
                            ],
                            max_tokens=500
                        )
                        return response.choices[0].message.content

                    ai_reply = await asyncio.to_thread(get_ai_response)

                final_text = f"{ai_reply[:1800]}\n\n*Aethel AI System*"

                webhooks = await message.channel.webhooks()
                webhook = webhooks[0] if webhooks else await message.channel.create_webhook(name="Aethel AI Webhook")

                await webhook.send(
                    content=final_text,
                    username="Aethel AI",
                    avatar_url=bot.user.display_avatar.url
                )

            except Exception as e:
                await message.reply(f"❌ AI Hatası: `{e}`")
        return

    # Selamlama
    if message.content.lower() in ["sa", "s.a", "sa.", "selamun aleykum", "selamün aleyküm"]:
        await message.channel.send(f"AleykümSelam! Hoş geldin {message.author.mention}.")

    # XP Sistemi (Ortak XP)
    user_id = message.author.id
    gained_xp = random.randint(5, 15)
    old_xp, new_xp = add_xp(user_id, gained_xp)

    if (old_xp // 100) < (new_xp // 100):
        log_channel = bot.get_channel(XP_LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"🎉 {message.author.mention} tebrikler! **Seviye {new_xp // 100}** ulaştın!")

    await bot.process_commands(message)

# ==========================================
# 7. KOMUTLAR
# ==========================================

# 1. YETKİLİ ALIM PANELİ KURMA KOMUTU
@bot.tree.command(name="yetkili_alim_kur", description="Başvuru panelini bulunduğunuz kanala kurar.")
@app_commands.default_permissions(administrator=True)
async def yetkili_alim_kur(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📋 Yetkili Alım Başvurusu",
        description="Aramıza katılmak ve yetkili ekibimizde yer almak istiyorsanız aşağıdaki **Başvuru Yap** butonuna tıklayarak formu doldurabilirsiniz.\n\nFormu doldurduktan sonra sonuç tarafınıza DM üzerinden iletilecektir.",
        color=discord.Color.gold()
    )
    await interaction.channel.send(embed=embed, view=ApplicationLaunchView())
    await interaction.response.send_message("Başvuru paneli başarıyla kuruldu!", ephemeral=True)

# 2. ÇALIŞMA SÜRESİ KOMUTU
@bot.tree.command(name="calisma_suresi", description="Botun ne kadar süredir kesintisiz açık olduğunu gösterir.")
async def calisma_suresi(interaction: discord.Interaction):
    current_time = time.time()
    uptime_seconds = int(round(current_time - START_TIME))
    uptime_string = str(timedelta(seconds=uptime_seconds))

    embed = discord.Embed(
        title="⏱️ Bot Çalışma Süresi",
        description=f"Bot **{uptime_string}** süredir kesintisiz aktif durumda.",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed)

# 3. ÖZEL DURUM DEĞİŞTİRME KOMUTU (Sadece SPECIAL_USER_ID)
@bot.tree.command(name="durum_degistir", description="Botun yayın/oyun durumunu ve aktiflik modunu değiştirir.")
@app_commands.choices(
    etkinlik_tipi=[
        app_commands.Choice(name="Oynuyor", value="playing"),
        app_commands.Choice(name="İzliyor", value="watching"),
        app_commands.Choice(name="Dinliyor", value="listening"),
        app_commands.Choice(name="Yayın Yapıyor", value="streaming")
    ],
    durum_modu=[
        app_commands.Choice(name="Çevrimiçi (Online)", value="online"),
        app_commands.Choice(name="Boşta (Idle)", value="idle"),
        app_commands.Choice(name="Rahatsız Etmeyin (DND)", value="dnd"),
        app_commands.Choice(name="Görünmez (Invisible)", value="invisible")
    ]
)
async def durum_degistir(interaction: discord.Interaction, etkinlik_tipi: str, isim: str, durum_modu: str):
    if interaction.user.id != SPECIAL_USER_ID:
        return await interaction.response.send_message("❌ Bu komutu sadece geliştirici kullanabilir!", ephemeral=True)

    status_map = {
        "online": discord.Status.online,
        "idle": discord.Status.idle,
        "dnd": discord.Status.dnd,
        "invisible": discord.Status.invisible
    }
    selected_status = status_map.get(durum_modu, discord.Status.online)

    if etkinlik_tipi == "playing":
        activity = discord.Game(name=isim)
    elif etkinlik_tipi == "watching":
        activity = discord.Activity(type=discord.ActivityType.watching, name=isim)
    elif etkinlik_tipi == "listening":
        activity = discord.Activity(type=discord.ActivityType.listening, name=isim)
    elif etkinlik_tipi == "streaming":
        activity = discord.Streaming(name=isim, url="https://www.twitch.tv/directory")

    await bot.change_presence(status=selected_status, activity=activity)
    await interaction.response.send_message(f"✅ Bot durumu **{durum_modu.upper()}** - **{etkinlik_tipi.capitalize()}: {isim}** olarak ayarlandı.", ephemeral=True)

# 4. ŞARKI ÇALMA KOMUTU (!oynat - HERKESE AÇIK / PUBLIC)
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

ffmpeg_options = {
    'options': '-vn',
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

@bot.command(name="oynat", aliases=["p", "play"])
async def oynat(ctx, *, sorgu: str):
    if not ctx.author.voice:
        return await ctx.send("❌ Şarkı çalabilmem için öncelikle bir ses kanalında olmalısınız!")

    voice_channel = ctx.author.voice.channel

    if ctx.voice_client is None:
        await voice_channel.connect()
    elif ctx.voice_client.channel != voice_channel:
        await ctx.voice_client.move_to(voice_channel)

    async with ctx.typing():
        try:
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(sorgu, download=False))

            if 'entries' in data:
                data = data['entries'][0]

            filename = data['url']
            title = data.get('title', 'Bilinmeyen Şarkı')

            if ctx.voice_client.is_playing():
                ctx.voice_client.stop()

            player = discord.FFmpegPCMAudio(filename, **ffmpeg_options)
            ctx.voice_client.play(player)

            await ctx.send(f"🎵 **Şimdi Çalıyor:** `{title}`")

        except Exception as e:
            await ctx.send(f"❌ Şarkı çalınırken hata oluştu: `{e}`")

@bot.command(name="durdur", aliases=["stop"])
async def durdur(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.voice_client.disconnect()
        await ctx.send("⏹️ Müzik durduruldu ve ses kanalından çıkıldı.")

# --- Diğer Sistem Komutları ---
async def send_user_embed(ctx, user_id: int):
    embed = discord.Embed(description=f"<@{user_id}>", color=discord.Color.dark_gold())
    embed.set_image(url=random.choice(RANDOM_IMAGES))
    await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

@bot.command(name="ahmet")
async def ahmet_cmd(ctx): await send_user_embed(ctx, 1269562675805814836)

@bot.command(name="mert")
async def mert_cmd(ctx): await send_user_embed(ctx, 1152331381834272859)

@bot.command(name="yücel")
async def yucel_cmd(ctx): await send_user_embed(ctx, 1145707357498769499)

@bot.command(name="yavuz")
async def yavuz_cmd(ctx): await send_user_embed(ctx, 1459625517467701362)

@bot.command(name="agil")
async def agil_cmd(ctx): await send_user_embed(ctx, 1095004764368015451)

@bot.command(name="haktan")
async def haktan_cmd(ctx): await send_user_embed(ctx, 1354867231472877881)

@bot.command(name="demir")
async def demir_cmd(ctx): await send_user_embed(ctx, 896862922557505567)

@bot.tree.command(name="vampir_koylu_baslat", description="Vampir-Köylü oyunu lobisini başlatır.")
async def vampir_koylu_baslat(interaction: discord.Interaction):
    embed = discord.Embed(title="🩸 Vampir - Köylü Oyunu Lobisi", description="Oyuna katılmak için aşağıdaki butona tıklayın.", color=discord.Color.red())
    await interaction.response.send_message(embed=embed, view=VampirKoyluLobbyView(host=interaction.user))

@bot.tree.command(name="kostebek_kim_baslat", description="Köstebek Kim oyunu lobisini başlatır.")
async def kostebek_kim_baslat(interaction: discord.Interaction):
    embed = discord.Embed(title="🕵️ Köstebek Kim? Lobisi", description="Oyuna katılmak için Katıl butonuna basın.", color=discord.Color.purple())
    await interaction.response.send_message(embed=embed, view=KostebekLobbyView(host=interaction.user))

@bot.tree.command(name="ses_istatistik", description="Ses kanallarında geçirilen süreyi gösterir.")
async def ses_istatistik(interaction: discord.Interaction, member: discord.Member = None):
    target = member or interaction.user
    uid = target.id
    current_active = int(time.time() - voice_active[uid]) if uid in voice_active else 0
    
    total_sec = voice_times.get(uid, 0) + current_active
    weekly_sec = voice_weekly.get(uid, 0) + current_active
    
    t_min, t_sec = divmod(total_sec, 60)
    t_hour, t_min = divmod(t_min, 60)
    w_min, w_sec = divmod(weekly_sec, 60)
    w_hour, w_min = divmod(w_min, 60)
    c_min, c_sec = divmod(current_active, 60)
    
    if total_sec == 0 and current_active == 0:
        return await interaction.response.send_message(f"📊 {target.mention} için henüz ses verisi bulunamadı.")

    msg = (f"🎙️ **{target.display_name} Ses İstatistikleri**\n"
           f"• **Anlık Seste Kalma Süresi:** {c_min} dk, {c_sec} sn\n"
           f"• **Haftalık Seste Kalma Süresi:** {w_hour} saat, {w_min} dk\n"
           f"• **Toplam Seste Kalma Süresi:** {t_hour} saat, {t_min} dk")
    await interaction.response.send_message(msg)

@bot.command(name="sese", aliases=["sesegir"])
async def sese_gir(ctx, channel_id: int):
    if not check_roles(ctx, MOD_ROLES): return await ctx.send("Bu komutu kullanmaya yetkiniz yok.")
    channel = bot.get_channel(channel_id)
    if not channel or not isinstance(channel, discord.VoiceChannel): return await ctx.send("❌ Geçersiz bir ses kanalı ID'si!")
    try:
        await channel.connect(reconnect=True)
        await ctx.send(f"🔊 **{channel.name}** kanalına bağlandım!")
    except Exception as e: await ctx.send(f"❌ Bağlanırken hata oluştu: `{e}`")

@bot.tree.command(name="ping", description="Botun gecikme süresini gösterir.")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"🏓 Pong! Gecikme: **{round(bot.latency * 1000)}ms**", ephemeral=True)

@bot.tree.command(name="sunucu_bilgi", description="Sunucu hakkında genel bilgilendirme yapar.")
async def sunucu_bilgi(interaction: discord.Interaction):
    guild = interaction.guild
    embed = discord.Embed(title=f"🏰 {guild.name} — Sunucu Bilgilendirmesi", description="• **Kurucumuz:** <@1145707357498769499> (**duckyre**)", color=discord.Color.dark_theme())
    if guild.icon: embed.set_thumbnail(url=guild.icon.url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="cekilis_baslat", description="Çekiliş başlatır.")
async def cekilis_baslat(interaction: discord.Interaction, sure_dakika: int, odul: str, kazanan_sayisi: int = 1):
    if not check_roles(interaction, MOD_ROLES): return await interaction.response.send_message("Yetkiniz yok.", ephemeral=True)
    end_time = time.time() + (sure_dakika * 60)
    embed = discord.Embed(title="🎉 ÇEKİLİŞ BAŞLADI!", description=f"Ödül: **{odul}**\nKazanan Sayısı: **{kazanan_sayisi}**", color=discord.Color.gold())
    g_view = GiveawayView(host_id=interaction.user.id, winner_count=kazanan_sayisi, prize=odul, end_time=end_time)
    await interaction.response.send_message("Çekiliş oluşturuldu.", ephemeral=True)
    await interaction.channel.send(embed=embed, view=g_view)
    await asyncio.sleep(sure_dakika * 60)
    await finish_giveaway(interaction.channel, g_view)

@bot.tree.command(name="temizle", description="Mesaj siler.")
async def temizle(interaction: discord.Interaction, miktar: int):
    if not check_roles(interaction, MOD_ROLES): return await interaction.response.send_message("Yetkiniz yok.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=miktar)
    await interaction.followup.send(f"🧹 **{len(deleted)}** mesaj silindi.", ephemeral=True)

@bot.tree.command(name="rank", description="Mevcut XP ve Seviyeni gösterir.")
async def rank(interaction: discord.Interaction, member: discord.Member = None):
    target = member or interaction.user
    xp = user_xp.get(target.id, 0)
    level = xp // 100
    await interaction.response.send_message(f"📊 **{target.display_name}** | Seviye: **{level}** | Toplam XP: **{xp}**")

@bot.tree.command(name="ticket-kur", description="Destek paneli kurar.")
@app_commands.checks.has_permissions(administrator=True)
async def ticket_kur(interaction: discord.Interaction):
    embed = discord.Embed(title="🎫 Destek Sistemi", description="Aşağıdaki menüden bilet açabilirsiniz.", color=discord.Color.green())
    await interaction.channel.send(embed=embed, view=TicketLaunchView())
    await interaction.response.send_message("Ticket paneli kuruldu.", ephemeral=True)

# ==========================================
# 8. BAŞLATMA DÖNGÜSÜ
# ==========================================
async def main():
    if not TOKEN:
        logger.critical("HATA: 'DISCORD_TOKEN' bulunamadı!")
        return

    async with bot:
        try:
            logger.info("Bot başlatılıyor...")
            await bot.start(TOKEN)
        except Exception as e:
            logger.error(f"Hata: {e}", exc_info=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Sistem kapatıldı.")
