#!/usr/bin/env python3
"""
CA Attorney General Charity Filing Monitor
Checks two charity profiles for new filings and sends Discord notifications.
"""

import os
import json
import hashlib
import sys
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime

# Charity profiles to monitor
CHARITIES = [
    {
        "id": "add8a22f-3bcc-4f1f-9061-f3bdd2d2666b",
        "url": "https://rct.doj.ca.gov/Verification/Web/Details.aspx?result=add8a22f-3bcc-4f1f-9061-f3bdd2d2666b",
        "label": "Charity 1",
    },
    {
        "id": "b6573c8d-8fb8-4d17-98b8-f0424da5399a",
        "url": "https://rct.doj.ca.gov/Verification/Web/Details.aspx?result=b6573c8d-8fb8-4d17-98b8-f0424da5399a",
        "label": "Charity 2",
    },
]

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
STATE_FILE = "filing_state.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def load_state():
    """Load the previously saved filing state."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_state(state):
    """Save the current filing state."""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def fetch_page(url, retries=3):
    """Fetch a page with retries."""
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            print(f"  Attempt {attempt + 1}/{retries} failed: {e}")
            if attempt < retries - 1:
                time.sleep(5)
    return None


def parse_filings(html, charity_label):
    """
    Parse the charity detail page and extract filing information.
    Returns a dict of {filing_id: filing_info} and the charity name.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Extract charity name from page title or heading
    charity_name = charity_label
    name_candidates = [
        soup.find("h1"),
        soup.find("h2"),
        soup.find(class_="org-name"),
        soup.find(class_="charity-name"),
        soup.find("title"),
    ]
    for el in name_candidates:
        if el and el.get_text(strip=True):
            text = el.get_text(strip=True)
            if text and text.lower() not in ("", "registry search"):
                charity_name = text
                break

    # Look for filing tables — the CA AG site uses data tables for filings
    filings = {}
    tables = soup.find_all("table")

    for table in tables:
        rows = table.find_all("tr")
        headers = []
        header_row = table.find("tr")
        if header_row:
            headers = [th.get_text(strip=True).lower() for th in header_row.find_all(["th", "td"])]

        # Skip tables that don't look like filing tables
        filing_keywords = {"filing", "form", "year", "date", "document", "type", "fiscal"}
        if not any(kw in " ".join(headers) for kw in filing_keywords):
            continue

        for row in rows[1:]:  # Skip header row
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            row_text = [c.get_text(strip=True) for c in cells]
            if not any(row_text):
                continue

            # Build a unique key from the row content
            row_key = hashlib.md5("|".join(row_text).encode()).hexdigest()

            # Try to find a link (document link)
            link = row.find("a")
            doc_url = None
            if link and link.get("href"):
                href = link["href"]
                if not href.startswith("http"):
                    href = "https://rct.doj.ca.gov" + href
                doc_url = href

            filings[row_key] = {
                "cells": row_text,
                "headers": headers,
                "doc_url": doc_url,
                "raw": " | ".join(row_text),
            }

    # Fallback: if no table found, hash key sections of the page that
    # indicate filing listings (look for list items or divs with filing info)
    if not filings:
        # Try to find any filing-related content blocks
        for el in soup.find_all(["li", "div", "p"]):
            text = el.get_text(strip=True)
            if len(text) > 20 and any(
                kw in text.lower()
                for kw in ["990", "rrf", "filing", "annual report", "form ct"]
            ):
                key = hashlib.md5(text.encode()).hexdigest()
                filings[key] = {
                    "cells": [text],
                    "headers": [],
                    "doc_url": None,
                    "raw": text,
                }

    return filings, charity_name


def format_filing_for_discord(filing_info, headers):
    """Format a single filing entry for Discord display."""
    if headers and len(headers) == len(filing_info["cells"]):
        parts = []
        for h, v in zip(headers, filing_info["cells"]):
            if h and v:
                parts.append(f"**{h.title()}:** {v}")
        return "\n".join(parts) if parts else filing_info["raw"]
    return filing_info["raw"]


