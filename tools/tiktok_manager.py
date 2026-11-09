#!/usr/bin/env python3
"""
Yankee Drive - TikTok Manager (@yankeedrive)
Oficiálne prepojenie cez TikTok API v2 (OAuth2, profilové štatistiky, zoznam videí,
publikovanie Photo Mode príspevkov a nahrávanie videí/konceptov do TikTok Inboxu).
"""

import argparse
import hashlib
import base64
import json
import os
from pathlib import Path
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
REDIRECT_URI = "https://yankeealpha.github.io/yankee-drive-app/tiktok-callback.html"
TIKTOK_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TIKTOK_API_BASE = "https://open.tiktokapis.com/v2"


def load_env():
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


def save_env_vars(updates):
    env_map = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env_map[k.strip()] = v.strip()
    env_map.update(updates)
    lines = ["# Konfigurácia pre Yankee Drive"]
    for k, v in env_map.items():
        lines.append(f"{k}={v}")
    lines.append("")
    ENV_FILE.write_text("\n".join(lines), encoding="utf-8")


def api_request(method, url, headers=None, data=None):
    req_headers = {"User-Agent": "YankeeDriveAssistant/1.0"}
    if headers:
        req_headers.update(headers)
    body = data.encode("utf-8") if isinstance(data, str) else data
    req = urllib.request.Request(url, data=body, headers=req_headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return r.status, json.loads(raw) if raw.strip().startswith("{") else raw
    except urllib.error.HTTPError as e:
        err_text = e.read().decode("utf-8", errors="replace")
        try:
            err_json = json.loads(err_text)
        except Exception:
            err_json = {"raw_error": err_text}
        return e.code, err_json


def get_valid_access_token():
    load_env()
    token = os.environ.get("TIKTOK_ACCESS_TOKEN", "")
    if token:
        return token
    raise RuntimeError("Chýba TIKTOK_ACCESS_TOKEN. Spustite najprv 'auth-url' a 'auth-token'.")


def refresh_access_token():
    load_env()
    client_key = os.environ.get("TIKTOK_CLIENT_KEY", "")
    client_secret = os.environ.get("TIKTOK_CLIENT_SECRET", "")
    refresh_token = os.environ.get("TIKTOK_REFRESH_TOKEN", "")
    if not (client_key and client_secret and refresh_token):
        raise RuntimeError("Chýbajú údaje TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET alebo TIKTOK_REFRESH_TOKEN.")

    form = urllib.parse.urlencode({
        "client_key": client_key,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    })
    status, resp = api_request(
        "POST",
        f"{TIKTOK_API_BASE}/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=form,
    )
    if status == 200 and isinstance(resp, dict) and resp.get("access_token"):
        save_env_vars({
            "TIKTOK_ACCESS_TOKEN": resp["access_token"],
            "TIKTOK_REFRESH_TOKEN": resp.get("refresh_token", refresh_token),
            "TIKTOK_OPEN_ID": resp.get("open_id", os.environ.get("TIKTOK_OPEN_ID", "")),
        })
        return resp
    raise RuntimeError(f"Obnova TikTok tokenu zlyhala ({status}): {resp}")


def cmd_auth_url(client_key, client_secret, scopes):
    load_env()
    ck = client_key or os.environ.get("TIKTOK_CLIENT_KEY", "")
    cs = client_secret or os.environ.get("TIKTOK_CLIENT_SECRET", "")
    if not ck:
        raise RuntimeError("Zadajte --client-key (z developers.tiktok.com).")

    code_verifier = secrets.token_urlsafe(48)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode("ascii")).digest()
    ).decode("ascii").rstrip("=")

    updates = {"TIKTOK_CLIENT_KEY": ck, "TIKTOK_CODE_VERIFIER": code_verifier}
    if cs:
        updates["TIKTOK_CLIENT_SECRET"] = cs
    save_env_vars(updates)

    params = {
        "client_key": ck,
        "response_type": "code",
        "scope": scopes,
        "redirect_uri": REDIRECT_URI,
        "state": "yankeedrive_tiktok",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    url = f"{TIKTOK_AUTH_URL}?{urllib.parse.urlencode(params)}"
    return {
        "ok": True,
        "redirect_uri": REDIRECT_URI,
        "authorize_url": url,
        "instructions": "Otvorte authorize_url v prehliadači, potvrďte prístup pre @yankeedrive a skopírujte výsledný kód.",
    }


def cmd_auth_token(code):
    load_env()
    ck = os.environ.get("TIKTOK_CLIENT_KEY", "")
    cs = os.environ.get("TIKTOK_CLIENT_SECRET", "")
    verifier = os.environ.get("TIKTOK_CODE_VERIFIER", "")
    if not (ck and cs):
        raise RuntimeError("Chýba TIKTOK_CLIENT_KEY alebo TIKTOK_CLIENT_SECRET.")

    clean_code = urllib.parse.unquote(code.strip())
    payload = {
        "client_key": ck,
        "client_secret": cs,
        "code": clean_code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    }
    if verifier:
        payload["code_verifier"] = verifier

    form = urllib.parse.urlencode(payload)
    status, resp = api_request(
        "POST",
        f"{TIKTOK_API_BASE}/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=form,
    )
    if status == 200 and isinstance(resp, dict) and resp.get("access_token"):
        save_env_vars({
            "TIKTOK_ACCESS_TOKEN": resp["access_token"],
            "TIKTOK_REFRESH_TOKEN": resp.get("refresh_token", ""),
            "TIKTOK_OPEN_ID": resp.get("open_id", ""),
        })
        return {"ok": True, "token_data": resp}
    raise RuntimeError(f"Výmena kódu za token zlyhala ({status}): {resp}")


def cmd_status():
    token = get_valid_access_token()
    fields = "open_id,union_id,avatar_url,display_name,bio_description,profile_deep_link,is_verified,follower_count,following_count,likes_count,video_count"
    status, resp = api_request(
        "GET",
        f"{TIKTOK_API_BASE}/user/info/?fields={fields}",
        headers={"Authorization": f"Bearer {token}"},
    )
    if status == 401:
        refreshed = refresh_access_token()
        token = refreshed["access_token"]
        status, resp = api_request(
            "GET",
            f"{TIKTOK_API_BASE}/user/info/?fields={fields}",
            headers={"Authorization": f"Bearer {token}"},
        )
    return {"status_code": status, "response": resp}


def cmd_publish_photo(image_urls, title, description, draft=True):
    token = get_valid_access_token()
    post_mode = "MEDIA_UPLOAD" if draft else "DIRECT_POST"
    body = {
        "post_info": {
            "title": title[:90],
            "description": description[:4000],
            "privacy_level": "PUBLIC_TO_EVERYONE",
            "disable_comment": False,
            "auto_add_music": True,
        },
        "source_info": {
            "source": "PULL_FROM_URL",
            "photo_cover_index": 0,
            "photo_images": image_urls,
        },
        "post_mode": post_mode,
        "media_type": "PHOTO",
    }
    if draft:
        body["post_info"] = {"title": title[:90], "description": description[:4000]}
    status, resp = api_request(
        "POST",
        f"{TIKTOK_API_BASE}/post/publish/content/init/",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        data=json.dumps(body),
    )
    return {"status_code": status, "post_mode": post_mode, "response": resp}


def cmd_publish_video(video_url, title, draft=True):
    token = get_valid_access_token()
    endpoint = "/post/publish/inbox/video/init/" if draft else "/post/publish/video/init/"
    body = {
        "source_info": {
            "source": "PULL_FROM_URL",
            "video_url": video_url,
        }
    }
    if not draft:
        body["post_info"] = {
            "title": title[:2200],
            "privacy_level": "PUBLIC_TO_EVERYONE",
            "disable_duet": False,
            "disable_comment": False,
            "disable_stitch": False,
        }
    status, resp = api_request(
        "POST",
        f"{TIKTOK_API_BASE}{endpoint}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        data=json.dumps(body),
    )
    return {"status_code": status, "draft_inbox": draft, "response": resp}


def main():
    parser = argparse.ArgumentParser(description="Yankee Drive - TikTok Manager (@yankeedrive)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_url = sub.add_parser("auth-url", help="Vygenerovať prihlasovaciu TikTok OAuth2 URL")
    p_url.add_argument("--client-key", default=None, help="TikTok Client Key")
    p_url.add_argument("--client-secret", default=None, help="TikTok Client Secret")
    p_url.add_argument(
        "--scopes",
        default="user.info.basic,user.info.profile,user.info.stats,video.list,video.upload,video.publish",
        help="OAuth scopes",
    )

    p_tok = sub.add_parser("auth-token", help="Vymeniť autorizačný kód za Access Token")
    p_tok.add_argument("--code", required=True, help="Kód z tiktok-callback.html")

    sub.add_parser("status", help="Zobraziť informácie a štatistiky účtu @yankeedrive")
    sub.add_parser("refresh", help="Obnoviť platnosť Access Tokenu")

    p_photo = sub.add_parser("publish-photo", help="Publikovať fotku / karusel na TikTok")
    p_photo.add_argument("--images", nargs="+", required=True, help="Verejné URL obrázkov (JPEG/WEBP)")
    p_photo.add_argument("--title", default="Yankee Drive Autodetailing Trebišov", help="Nadpis")
    p_photo.add_argument("--description", required=True, help="Popis a hashtagy")
    p_photo.add_argument("--direct", action="store_true", help="Priame uverejnenie namiesto odoslania do TikTok Inboxu")

    p_vid = sub.add_parser("publish-video", help="Nahrať video na TikTok (do Inboxu alebo priamo)")
    p_vid.add_argument("--video-url", required=True, help="Verejná URL MP4 videa")
    p_vid.add_argument("--title", required=True, help="Popis videa a hashtagy")
    p_vid.add_argument("--direct", action="store_true", help="Priame uverejnenie namiesto Inboxu")

    args = parser.parse_args()
    try:
        if args.command == "auth-url":
            out = cmd_auth_url(args.client_key, args.client_secret, args.scopes)
        elif args.command == "auth-token":
            out = cmd_auth_token(args.code)
        elif args.command == "status":
            out = cmd_status()
        elif args.command == "refresh":
            out = refresh_access_token()
        elif args.command == "publish-photo":
            out = cmd_publish_photo(args.images, args.title, args.description, draft=not args.direct)
        elif args.command == "publish-video":
            out = cmd_publish_video(args.video_url, args.title, draft=not args.direct)
        print(json.dumps(out, indent=2, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, indent=2, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
