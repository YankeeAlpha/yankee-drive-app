#!/usr/bin/env python3
"""
Yankee Drive - Google Business Profile Manager (Google Moja Firma - Yankee Drive Autodetailing)
Supports reading and updating the Google Business Profile (locations/18051088391378444532),
auto-refreshing tokens via OAuth Playground or Google OAuth2, and managing services/description/hours.
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


def refresh_google_access_token():
    load_env()
    cid = os.environ.get("GOOGLE_CLIENT_ID", "")
    csec = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    rtok = os.environ.get("GOOGLE_REFRESH_TOKEN", "")
    if cid and csec and rtok:
        data = urllib.parse.urlencode({
            "client_id": cid,
            "client_secret": csec,
            "refresh_token": rtok,
            "grant_type": "refresh_token",
        }).encode("utf-8")
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            res = json.loads(resp.read().decode("utf-8"))
        token = res["access_token"]
        save_env_vars({"GOOGLE_ACCESS_TOKEN": token})
        os.environ["GOOGLE_ACCESS_TOKEN"] = token
        return token
    if rtok:
        req = urllib.request.Request(
            "https://developers.google.com/oauthplayground/refreshAccessToken",
            data=json.dumps({"token_uri": "https://oauth2.googleapis.com/token", "refresh_token": rtok}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            res = json.loads(resp.read().decode("utf-8"))
        token = res.get("access_token")
        if token:
            save_env_vars({"GOOGLE_ACCESS_TOKEN": token})
            os.environ["GOOGLE_ACCESS_TOKEN"] = token
            return token
    raise RuntimeError("Nepodarilo sa obnoviť GOOGLE_ACCESS_TOKEN.")


def gbp_request(method, url, body=None):
    load_env()
    token = os.environ.get("GOOGLE_ACCESS_TOKEN") or refresh_google_access_token()

    def _do_req(tok):
        headers = {
            "Authorization": f"Bearer {tok}",
            "Accept": "application/json",
        }
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=req_headers if False else headers, method=method.upper())
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))

    try:
        return _do_req(token)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            token = refresh_google_access_token()
            return _do_req(token)
        err = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Google Business API chyba ({e.code}): {err}")


def get_profile():
    load_env()
    loc_name = os.environ.get("GOOGLE_GBP_LOCATION", "locations/18051088391378444532")
    mask = "name,title,phoneNumbers,categories,storefrontAddress,websiteUri,regularHours,specialHours,profile,metadata,serviceItems"
    return gbp_request("GET", f"https://mybusinessbusinessinformation.googleapis.com/v1/{loc_name}?readMask={mask}")


def main():
    parser = argparse.ArgumentParser(description="Yankee Drive - Google Business Profile Manager")
    sub = parser.add_subparsers(dest="command", required=True)

    # accounts
    sub.add_parser("accounts", help="Zobraziť Google Business účty a prevádzku Yankee Drive")

    # profile
    sub.add_parser("profile", help="Zobraziť kompletný profil prevádzky Yankee Drive Autodetailing na Google")

    # update-description
    p_desc = sub.add_parser("update-description", help="Aktualizovať popis firmy na Google Moja Firma (po odsúhlasení!)")
    p_desc.add_argument("--description", required=True, help="Nový popis prevádzky (max 750 znakov)")

    # update-service-price
    p_srv = sub.add_parser("update-service", help="Pridať alebo upraviť službu v zozname služieb na Google Moja Firma")
    p_srv.add_argument("--name", required=True, help="Názov služby (napr. Yankee Exclusive)")
    p_srv.add_argument("--description", required=True, help="Popis služby")
    p_srv.add_argument("--price-eur", type=float, default=None, help="Cena v EUR (voliteľné)")

    args = parser.parse_args()
    load_env()

    try:
        if args.command == "accounts":
            acc_res = gbp_request("GET", "https://mybusinessaccountmanagement.googleapis.com/v1/accounts")
            accounts = acc_res.get("accounts", [])
            locations = []
            for a in accounts:
                acc_name = a["name"]
                loc_res = gbp_request(
                    "GET",
                    f"https://mybusinessbusinessinformation.googleapis.com/v1/{acc_name}/locations?readMask=name,title,storefrontAddress,websiteUri,phoneNumbers",
                )
                for loc in loc_res.get("locations", []):
                    locations.append({"account": acc_name, "location": loc})
                    save_env_vars({"GOOGLE_GBP_ACCOUNT": acc_name, "GOOGLE_GBP_LOCATION": loc["name"]})
            print(json.dumps({"accounts": accounts, "locations": locations}, indent=2, ensure_ascii=False))
        elif args.command == "profile":
            print(json.dumps(get_profile(), indent=2, ensure_ascii=False))
        elif args.command == "update-description":
            loc_name = os.environ.get("GOOGLE_GBP_LOCATION", "locations/18051088391378444532")
            res = gbp_request(
                "PATCH",
                f"https://mybusinessbusinessinformation.googleapis.com/v1/{loc_name}?updateMask=profile.description",
                body={"profile": {"description": args.description}},
            )
            print(json.dumps(res, indent=2, ensure_ascii=False))
        elif args.command == "update-service":
            loc_name = os.environ.get("GOOGLE_GBP_LOCATION", "locations/18051088391378444532")
            prof = get_profile()
            items = prof.get("serviceItems", [])
            updated = False
            for it in items:
                ff = it.get("freeFormServiceItem")
                if ff and ff.get("label", {}).get("displayName", "").lower() == args.name.lower():
                    ff["label"]["description"] = args.description
                    if args.price_eur is not None:
                        units = int(args.price_eur)
                        nanos = int(round((args.price_eur - units) * 1e9))
                        it["price"] = {"currencyCode": "EUR", "units": str(units), "nanos": nanos}
                    updated = True
                    break
            if not updated:
                new_item = {
                    "freeFormServiceItem": {
                        "category": "categories/gcid:car_detailing_service",
                        "label": {"displayName": args.name, "description": args.description},
                    }
                }
                if args.price_eur is not None:
                    units = int(args.price_eur)
                    nanos = int(round((args.price_eur - units) * 1e9))
                    new_item["price"] = {"currencyCode": "EUR", "units": str(units), "nanos": nanos}
                items.append(new_item)
            res = gbp_request(
                "PATCH",
                f"https://mybusinessbusinessinformation.googleapis.com/v1/{loc_name}?updateMask=serviceItems",
                body={"serviceItems": items},
            )
            print(json.dumps(res, indent=2, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, indent=2, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
