import feedparser
import requests
import json
import os
import re
from datetime import datetime

# ─── Configuration ────────────────────────────────────────────────────────────

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
SEEN_FILE   = "seen_articles.json"
CONFIG_FILE = "config.json"

ALL_SOURCES = [
    {
        "name":  "Splunk Security",
        "rss":   "https://www.splunk.com/en_us/blog/security.rss",
        "color": 0x65A637,
        "emoji": "🟢",
    },
    {
        "name":  "Elastic Security Labs",
        "rss":   "https://www.elastic.co/security-labs/rss/feed.xml",
        "color": 0x00BFB3,
        "emoji": "🔵",
    },
    {
        "name":  "DFIR Report",
        "rss":   "https://thedfirreport.com/feed/",
        "color": 0xE74C3C,
        "emoji": "🔴",
    },
    {
        "name":  "CrowdStrike Blog",
        "rss":   "https://www.crowdstrike.com/blog/feed/",
        "color": 0xFF0000,
        "emoji": "🦅",
    },
    {
        "name":  "Unit 42 – Palo Alto",
        "rss":   "https://unit42.paloaltonetworks.com/feed/",
        "color": 0xFA582D,
        "emoji": "🔶",
    },
    {
        "name":  "Microsoft Security Blog",
        "rss":   "https://www.microsoft.com/en-us/security/blog/feed/",
        "color": 0x0078D4,
        "emoji": "🪟",
    },
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# ─── Config ───────────────────────────────────────────────────────────────────

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "sources": {s["name"]: True for s in ALL_SOURCES},
        "mode": "all",
    }

# ─── Helpers ──────────────────────────────────────────────────────────────────

def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return re.sub(r"\s+", " ", text).strip()

def load_seen() -> dict:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_seen(seen: dict) -> None:
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, indent=2, ensure_ascii=False)

# ─── Discord ──────────────────────────────────────────────────────────────────

def send_notification(source: dict, entry) -> None:
    title   = (entry.get("title") or "Nouvel article")[:256]
    link    = entry.get("link", "")
    summary = strip_html(entry.get("summary") or entry.get("description") or "")
    if len(summary) > 350:
        summary = summary[:347] + "…"

    embed = {
        "title":       title,
        "url":         link,
        "description": summary or "_Pas de résumé disponible._",
        "color":       source["color"],
        "footer": {
            "text": f"📡 {source['name']}  •  {datetime.utcnow().strftime('%d/%m/%Y %H:%M')} UTC"
        },
    }

    payload = {
        "content":    f"{source['emoji']} **Nouveau : {source['name']}**",
        "embeds":     [embed],
        "username":   "Cyber Veille Bot",
        "avatar_url": "https://cdn-icons-png.flaticon.com/512/2092/2092757.png",
    }

    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        if r.status_code in (200, 204):
            print(f"  ✅ Notif envoyée : {title}")
        else:
            print(f"  ⚠️  Discord {r.status_code} : {r.text[:200]}")
    except Exception as e:
        print(f"  ❌ Erreur envoi notif : {e}")

# ─── Core logic ───────────────────────────────────────────────────────────────

def check_source(source: dict, seen: dict, mode: str) -> None:
    key = source["name"]
    if key not in seen:
        seen[key] = []

    print(f"🔍 {source['name']} …")

    try:
        feed = feedparser.parse(source["rss"], request_headers=HEADERS)
    except Exception as e:
        print(f"  ❌ Erreur RSS : {e}")
        return

    if not feed.entries:
        print(f"  ⚠️  Flux vide ou inaccessible")
        return

    first_run   = len(seen[key]) == 0
    new_entries = []

    for entry in feed.entries[:15]:
        entry_id = entry.get("id") or entry.get("link") or entry.get("title")
        if entry_id and entry_id not in seen[key]:
            if not first_run:
                new_entries.append(entry)
            seen[key].append(entry_id)

    seen[key] = seen[key][-150:]

    if first_run:
        print(f"  ℹ️  Premier lancement — {len(seen[key])} articles enregistrés (pas de notif)")
        return

    if not new_entries:
        print(f"  ✓  Aucun nouvel article")
        return

    to_notify = new_entries[:1] if mode == "latest" else new_entries

    for entry in to_notify:
        send_notification(source, entry)

    print(f"  🆕 {len(to_notify)} notif(s) envoyée(s) [mode={mode}]")


def main() -> None:
    if not WEBHOOK_URL:
        print("❌ DISCORD_WEBHOOK_URL manquant !")
        return

    config          = load_config()
    enabled_sources = config.get("sources", {})
    mode            = config.get("mode", "all")

    print(f"\n{'='*52}")
    print(f"  Cyber Veille — {datetime.utcnow().strftime('%d/%m/%Y %H:%M')} UTC")
    print(f"  Mode : {mode}")
    print(f"{'='*52}\n")

    seen = load_seen()

    for source in ALL_SOURCES:
        if not enabled_sources.get(source["name"], True):
            print(f"⏭️  {source['name']} — désactivée")
            continue
        check_source(source, seen, mode)

    save_seen(seen)
    print("\n✅ Vérification terminée.")


if __name__ == "__main__":
    main()
