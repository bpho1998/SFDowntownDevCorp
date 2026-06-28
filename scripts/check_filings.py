#!/usr/bin/env python3
"""
CA Attorney General Charity Filing Monitor
Uses Playwright (headless Chromium) to handle JS-rendered pages.
"""

import os
import json
import hashlib
import sys
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

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


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def fetch_page_playwright(url, playwright):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 800},
    )
    page = context.new_page()
    try:
        page.goto(url, wait_until="networkidle", timeout=60000)
        try:
            page.wait_for_selector("table, .filing, .documents, #filings", timeout=15000)
        except PWTimeout:
            pass
        return page.content()
    except Exception as e:
        print(f"  Playwright error: {e}")
        return None
    finally:
        browser.close()


def parse_filings(html, charity_label):
    soup = BeautifulSoup(html, "html.parser")

    charity_name = charity_label
    for selector in ["h1", "h2", ".org-name", ".charity-name", "title"]:
        el = soup.select_one(selector)
        if el:
            text = el.get_text(strip=True)
            if text and text.lower() not in ("", "registry search", "ca doj registry"):
                charity_name = text
                break

    filings = {}
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
        filing_keywords = {"filing", "form", "year", "date", "document", "type", "fiscal", "rrf", "990"}
        if not any(kw in " ".join(headers) for kw in filing_keywords):
            continue
        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            row_text = [c.get_text(strip=True) for c in cells]
            if not any(row_text):
                continue
            row_key = hashlib.md5("|".join(row_text).encode()).hexdigest()
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

    if not filings:
        for el in soup.find_all(["li", "div", "p"]):
            text = el.get_text(strip=True)
            if len(text) > 20 and any(
                kw in text.lower() for kw in ["990", "rrf", "filing", "annual report", "form ct"]
            ):
                key = hashlib.md5(text.encode()).hexdigest()
                filings[key] = {"cells": [text], "headers": [], "doc_url": None, "raw": text}

    return filings, charity_name


def format_filing_for_discord(filing_info):
    headers = filing_info.get("headers", [])
    cells = filing_info.get("cells", [])
    if headers and len(headers) == len(cells):
        parts = [f"**{h.title()}:** {v}" for h, v in zip(headers, cells) if h and v]
        return "\n".join(parts) if parts else filing_info["raw"]
    return filing_info["raw"]


def send_discord_notification(charity_name, charity_url, new_filings):
    if not DISCORD_WEBHOOK_URL:
        print("ERROR: DISCORD_WEBHOOK_URL not set.")
        return False

    count = len(new_filings)
    plural = "filing" if count == 1 else "filings"
    embeds = []
    for i, (_, info) in enumerate(new_filings.items()):
        if i >= 10:
            break
        description = format_filing_for_discord(info)
        if len(description) > 1024:
            description = description[:1021] + "..."
        embed = {"description": description, "color": 0x003366}
        if info.get("doc_url"):
            embed["url"] = info["doc_url"]
            embed["title"] = "📄 View Document"
        embeds.append(embed)

    payload = {
        "username": "CA AG Filing Monitor",
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
        ] + embeds,
    }

    resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
    if resp.status_code in (200, 204):
        print(f"  ✅ Discord notified: {count} new {plural} for {charity_name}")
        return True
    else:
        print(f"  ❌ Discord webhook failed: {resp.status_code} {resp.text}")
        return False


def send_error_notification(message):
    if not DISCORD_WEBHOOK_URL:
        return
    payload = {
        "username": "CA AG Filing Monitor",
        "embeds": [{"title": "⚠️ Monitor Error", "description": message, "color": 0xFF0000,
                    "footer": {"text": "CA AG Charity Filing Monitor"}}],
    }
    requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)


def main():
    print(f"🔍 CA AG Filing Monitor — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    state = load_state()
    any_errors = False

    with sync_playwright() as playwright:
        for charity in CHARITIES:
            cid = charity["id"]
            label = charity["label"]
            url = charity["url"]

            print(f"\n📋 Checking {label} ({cid[:8]}...)")
            html = fetch_page_playwright(url, playwright)

            if html is None:
                msg = f"Failed to fetch page for {label}:\n{url}"
                print(f"  ❌ {msg}")
                send_error_notification(msg)
                any_errors = True
                continue

            filings, charity_name = parse_filings(html, label)
            print(f"  Found {len(filings)} filing entries for: {charity_name}")

            previous_keys = set(state.get(cid, {}).get("filing_keys", []))
            current_keys = set(filings.keys())
            new_keys = current_keys - previous_keys

            if not previous_keys:
                print(f"  ℹ️  First run — saving baseline ({len(current_keys)} entries). No notification sent.")
            elif new_keys:
                print(f"  🆕 {len(new_keys)} new filing(s) detected!")
                send_discord_notification(charity_name, url, {k: filings[k] for k in new_keys})
            else:
                print(f"  ✅ No new filings.")

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
