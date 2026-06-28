# CA Attorney General Filing Monitor 🔔

A GitHub Actions bot that monitors two CA Attorney General charity profiles for new filings and sends Discord notifications.

## Monitored Charities

| Label | Registry URL |
|-------|-------------|
| Charity 1 | [View Profile](https://rct.doj.ca.gov/Verification/Web/Details.aspx?result=add8a22f-3bcc-4f1f-9061-f3bdd2d2666b) |
| Charity 2 | [View Profile](https://rct.doj.ca.gov/Verification/Web/Details.aspx?result=b6573c8d-8fb8-4d17-98b8-f0424da5399a) |

---

## Setup

### 1. Create a GitHub Repository

Create a new **private** GitHub repo (recommended, since it will store filing state) and push this folder's contents to it:

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

---

### 2. Create a Discord Webhook

1. Open your Discord server → go to the channel where you want notifications.
2. Click **Edit Channel** (gear icon) → **Integrations** → **Webhooks** → **New Webhook**.
3. Give it a name (e.g. `CA AG Filing Monitor`) and click **Copy Webhook URL**.

---

### 3. Add the Webhook as a GitHub Secret

1. In your GitHub repo, go to **Settings** → **Secrets and variables** → **Actions**.
2. Click **New repository secret**.
3. Name: `DISCORD_WEBHOOK_URL`
4. Value: paste your Discord webhook URL.
5. Click **Add secret**.

---

### 4. Enable GitHub Actions

Go to the **Actions** tab in your repo and enable workflows if prompted.

---

### 5. Test It

Trigger a manual run:
1. Go to **Actions** → **CA AG Filing Monitor** → **Run workflow** → **Run workflow**.
2. Check the logs — on first run it will save a baseline and send **no notification** (nothing to compare against yet).
3. On the second run (or when a new filing appears), it will ping Discord.

---

## How It Works

```
Every 6 hours (via cron):
  For each charity URL:
    1. Fetch the CA AG detail page
    2. Parse all filing table rows
    3. Compare against previously seen filings (stored in GitHub Actions cache)
    4. If new rows found → send Discord embed with details
    5. Save updated state
```

- **First run:** saves a baseline snapshot. No Discord message is sent.
- **Subsequent runs:** any new filing rows trigger a Discord notification with the filing details and a direct link to the document (if available).

---

## Customization

### Change the check frequency

Edit `.github/workflows/monitor.yml` — the `cron` line:

```yaml
- cron: "0 */6 * * *"   # every 6 hours (default)
- cron: "0 */1 * * *"   # every hour
- cron: "0 9 * * *"     # once daily at 9am UTC
```

> ⚠️ GitHub Actions free tier has a limit of ~2,000 minutes/month. Hourly checks use ~720 min/month, which is fine.

### Add more charities

Edit `scripts/check_filings.py` and add entries to the `CHARITIES` list:

```python
CHARITIES = [
    ...
    {
        "id": "YOUR-GUID-HERE",
        "url": "https://rct.doj.ca.gov/Verification/Web/Details.aspx?result=YOUR-GUID-HERE",
        "label": "My New Charity",
    },
]
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| No Discord messages | Check that `DISCORD_WEBHOOK_URL` secret is set correctly |
| "Failed to fetch page" errors | CA AG site may be down or blocking; it will retry automatically next run |
| Always says "no new filings" | The site may render filings via JavaScript — see note below |

### ⚠️ JavaScript-rendered content note

The CA AG registry site may load filing data dynamically via JavaScript. If the bot consistently finds 0 filings, the page may require a headless browser. In that case, open an issue or swap `requests` + `BeautifulSoup` for `playwright` (a headless browser library). A `playwright`-based alternative is easy to drop in.
