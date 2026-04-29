"""
Cyber Veille Bot — Menu Discord interactif
Commandes : /config  /latest
"""

import discord
from discord import app_commands
import json
import os
import base64
import re
import requests
import feedparser
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN    = os.getenv("DISCORD_BOT_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO  = os.getenv("GITHUB_REPO")   # ex : "paulbaptiste/cyber-veille"
CONFIG_FILE  = "config.json"

ALL_SOURCES = [
    "Splunk Security",
    "Elastic Security Labs",
    "DFIR Report",
    "CrowdStrike Blog",
    "Unit 42 – Palo Alto",
    "Microsoft Security Blog",
]

EMOJIS = {
    "Splunk Security":        "🟢",
    "Elastic Security Labs":  "🔵",
    "DFIR Report":            "🔴",
    "CrowdStrike Blog":       "🦅",
    "Unit 42 – Palo Alto":   "🔶",
    "Microsoft Security Blog":"🪟",
}

# ─── Config helpers ───────────────────────────────────────────────────────────

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"sources": {s: True for s in ALL_SOURCES}, "mode": "all"}


def save_config(config: dict) -> bool:
    """Sauvegarde config.json localement ET le pousse sur GitHub."""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    if not (GITHUB_TOKEN and GITHUB_REPO):
        return False

    url     = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{CONFIG_FILE}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept":        "application/vnd.github.v3+json",
        "User-Agent":    "CyberVeilleBot/1.0",
    }

    # Récupère le SHA actuel (nécessaire pour mettre à jour)
    r   = requests.get(url, headers=headers, timeout=10)
    sha = r.json().get("sha") if r.status_code == 200 else None

    content = base64.b64encode(
        json.dumps(config, indent=2, ensure_ascii=False).encode()
    ).decode()

    data = {
        "message": "chore: update config via Discord bot [skip ci]",
        "content": content,
    }
    if sha:
        data["sha"] = sha

    r = requests.put(url, headers=headers, json=data, timeout=10)
    return r.status_code in (200, 201)

# ─── UI Components ────────────────────────────────────────────────────────────

