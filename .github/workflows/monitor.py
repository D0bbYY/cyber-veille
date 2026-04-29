import feedparser
import requests
import json
import os
import re
from datetime import datetime

# ─── Configuration ────────────────────────────────────────────────────────────

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
SEEN_FILE = "seen_articles.json"

SOURCES = [
    {
        "name": "Splunk Security",
        "rss": "https://www.splunk.com/en_us/blog/security.rss",
        "color": 0x65A637,
        "emoji": "🟢",
    },
    {
        "name": "Elastic Security Labs",
        "rss": "https://www.elastic.co/security-labs/rss/feed.xml",
        "color": 0x00BFB3,
        "emoji": "🔵",
    },
    {
        "name": "DFIR Report",
        "rss": "https://thedfirreport.com/feed/",
        "color": 0xE74C3C,
        "emoji": "🔴",
    },
    {
        "name": "CrowdStrike Blog",
        "rss": "https://www.crowdstrike.com/blog/feed/",
        "color": 0xFF0000,
        "emoji": "🦅",
    },
    {
        "name": "Unit 42 – Palo Alto",
        "rss": "https://unit42.paloaltonetworks.com/feed/",
        "color": 0xFA582D,
        "emoji": "🔶",
    },
    {
        "name": "Microsoft Security Blog",
        "rss": "https://www.microsoft.com/en-us/security/blog/feed/",
        "color": 0x0078D4,
        "emoji": "🪟",
    },
]

# ─── Helpers ──────────────────────────────────────────────────────────────────

def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


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
    title = (entry.get("title") or "Nouvel article")[:256]
    link = entry.get("link", "")
    summary = strip_html(entry.get("summary") or entry.get("description") or "")
    if len(summary) > 350:
        summary = summary[:347] + "…"

    embed = {
        "title": title,
        "url": link,
        "description": summary or "_Pas de résumé disponible._",
        "color": source["color"],
        "footer": {
            "text": f"📡 {source['name']}  •  {datetime.utcnow().strftime('%d/%m/%Y %H:%M')} UTC"
        },
    }

    payload = {
        "content": f"{source['emoji']} **Nouveau : {source['name']}**",
        "embeds": [embed],
        "username": "Cyber Veille Bot",
        "avatar_url": "https://cdn-icons-png.flaticon.com/512/2092/2092757.png",
    }

    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        if r.status_code in (200, 204):
            print(f"  ✅ Notif envoyée : {title}")
        else:
            print(f"  ⚠️  Erreur Discord {r.status_code} : {r.text[:200]}")
    except Exception as e:
        print(f"  ❌ Impossible d'envoyer la notif : {e}")


# ─── Core logic ───────────────────────────────────────────────────────────────

def check_source(source: dict, seen: dict) -> None:
    key = source["name"]
    if key not in seen:
        seen[key] = []

    print(f"🔍 Vérification : {source['name']} …")
    try:
        feed = feedparser.parse(source["rss"])
    except Exception as e:
        print(f"  ❌ Erreur RSS : {e}")
        return

    first_run = len(seen[key]) == 0
    new_count = 0

    for entry in feed.entries[:15]:
        entry_id = entry.get("id") or entry.get("link") or entry.get("title")
        if not entry_id:
            continue

        if entry_id not in seen[key]:
            if not first_run:
                send_notification(source, entry)
                new_count += 1
            seen[key].append(entry_id)

    # Garde uniquement les 150 derniers IDs pour éviter un fichier trop gros
    seen[key] = seen[key][-150:]

    if first_run:
        print(f"  ℹ️  Premier lancement — {len(seen[key])} articles enregistrés (pas de notif)")
    else:
        print(f"  {'🆕' if new_count else '✓ '} {new_count} nouveau(x) article(s)")


def main() -> None:
    if not WEBHOOK_URL:
        print("❌ Variable DISCORD_WEBHOOK_URL manquante !")
        return

    print(f"\n{'='*50}")
    print(f"  Cyber Veille — {datetime.utcnow().strftime('%d/%m/%Y %H:%M')} UTC")
    print(f"{'='*50}\n")

    seen = load_seen()

    for source in SOURCES:
        check_source(source, seen)

    save_seen(seen)
    print("\n✅ Vérification terminée.")


if __name__ == "__main__":
    main()
