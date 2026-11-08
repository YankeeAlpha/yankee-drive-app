#!/usr/bin/env python3
"""
Yankee Drive - Meta Manager (Facebook Page, Instagram Business @yankee_drive, WhatsApp Business)
Uses Meta Graph API v21.0 over HTTPS.
"""

import argparse
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
GRAPH_BASE = "https://graph.facebook.com/v21.0"


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
    lines = ["# Konfigurácia pre Yankee Drive (Zoho Mail, Welcomio, Meta & Google Business)"]
    for k, v in env_map.items():
        lines.append(f"{k}={v}")
    lines.append("")
    ENV_FILE.write_text("\n".join(lines), encoding="utf-8")


def graph_request(method, path, params=None, body=None, token=None):
    load_env()
    token = token or os.environ.get("META_PAGE_ACCESS_TOKEN") or os.environ.get("META_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("Chýba META_ACCESS_TOKEN v .env. Spustite 'meta_manager.py auth --token ...'")
    query = dict(params or {})
    query["access_token"] = token
    url = f"{GRAPH_BASE}/{path.lstrip('/')}?{urllib.parse.urlencode(query)}"
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Meta Graph API chyba ({e.code}): {err_body}")


def setup_auth(token, app_id=None, app_secret=None, wa_phone_id=None):
    load_env()
    updates = {"META_ACCESS_TOKEN": token}
    if app_id:
        updates["META_APP_ID"] = app_id
    if app_secret:
        updates["META_APP_SECRET"] = app_secret

    # Optional: Exchange short-lived user token for long-lived user token if app_id & app_secret provided
    if app_id and app_secret:
        try:
            res = graph_request(
                "GET",
                "/oauth/access_token",
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": app_id,
                    "client_secret": app_secret,
                    "fb_exchange_token": token,
                },
                token=token,
            )
            if "access_token" in res:
                token = res["access_token"]
                updates["META_ACCESS_TOKEN"] = token
        except Exception:
            pass

    # Discover Facebook Pages & connected Instagram Business Account
    pages_res = graph_request(
        "GET",
        "/me/accounts",
        params={"fields": "id,name,access_token,instagram_business_account{id,username,name,followers_count,media_count}"},
        token=token,
    )
    pages = pages_res.get("data", [])
    selected_page = None
    if pages:
        selected_page = pages[0]
        for p in pages:
            if "yankee" in (p.get("name") or "").lower():
                selected_page = p
                break
        updates["META_PAGE_ID"] = selected_page["id"]
        updates["META_PAGE_NAME"] = selected_page.get("name", "")
        if selected_page.get("access_token"):
            updates["META_PAGE_ACCESS_TOKEN"] = selected_page["access_token"]
        ig = selected_page.get("instagram_business_account")
        if ig and ig.get("id"):
            updates["META_IG_USER_ID"] = ig["id"]
            updates["META_IG_USERNAME"] = ig.get("username", "")

    if wa_phone_id:
        updates["META_WA_PHONE_ID"] = wa_phone_id

    save_env_vars(updates)
    return {
        "ok": True,
        "pages_found": len(pages),
        "selected_page": {
            "id": updates.get("META_PAGE_ID"),
            "name": updates.get("META_PAGE_NAME"),
            "instagram": selected_page.get("instagram_business_account") if selected_page else None,
        },
        "whatsapp_phone_id": updates.get("META_WA_PHONE_ID", os.environ.get("META_WA_PHONE_ID", "")),
    }


