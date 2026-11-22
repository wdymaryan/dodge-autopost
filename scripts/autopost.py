#!/usr/bin/env python3
"""Dodge Social Auto-Poster — Bluesky ATProto, Discord Webhooks, and X API v2."""

import argparse
import json
import mimetypes
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
try:
    from requests_oauthlib import OAuth1
except ImportError:
    OAuth1 = None

GAME_URL = os.getenv("GAME_URL", "https://dodge.saas-build09.workers.dev")
DEV_HANDLE = os.getenv("DEV_HANDLE", "@DodgeGameDev")

ENABLE_BSKY = True
ENABLE_DISCORD = True
ENABLE_X = True

QUEUE_PATH = Path("scripts/posts_queue.json")
STATE_PATH = Path("scripts/state.json")


def utc_iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def build_bsky_facets(text: str) -> list:
    """Create ATProto byte-indexed facets so URLs and #hashtags are clickable."""
    facets = []
    for m in re.finditer(r"https?://\S+", text):
        b_start = len(text[: m.start()].encode("utf-8"))
        b_end = len(text[: m.end()].encode("utf-8"))
        facets.append({
            "index": {"byteStart": b_start, "byteEnd": b_end},
            "features": [{"$type": "app.bsky.richtext.facet#link", "uri": m.group(0)}],
        })
    for m in re.finditer(r"(?:^|\s)(#[A-Za-z0-9_]+)", text):
        tag = m.group(1)
        t_start = m.start(1)
        b_start = len(text[:t_start].encode("utf-8"))
        b_end = len(text[: t_start + len(tag)].encode("utf-8"))
        facets.append({
            "index": {"byteStart": b_start, "byteEnd": b_end},
            "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": tag.lstrip("#")}],
        })
    return facets


def post_to_bluesky(post: dict, dry_run: bool) -> bool:
    handle = os.getenv("BSKY_HANDLE", "").strip()
    app_pwd = os.getenv("BSKY_APP_PASSWORD", "").strip()
    if not handle or not app_pwd:
        print("Skipping Bluesky: BSKY_HANDLE or BSKY_APP_PASSWORD not set.")
        return False

    body = f"{post['main']}\n\nPlay: {GAME_URL}"
    if len(body) > 300:
        body = body[:297] + "..."

    if dry_run:
        print(f"[DRY RUN] Bluesky ({len(body)} chars):\n{body}")
        return True

    sess = requests.post(
        "https://bsky.social/xrpc/com.atproto.server.createSession",
        json={"identifier": handle, "password": app_pwd},
        timeout=15,
    )
    sess.raise_for_status()
    token = sess.json()["accessJwt"]
    did = sess.json()["did"]
    headers = {"Authorization": f"Bearer {token}"}

    record = {
        "$type": "app.bsky.feed.post",
        "text": body,
        "facets": build_bsky_facets(body),
        "createdAt": utc_iso_now(),
    }

    media_file = Path(post.get("media", ""))
    if media_file.is_file():
        mime = mimetypes.guess_type(str(media_file))[0] or "application/octet-stream"
        if mime.startswith("image/"):
            up = requests.post(
                "https://bsky.social/xrpc/com.atproto.repo.uploadBlob",
                headers={**headers, "Content-Type": mime},
                data=media_file.read_bytes(),
                timeout=30,
            )
            up.raise_for_status()
            record["embed"] = {
                "$type": "app.bsky.embed.images",
                "images": [{"alt": "Dodge gameplay clip", "image": up.json()["blob"]}],
            }

    res = requests.post(
        "https://bsky.social/xrpc/com.atproto.repo.createRecord",
        headers=headers,
        json={"repo": did, "collection": "app.bsky.feed.post", "record": record},
        timeout=15,
    )
    res.raise_for_status()
    print("Published to Bluesky.")
    return True


