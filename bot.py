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
    "Splunk Threat Research",
    "Elastic Security Labs",
    "DFIR Report",
    "CrowdStrike Blog",
    "Unit 42 – Palo Alto",
    "Microsoft Security Blog",
]

EMOJIS = {
    "Splunk Threat Research":  "🟢",
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
    {
        "name":       "Splunk Threat Research",
        "rss":        [],
        "scrape_url": "https://www.splunk.com/en_us/blog/author/secmrkt-research.html",
        "color":      0x65A637, "emoji": "🟢",
    },
    {"name": "Elastic Security Labs",  "rss": ["https://www.elastic.co/security-labs/rss/feed.xml", "https://www.elastic.co/blog/feed"],          "color": 0x00BFB3, "emoji": "🔵"},
    {"name": "DFIR Report",            "rss": ["https://thedfirreport.com/feed/"],                                                                  "color": 0xE74C3C, "emoji": "🔴"},
    {"name": "CrowdStrike Blog",       "rss": ["https://www.crowdstrike.com/blog/feed/"],                                                           "color": 0xFF0000, "emoji": "🦅"},
    {"name": "Unit 42 – Palo Alto",   "rss": ["https://unit42.paloaltonetworks.com/feed/"],                                                         "color": 0xFA582D, "emoji": "🔶"},
    {"name": "Microsoft Security Blog","rss": ["https://www.microsoft.com/en-us/security/blog/feed/"],                                              "color": 0x0078D4, "emoji": "🪟"},
]

FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
}

def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return re.sub(r"\s+", " ", text).strip()


def scrape_splunk(url: str) -> list:
    """Scrape la page auteur Splunk — capture les articles cards + éventuellement l'article featured en tête."""
    try:
        r = requests.get(url, headers=FETCH_HEADERS, timeout=15)
        if r.status_code != 200:
            return []

        seen_links = {}

        # Pattern 1 : h3.article-card-title avec .*? pour tolérer badges/spans avant le <a>
        card_pattern = (
            r'<h3[^>]*class="article-card-title"[^>]*>'
            r'.*?'
            r'<a[^>]*href="(/en_us/blog/[^"#]+)"[^>]*>\s*([^<]+?)\s*</a>'
        )
        desc_pattern = r'<div[^>]*class="article-card-description"[^>]*>(.*?)</div>'
        cards = re.findall(card_pattern, r.text, re.IGNORECASE | re.DOTALL)
        descs = re.findall(desc_pattern, r.text, re.IGNORECASE | re.DOTALL)
        for i, (href, title) in enumerate(cards):
            link = f"https://www.splunk.com{href}"
            if link not in seen_links:
                seen_links[link] = {
                    "title":   title.strip(),
                    "summary": strip_html(descs[i]) if i < len(descs) else "",
                }

        # Pattern 2 : fallback — tout <a> blog avec texte >15 chars
        fallback_pattern = r'<a[^>]+href="(/en_us/blog/[^/"]+/[^/"]+\.html)"[^>]*>\s*([^<]{15,}?)\s*</a>'
        for href, title in re.findall(fallback_pattern, r.text, re.IGNORECASE):
            link = f"https://www.splunk.com{href}"
            if link not in seen_links:
                seen_links[link] = {"title": title.strip(), "summary": ""}

        return [
            {"id": lnk, "link": lnk, "title": meta["title"], "summary": meta["summary"]}
            for lnk, meta in seen_links.items()
        ][:15]
    except Exception:
        return []


@client.tree.command(name="latest", description="📰 Affiche le dernier article de chaque source active")
async def latest_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)

    config  = load_config()
    enabled = config.get("sources", {})
    active  = [s for s in ALL_SOURCES_DEF if enabled.get(s["name"], True)]

    if not active:
        await interaction.followup.send("⚠️ Aucune source active. Utilise `/config` pour en activer.", ephemeral=True)
        return

    embeds  = []
    failed  = []

    for source in active:
        urls    = source["rss"] if isinstance(source["rss"], list) else [source["rss"]]
        entries = []

        for url in urls:
            try:
                feed = feedparser.parse(url, request_headers=FETCH_HEADERS)
                if feed.entries:
                    entries = list(feed.entries[:3])
                    break
            except Exception:
                continue

        # Fallback scraping si RSS vide
        if not entries and source.get("scrape_url"):
            entries = scrape_splunk(source["scrape_url"])[:3]

        if not entries:
            failed.append(f"{source['emoji']} {source['name']}")
            continue

        # Un embed par source avec les 3 articles listés dedans
        lines = []
        for e in entries:
            title = (e.get("title") or "Article").strip()
            link  = e.get("link", "")
            lines.append(f"**[{title}]({link})**")

        embed = discord.Embed(
            title       = f"{source['emoji']} {source['name']}",
            description = "\n\n".join(lines),
            color       = source["color"],
        )
        embeds.append(embed)

        if len(embeds) == 10:
            break

    if not embeds and not failed:
        await interaction.followup.send("❌ Impossible de récupérer les articles pour l'instant.", ephemeral=True)
        return

    content = "📡 **Derniers articles — Cyber Veille**"
    if failed:
        content += f"\n⚠️ Sources inaccessibles : {', '.join(failed)}"

    await interaction.followup.send(content=content, embeds=embeds)


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