def main():
    parser = argparse.ArgumentParser(description="Yankee Drive - Meta Manager (FB, IG, WhatsApp)")
    sub = parser.add_subparsers(dest="command", required=True)

    # auth
    p_auth = sub.add_parser("auth", help="Uložiť Meta Access Token a automaticky načítať FB Page, IG a WhatsApp ID")
    p_auth.add_argument("--token", required=True, help="Meta User alebo Page Access Token")
    p_auth.add_argument("--app-id", default=None, help="Voliteľné Meta App ID pre trvalý token")
    p_auth.add_argument("--app-secret", default=None, help="Voliteľný Meta App Secret pre trvalý token")
    p_auth.add_argument("--wa-phone-id", default=None, help="Voliteľné WhatsApp Phone Number ID")

    # status
    sub.add_parser("status", help="Zobraziť stav prepojenia Facebook Page, Instagramu a WhatsAppu")

    # fb-posts
    p_fb_list = sub.add_parser("fb-posts", help="Zobraziť posledné príspevky na Facebook stránke Yankee Drive")
    p_fb_list.add_argument("--limit", type=int, default=5)

    # fb-publish
    p_fb_pub = sub.add_parser("fb-publish", help="Publikovať príspevok na Facebook stránku (iba po odsúhlasení!)")
    p_fb_pub.add_argument("--message", required=True, help="Text príspevku")
    p_fb_pub.add_argument("--link", default=None, help="Voliteľný odkaz")
    p_fb_pub.add_argument("--photo-url", default=None, help="Voliteľná verejná URL fotky")

    # ig-media
    p_ig_list = sub.add_parser("ig-media", help="Zobraziť posledné príspevky na Instagrame @yankee_drive")
    p_ig_list.add_argument("--limit", type=int, default=5)

    # ig-publish
    p_ig_pub = sub.add_parser("ig-publish", help="Publikovať fotku s popisom na Instagram @yankee_drive (po odsúhlasení!)")
    p_ig_pub.add_argument("--image-url", required=True, help="Verejná URL obrázka (JPEG/PNG)")
    p_ig_pub.add_argument("--caption", required=True, help="Popis príspevku vrátane hashtagov")

    # wa-send
    p_wa = sub.add_parser("wa-send", help="Odoslať WhatsApp správu zákazníkovi cez WhatsApp Cloud API (po odsúhlasení!)")
    p_wa.add_argument("--to", required=True, help="Telefónne číslo v medzinárodnom formáte (napr. 421940247133)")
    p_wa.add_argument("--text", required=True, help="Text WhatsApp správy")

    args = parser.parse_args()
    load_env()

    try:
        if args.command == "auth":
            print(json.dumps(setup_auth(args.token, args.app_id, args.app_secret, args.wa_phone_id), indent=2, ensure_ascii=False))
        elif args.command == "status":
            page_id = os.environ.get("META_PAGE_ID")
            ig_id = os.environ.get("META_IG_USER_ID")
            wa_id = os.environ.get("META_WA_PHONE_ID")
            info = {"ok": True, "facebook_page": None, "instagram": None, "whatsapp_phone_id": wa_id}
            if page_id:
                info["facebook_page"] = graph_request("GET", f"/{page_id}", params={"fields": "id,name,fan_count,followers_count,link"})
            if ig_id:
                info["instagram"] = graph_request("GET", f"/{ig_id}", params={"fields": "id,username,name,followers_count,media_count"})
            print(json.dumps(info, indent=2, ensure_ascii=False))
        elif args.command == "fb-posts":
            page_id = os.environ.get("META_PAGE_ID")
            if not page_id:
                raise RuntimeError("Chýba META_PAGE_ID v .env.")
            res = graph_request("GET", f"/{page_id}/posts", params={"fields": "id,message,created_time,permalink_url", "limit": args.limit})
            print(json.dumps(res.get("data", []), indent=2, ensure_ascii=False))
        elif args.command == "fb-publish":
            page_id = os.environ.get("META_PAGE_ID")
            if not page_id:
                raise RuntimeError("Chýba META_PAGE_ID v .env.")
            if args.photo_url:
                res = graph_request("POST", f"/{page_id}/photos", body={"url": args.photo_url, "caption": args.message})
            else:
                payload = {"message": args.message}
                if args.link:
                    payload["link"] = args.link
                res = graph_request("POST", f"/{page_id}/feed", body=payload)
            print(json.dumps(res, indent=2, ensure_ascii=False))
        elif args.command == "ig-media":
            ig_id = os.environ.get("META_IG_USER_ID")
            if not ig_id:
                raise RuntimeError("Chýba META_IG_USER_ID v .env.")
            res = graph_request(
                "GET",
                f"/{ig_id}/media",
                params={"fields": "id,caption,media_type,media_url,permalink,timestamp,like_count,comments_count", "limit": args.limit},
            )
            print(json.dumps(res.get("data", []), indent=2, ensure_ascii=False))
        elif args.command == "ig-publish":
            ig_id = os.environ.get("META_IG_USER_ID")
            if not ig_id:
                raise RuntimeError("Chýba META_IG_USER_ID v .env.")
            container = graph_request("POST", f"/{ig_id}/media", body={"image_url": args.image_url, "caption": args.caption})
            creation_id = container["id"]
            published = graph_request("POST", f"/{ig_id}/media_publish", body={"creation_id": creation_id})
            print(json.dumps(published, indent=2, ensure_ascii=False))
        elif args.command == "wa-send":
            wa_id = os.environ.get("META_WA_PHONE_ID")
            if not wa_id:
                raise RuntimeError("Chýba META_WA_PHONE_ID v .env.")
            clean_phone = "".join(ch for ch in args.to if ch.isdigit())
            res = graph_request(
                "POST",
                f"/{wa_id}/messages",
                body={
                    "messaging_product": "whatsapp",
                    "to": clean_phone,
                    "type": "text",
                    "text": {"preview_url": True, "body": args.text},
                },
                token=os.environ.get("META_ACCESS_TOKEN"),
            )
            print(json.dumps(res, indent=2, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, indent=2, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