def send_discord_notification(charity_name, charity_url, new_filings):
    """Send a Discord webhook notification about new filings."""
    if not DISCORD_WEBHOOK_URL:
        print("ERROR: DISCORD_WEBHOOK_URL not set.")
        return False

    count = len(new_filings)
    plural = "filing" if count == 1 else "filings"

    embeds = []
    for i, (key, info) in enumerate(new_filings.items()):
        if i >= 10:  # Discord limits embeds
            break
        description = format_filing_for_discord(info, info.get("headers", []))
        if len(description) > 1024:
            description = description[:1021] + "..."

        embed = {
            "description": description,
            "color": 0x003366,  # CA AG dark blue
        }
        if info.get("doc_url"):
            embed["url"] = info["doc_url"]
            embed["title"] = "📄 View Document"

        embeds.append(embed)

    payload = {
        "username": "CA AG Filing Monitor",
        "avatar_url": "https://oag.ca.gov/sites/all/themes/oag/logo.png",
        "embeds": [
            {
                "title": f"🔔 {count} New {plural.title()} — {charity_name}",
                "url": charity_url,
                "description": (
                    f"**{count}** new {plural} detected on the "
                    f"[CA Attorney General Registry]({charity_url}).\n"
                    f"**Checked:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
                ),
                "color": 0x1DA1F2,
                "footer": {"text": "CA AG Charity Filing Monitor"},
            }
        ]
        + embeds,
    }

    resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
    if resp.status_code in (200, 204):
        print(f"  ✅ Discord notified: {count} new {plural} for {charity_name}")
        return True
    else:
        print(f"  ❌ Discord webhook failed: {resp.status_code} {resp.text}")
        return False


def send_error_notification(message):
    """Send an error notification to Discord."""
    if not DISCORD_WEBHOOK_URL:
        return
    payload = {
        "username": "CA AG Filing Monitor",
        "embeds": [
            {
                "title": "⚠️ Monitor Error",
                "description": message,
                "color": 0xFF0000,
                "footer": {"text": "CA AG Charity Filing Monitor"},
            }
        ],
    }
    requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)


def main():
    print(f"🔍 CA AG Filing Monitor — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    state = load_state()
    any_errors = False

    for charity in CHARITIES:
        cid = charity["id"]
        label = charity["label"]
        url = charity["url"]

        print(f"\n📋 Checking {label} ({cid[:8]}...)")
        html = fetch_page(url)

        if html is None:
            msg = f"Failed to fetch page for {label}:\n{url}"
            print(f"  ❌ {msg}")
            send_error_notification(msg)
            any_errors = True
            continue

        filings, charity_name = parse_filings(html, label)
        print(f"  Found {len(filings)} filing entries for: {charity_name}")

        # Update label with real name if found
        if charity_name != label:
            print(f"  Name resolved: {charity_name}")

        previous_keys = set(state.get(cid, {}).get("filing_keys", []))
        current_keys = set(filings.keys())
        new_keys = current_keys - previous_keys

        if not previous_keys:
            print(f"  ℹ️  First run — saving baseline ({len(current_keys)} entries). No notification sent.")
        elif new_keys:
            print(f"  🆕 {len(new_keys)} new filing(s) detected!")
            new_filings = {k: filings[k] for k in new_keys}
            send_discord_notification(charity_name, url, new_filings)
        else:
            print(f"  ✅ No new filings.")

        # Save updated state
        state[cid] = {
            "charity_name": charity_name,
            "url": url,
            "filing_keys": list(current_keys),
            "last_checked": datetime.utcnow().isoformat(),
            "filing_count": len(current_keys),
        }

    save_state(state)
    print("\n✅ State saved.")
    return 1 if any_errors else 0


if __name__ == "__main__":
    sys.exit(main())
