# Dodge Social Auto-Poster

Zero-cost GitHub Actions pipeline to automatically rotate and publish Dodge browser game updates (`https://dodge.saas-build09.workers.dev`) to **Bluesky**, **Discord**, and **X (Twitter)**.

## Features
- **Bluesky ATProto**: Clickable URL and hashtag facets plus optional image attachment from `media/`.
- **Discord Webhooks**: Rich embeds with optional `.mp4`/`.gif`/`.png` clip attachments.
- **X API v2 (OAuth 1.0a)**: Link-free main post followed by an automatic link self-reply, protected by a monthly post cap (`X_MONTHLY_CAP`, default `40`).
- **Sequential Queue Rotation**: Persists `scripts/state.json` after each run so posts rotate cleanly without duplicates.
- **Safe Dry-Run Mode**: Run `python3 scripts/autopost.py --dry-run` locally (including Termux / Pydroid 3) or trigger `workflow_dispatch` with `dry_run: true`.

## Setup
1. Go to **Settings -> Secrets and variables -> Actions** and add secrets for the platforms you want active (any missing platform is skipped automatically):
   - **Bluesky**: `BSKY_HANDLE`, `BSKY_APP_PASSWORD`
   - **Discord**: `DISCORD_WEBHOOK_URL`
   - **X (Twitter)**: `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_SECRET`, and optional `X_MONTHLY_CAP`
2. Add your gameplay clip(s) to `media/` (matching the `media` path in `scripts/posts_queue.json`).
3. Run the **Dodge Social Auto-Poster** workflow manually from the **Actions** tab with `dry_run: true` first, then run live or let the 3-day schedule handle it.