class SourceSelect(discord.ui.Select):
    def __init__(self, enabled: dict):
        options = [
            discord.SelectOption(
                label=f"{EMOJIS.get(s, '•')} {s}",
                value=s,
                default=enabled.get(s, True),
            )
            for s in ALL_SOURCES
        ]
        super().__init__(
            placeholder="Choisir les sources à surveiller…",
            min_values=1,
            max_values=len(ALL_SOURCES),
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_sources = list(self.values)
        await interaction.response.defer()


class ConfigView(discord.ui.View):
    def __init__(self, config: dict):
        super().__init__(timeout=300)
        self.mode             = config.get("mode", "all")
        self.selected_sources = [s for s, v in config.get("sources", {}).items() if v]

        self.select = SourceSelect(config.get("sources", {}))
        self.add_item(self.select)

        self._update_button_styles()

    def _update_button_styles(self):
        for item in self.children:
            if not isinstance(item, discord.ui.Button):
                continue
            if item.custom_id == "mode_all":
                item.style = (
                    discord.ButtonStyle.success
                    if self.mode == "all"
                    else discord.ButtonStyle.secondary
                )
            elif item.custom_id == "mode_latest":
                item.style = (
                    discord.ButtonStyle.success
                    if self.mode == "latest"
                    else discord.ButtonStyle.secondary
                )

    @discord.ui.button(
        label="📰 Tous les articles",
        custom_id="mode_all",
        style=discord.ButtonStyle.success,
        row=1,
    )
    async def btn_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mode = "all"
        self._update_button_styles()
        await interaction.response.edit_message(view=self)

    @discord.ui.button(
        label="📌 Dernier article seulement",
        custom_id="mode_latest",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def btn_latest(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mode = "latest"
        self._update_button_styles()
        await interaction.response.edit_message(view=self)

    @discord.ui.button(
        label="✅ Sauvegarder",
        style=discord.ButtonStyle.primary,
        row=2,
    )
    async def btn_save(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Priorise la sélection actuelle du menu
        sources_active = (
            list(self.select.values)
            if self.select.values
            else self.selected_sources
        )

        new_config = {
            "sources": {s: (s in sources_active) for s in ALL_SOURCES},
            "mode":    self.mode,
        }

        ok = save_config(new_config)

        active     = [f"{EMOJIS.get(s,'•')} {s}" for s, v in new_config["sources"].items() if v]
        mode_label = "📰 Tous les articles" if self.mode == "all" else "📌 Dernier article seulement"

        embed = discord.Embed(title="✅ Configuration sauvegardée !", color=0x2ECC71)
        embed.add_field(name="Sources actives",  value="\n".join(active) or "Aucune", inline=False)
        embed.add_field(name="Mode de réception", value=mode_label,                   inline=False)
        embed.set_footer(
            text=(
                "Synchronisé avec GitHub ✓ — Actif au prochain check horaire"
                if ok
                else "⚠️  GitHub non synchronisé (vérifie GITHUB_TOKEN et GITHUB_REPO)"
            )
        )

        self.stop()
        await interaction.response.edit_message(embed=embed, view=None)

# ─── Bot ──────────────────────────────────────────────────────────────────────

MY_GUILD = discord.Object(id=1497953495377117316)  # Ton serveur Discord


class CyberVeilleBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # Copie les commandes sur le serveur → sync instantané
        self.tree.copy_global_to(guild=MY_GUILD)
        await self.tree.sync(guild=MY_GUILD)
        print("✅ Commandes slash synchronisées sur le serveur")

    async def on_ready(self):
        print(f"✅ Bot connecté : {self.user}  (ID {self.user.id})")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="les blogs cyber 👁️"
            )
        )


client = CyberVeilleBot()


ALL_SOURCES_DEF = [
    {"name": "Splunk Security",        "rss": "https://www.splunk.com/en_us/blog/security.rss",                    "color": 0x65A637, "emoji": "🟢"},
    {"name": "Elastic Security Labs",  "rss": "https://www.elastic.co/security-labs/rss/feed.xml",                 "color": 0x00BFB3, "emoji": "🔵"},
    {"name": "DFIR Report",            "rss": "https://thedfirreport.com/feed/",                                    "color": 0xE74C3C, "emoji": "🔴"},
    {"name": "CrowdStrike Blog",       "rss": "https://www.crowdstrike.com/blog/feed/",                             "color": 0xFF0000, "emoji": "🦅"},
    {"name": "Unit 42 – Palo Alto",   "rss": "https://unit42.paloaltonetworks.com/feed/",                          "color": 0xFA582D, "emoji": "🔶"},
    {"name": "Microsoft Security Blog","rss": "https://www.microsoft.com/en-us/security/blog/feed/",                "color": 0x0078D4, "emoji": "🪟"},
]

FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
}

def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return re.sub(r"\s+", " ", text).strip()


@client.tree.command(name="latest", description="📰 Affiche le dernier article de chaque source active")
async def latest_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)

    config  = load_config()
    enabled = config.get("sources", {})
    active  = [s for s in ALL_SOURCES_DEF if enabled.get(s["name"], True)]

    if not active:
        await interaction.followup.send("⚠️ Aucune source active. Utilise `/config` pour en activer.", ephemeral=True)
        return

    embeds = []
    for source in active:
        try:
            feed = feedparser.parse(source["rss"], request_headers=FETCH_HEADERS)
            if not feed.entries:
                continue
            entry   = feed.entries[0]
            title   = (entry.get("title") or "Article")[:256]
            link    = entry.get("link", "")
            summary = strip_html(entry.get("summary") or entry.get("description") or "")
            if len(summary) > 300:
                summary = summary[:297] + "…"

            embeds.append(discord.Embed(
                title       = f"{source['emoji']} {title}",
                url         = link,
                description = summary or "_Pas de résumé._",
                color       = source["color"],
            ).set_footer(text=source["name"]))
        except Exception:
            continue

        # Discord max 10 embeds par message
        if len(embeds) == 10:
            break

    if not embeds:
        await interaction.followup.send("❌ Impossible de récupérer les articles pour l'instant.", ephemeral=True)
        return

    await interaction.followup.send(content="📡 **Derniers articles — Cyber Veille**", embeds=embeds)


@client.tree.command(name="config", description="⚙️ Configurer la surveillance des blogs cyber")
async def config_cmd(interaction: discord.Interaction):
    config     = load_config()
    enabled    = config.get("sources", {})
    mode_label = "📰 Tous les articles" if config.get("mode") == "all" else "📌 Dernier article seulement"
    active     = [f"{EMOJIS.get(s,'•')} {s}" for s, v in enabled.items() if v]

    embed = discord.Embed(
        title="⚙️ Cyber Veille — Configuration",
        description="Sélectionne tes sources et ton mode de réception, puis clique **Sauvegarder**.",
        color=0x5865F2,
    )
    embed.add_field(name="Sources actives",   value="\n".join(active) or "Aucune", inline=False)
    embed.add_field(name="Mode actuel",       value=mode_label,                   inline=False)
    embed.set_footer(text="Seul toi peux voir ce message.")

    await interaction.response.send_message(embed=embed, view=ConfigView(config), ephemeral=True)


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("❌ DISCORD_BOT_TOKEN manquant dans le fichier .env")
    else:
        client.run(BOT_TOKEN)