def post_to_discord(post: dict, dry_run: bool) -> bool:
    webhook = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        print("Skipping Discord: DISCORD_WEBHOOK_URL not set.")
        return False

    payload = {
        "username": "Dodge Game Announcer",
        "embeds": [{
            "title": f"Dodge — {post.get('angle', 'Update')}",
            "description": post["main"],
            "color": 1096065,
            "fields": [
                {"name": "Play Instantly", "value": f"[Play Dodge]({GAME_URL})", "inline": True},
                {"name": "Dev", "value": DEV_HANDLE, "inline": True},
            ],
        }],
    }

    if dry_run:
        print(f"[DRY RUN] Discord embed: {json.dumps(payload)}")
        return True

    media_file = Path(post.get("media", ""))
    if media_file.is_file():
        mime = mimetypes.guess_type(str(media_file))[0] or "application/octet-stream"
        with media_file.open("rb") as fh:
            res = requests.post(
                webhook,
                data={"payload_json": json.dumps(payload)},
                files={"file": (media_file.name, fh, mime)},
                timeout=30,
            )
    else:
        res = requests.post(webhook, json=payload, timeout=15)

    res.raise_for_status()
    print("Published to Discord.")
    return True


def post_to_x(post: dict, state: dict, dry_run: bool) -> bool:
    api_key = os.getenv("X_API_KEY", "").strip()
    api_secret = os.getenv("X_API_SECRET", "").strip()
    access_token = os.getenv("X_ACCESS_TOKEN", "").strip()
    access_secret = os.getenv("X_ACCESS_SECRET", "").strip()
    if not all([api_key, api_secret, access_token, access_secret]):
        print("Skipping X: OAuth 1.0a secrets not set.")
        return False
    if OAuth1 is None:
        print("Skipping X: requests-oauthlib not installed.")
        return False

    cap = int(os.getenv("X_MONTHLY_CAP", "40") or "40")
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    if state.get("month") != month:
        state["month"] = month
        state["x_posts_this_month"] = 0

    if state.get("x_posts_this_month", 0) + 2 > cap:
        print(f"Skipping X: monthly cap ({cap}) reached.")
        return False

    main_text = post["main"][:280]
    reply_text = post.get("reply", f"Play in your browser: {GAME_URL}")[:280]

    if dry_run:
        print(f"[DRY RUN] X main ({len(main_text)} chars):\n{main_text}")
        print(f"[DRY RUN] X self-reply:\n{reply_text}")
        return True

    auth = OAuth1(api_key, api_secret, access_token, access_secret)
    r1 = requests.post(
        "https://api.twitter.com/2/tweets",
        auth=auth,
        json={"text": main_text},
        timeout=15,
    )
    r1.raise_for_status()
    tweet_id = r1.json()["data"]["id"]

    r2 = requests.post(
        "https://api.twitter.com/2/tweets",
        auth=auth,
        json={"text": reply_text, "reply": {"in_reply_to_tweet_id": tweet_id}},
        timeout=15,
    )
    r2.raise_for_status()
    state["x_posts_this_month"] = state.get("x_posts_this_month", 0) + 2
    print(f"Published X thread (main {tweet_id} + link self-reply).")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Dodge Social Auto-Poster")
    parser.add_argument("--dry-run", action="store_true", help="Log actions without posting")
    args = parser.parse_args()
    dry_run = args.dry_run or os.getenv("DRY_RUN", "false").lower() == "true"

    posts = load_json(QUEUE_PATH, [])
    if not posts:
        raise SystemExit("scripts/posts_queue.json is empty.")

    state = load_json(STATE_PATH, {"next_index": 0, "x_posts_this_month": 0, "month": "", "last_run_utc": None})
    idx = state.get("next_index", 0) % len(posts)
    post = posts[idx]
    print(f"Running Dodge Auto-Poster | angle={post.get('angle')} | index={idx} | dry_run={dry_run}")

    posted_any = False
    if ENABLE_BSKY:
        posted_any = post_to_bluesky(post, dry_run) or posted_any
    if ENABLE_DISCORD:
        posted_any = post_to_discord(post, dry_run) or posted_any
    if ENABLE_X:
        posted_any = post_to_x(post, state, dry_run) or posted_any

    if not dry_run and posted_any:
        state["next_index"] = (idx + 1) % len(posts)
        state["last_run_utc"] = utc_iso_now()
        save_json(STATE_PATH, state)
        print(f"Updated state.json -> next_index={state['next_index']}")
    print("Done.")


if __name__ == "__main__":
    main()
