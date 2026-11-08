#!/usr/bin/env python3
"""
Yankee Drive - Welcomio Web & Admin Manager (www.yankeedrive.sk / admin.welcomio.com)
Supports reading and managing the Welcomio admin panel via Laravel/Inertia JSON endpoints.
"""

import argparse
import html
import http.cookiejar
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
COOKIE_JSON = BASE_DIR / ".welcomio_cookies.json"
ADMIN_BASE = "https://admin.welcomio.com"
PUBLIC_URL = "https://www.yankeedrive.sk"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


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
    lines = ["# Konfigurácia pre Yankee Drive (Zoho Mail & Welcomio)"]
    for k, v in env_map.items():
        lines.append(f"{k}={v}")
    lines.append("")
    ENV_FILE.write_text("\n".join(lines), encoding="utf-8")


class WelcomioSession:
    def __init__(self):
        self.cj = http.cookiejar.CookieJar()
        self._load_cookies()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))

    def _load_cookies(self):
        if COOKIE_JSON.exists():
            try:
                items = json.loads(COOKIE_JSON.read_text(encoding="utf-8"))
                for c in items:
                    cookie = http.cookiejar.Cookie(
                        version=0,
                        name=c["name"],
                        value=c["value"],
                        port=None,
                        port_specified=False,
                        domain=c["domain"],
                        domain_specified=bool(c["domain"]),
                        domain_initial_dot=c["domain"].startswith("."),
                        path=c.get("path", "/"),
                        path_specified=True,
                        secure=c.get("secure", True),
                        expires=c.get("expires"),
                        discard=False,
                        comment=None,
                        comment_url=None,
                        rest={},
                        rfc2109=False,
                    )
                    self.cj.set_cookie(cookie)
            except Exception:
                pass

    def _save_cookies(self):
        items = []
        for c in self.cj:
            items.append({
                "name": c.name,
                "value": c.value,
                "domain": c.domain,
                "path": c.path,
                "secure": c.secure,
                "expires": c.expires,
            })
        COOKIE_JSON.write_text(json.dumps(items, indent=2), encoding="utf-8")

    def get_xsrf_token(self):
        for c in self.cj:
            if c.name == "XSRF-TOKEN":
                return urllib.parse.unquote(c.value)
        return ""

    def request(self, method, url, headers=None, data=None):
        req_headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html, application/xhtml+xml, application/json",
            "Accept-Language": "sk-SK,sk;q=0.9,en;q=0.8",
        }
        xsrf = self.get_xsrf_token()
        if xsrf:
            req_headers["X-XSRF-TOKEN"] = xsrf
        if headers:
            req_headers.update(headers)
        body_bytes = data.encode("utf-8") if isinstance(data, str) else data
        req = urllib.request.Request(url, data=body_bytes, headers=req_headers, method=method.upper())
        try:
            with self.opener.open(req, timeout=20) as resp:
                text = resp.read().decode("utf-8", errors="replace")
                final_url = resp.geturl()
                status = resp.status
        except urllib.error.HTTPError as e:
            status = e.code
            if status in (301, 302, 303, 307, 308):
                loc = e.headers.get("Location")
                self._save_cookies()
                if loc:
                    next_url = urllib.parse.urljoin(url, loc)
                    return self.request("GET", next_url)
            text = e.read().decode("utf-8", errors="replace")
            final_url = e.geturl()
            if status not in (409, 422):
                raise RuntimeError(f"HTTP {status} na {url}: {text[:500]}")
        finally:
            self._save_cookies()
        return status, final_url, text


def extract_inertia_page(raw_text):
    raw_text = raw_text.strip()
    if raw_text.startswith("{") and raw_text.endswith("}"):
        try:
            return json.loads(raw_text)
        except Exception:
            pass
    m = re.search(r'<script data-page="app" type="application/json">(.*?)</script>', raw_text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    m2 = re.search(r'data-page="([^"]+)"', raw_text)
    if m2:
        return json.loads(html.unescape(m2.group(1)))
    return None


def clean_props(page, include_translations=False):
    if not page:
        return None
    props = dict(page.get("props", {}))
    if not include_translations:
        props.pop("translations", None)
        props.pop("feTranslations", None)
    return {
        "component": page.get("component"),
        "url": page.get("url"),
        "version": page.get("version"),
        "props": props,
    }


def login(email=None, password=None):
    load_env()
    email = email or os.environ.get("WELCOMIO_EMAIL", "")
    password = password or os.environ.get("WELCOMIO_PASSWORD", "")
    if not email or not password:
        raise RuntimeError("Chýba WELCOMIO_EMAIL alebo WELCOMIO_PASSWORD.")

    sess = WelcomioSession()
    _, _, login_html = sess.request("GET", f"{ADMIN_BASE}/login")
    login_page = extract_inertia_page(login_html)
    version = login_page.get("version", "") if login_page else ""

    payload = json.dumps({
        "email": email,
        "password": password,
        "remember": "on",
    })
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/html, application/xhtml+xml",
        "X-Requested-With": "XMLHttpRequest",
        "X-Inertia": "true",
        "Origin": ADMIN_BASE,
        "Referer": f"{ADMIN_BASE}/login",
    }
    if version:
        headers["X-Inertia-Version"] = version

    _, _, out = sess.request("POST", f"{ADMIN_BASE}/login", headers=headers, data=payload)
    page = extract_inertia_page(out)
    if not page or not (page.get("props", {}).get("auth") or {}).get("user"):
        _, _, out = sess.request("GET", f"{ADMIN_BASE}/")
        page = extract_inertia_page(out)

    if not page:
        raise RuntimeError("Nepodarilo sa načítať odpoveď z Welcomio prihlásenia.")
    cleaned = clean_props(page)
    errors = cleaned["props"].get("errors") or {}
    user = (cleaned["props"].get("auth") or {}).get("user")
    if errors or not user:
        raise RuntimeError(f"Prihlásenie zlyhalo: {errors or 'Neplatné meno alebo heslo (user=null)'}")

    save_env_vars({"WELCOMIO_EMAIL": email, "WELCOMIO_PASSWORD": password})
    sb = (cleaned["props"].get("selectedBusiness") or {}).get("data", {})
    return {
        "ok": True,
        "user": {"id": user.get("id"), "name": user.get("name"), "email": user.get("email")},
        "business": {
            "id": sb.get("id"),
            "name": sb.get("name"),
            "active_url": sb.get("active_url"),
            "is_published": sb.get("is_published"),
        },
        "openOrdersCount": cleaned["props"].get("openOrdersCount"),
    }


def ensure_logged_in(path="/"):
    load_env()
    sess = WelcomioSession()
    url = path if path.startswith("http") else f"{ADMIN_BASE}/{path.lstrip('/')}"
    _, _, out = sess.request("GET", url)
    page = extract_inertia_page(out)
    if page and (page.get("props", {}).get("auth") or {}).get("user"):
        return sess, page
    if os.environ.get("WELCOMIO_EMAIL") and os.environ.get("WELCOMIO_PASSWORD"):
        login()
        sess = WelcomioSession()
        _, _, out = sess.request("GET", url)
        page = extract_inertia_page(out)
        if page:
            return sess, page
    raise RuntimeError("Nie ste prihlásený do Welcomio administrácie. Spustite príkaz 'login'.")


def main():
    parser = argparse.ArgumentParser(description="Yankee Drive - Welcomio Admin Manager")
    sub = parser.add_subparsers(dest="command", required=True)

    # login
    p_login = sub.add_parser("login", help="Prihlásiť sa do admin.welcomio.com a uložiť session")
    p_login.add_argument("--email", default=None, help="Prihlasovací e-mail do Welcomio")
    p_login.add_argument("--password", default=None, help="Heslo do Welcomio")

    # summary
    sub.add_parser("summary", help="Kompletný prehľad webu, cenníka, rezervácií a FAQ")

    # offers
    sub.add_parser("offers", help="Zobraziť položky cenníka (Ponuka služieb)")

    # booking-services
    sub.add_parser("booking-services", help="Zobraziť služby v online rezervačnom systéme")

    # reservations
    sub.add_parser("reservations", help="Zobraziť prijaté online rezervácie")

    # faq
    sub.add_parser("faq", help="Zobraziť všetky otázky a odpovede (FAQ)")

    # orders
    sub.add_parser("orders", help="Zobraziť objednávky z e-shopu")

    # get
    p_get = sub.add_parser("get", help="Načítať ľubovoľnú podstránku v admin.welcomio.com (Inertia JSON)")
    p_get.add_argument("path", nargs="?", default="/", help="Cesta v administrácii (napr. /bookings, /eshop/orders)")
    p_get.add_argument("--raw", action="store_true", help="Zahrnúť aj slovníky prekladov")

    # request
    p_req = sub.add_parser("request", help="Odoslať autentifikovaný POST/PUT/PATCH/DELETE požiadavok do Welcomio")
    p_req.add_argument("method", choices=["POST", "PUT", "PATCH", "DELETE"], help="HTTP metóda")
    p_req.add_argument("path", help="Cesta v administrácii")
    p_req.add_argument("--json", required=True, help="JSON dáta na odoslanie")

    args = parser.parse_args()

    try:
        if args.command == "login":
            res = login(args.email, args.password)
            print(json.dumps(res, indent=2, ensure_ascii=False))
        elif args.command == "summary":
            _, page = ensure_logged_in("/")
            sb = page["props"]["selectedBusiness"]["data"]
            _, b_page = ensure_logged_in("/bookings/services")
            _, r_page = ensure_logged_in("/bookings/reservations")
            services = b_page["props"].get("services", [])
            if isinstance(services, dict):
                services = services.get("data", [])
            reservations = r_page["props"].get("reservations", {})
            if isinstance(reservations, dict):
                reservations = reservations.get("data", [])
            print(json.dumps({
                "ok": True,
                "business": sb.get("name"),
                "url": sb.get("active_url"),
                "is_published": sb.get("is_published"),
                "open_eshop_orders": page["props"].get("openOrdersCount"),
                "offer_items_count": len(sb.get("offerItems", [])),
                "booking_services_count": len(services),
                "reservations_count": len(reservations),
                "modules": [
                    {"id": m.get("id"), "type": m.get("module_type"), "nav_label": m.get("nav_label")}
                    for m in sb.get("modules", [])
                ],
            }, indent=2, ensure_ascii=False))
        elif args.command == "offers":
            _, page = ensure_logged_in("/")
            sb = page["props"]["selectedBusiness"]["data"]
            items = [
                {
                    "id": it.get("id"),
                    "title": it.get("title"),
                    "price_eur": (it.get("price") or 0) / 100.0 if it.get("price") is not None else None,
                    "price_cents": it.get("price"),
                    "label": it.get("label"),
                    "status": it.get("status"),
                    "description": it.get("description"),
                }
                for it in sb.get("offerItems", [])
            ]
            print(json.dumps(items, indent=2, ensure_ascii=False))
        elif args.command == "booking-services":
            _, b_page = ensure_logged_in("/bookings/services")
            services = b_page["props"].get("services", [])
            if isinstance(services, dict):
                services = services.get("data", [])
            print(json.dumps(services, indent=2, ensure_ascii=False))
        elif args.command == "reservations":
            _, r_page = ensure_logged_in("/bookings/reservations")
            print(json.dumps({
                "reservations": r_page["props"].get("reservations"),
                "calendarReservations": r_page["props"].get("calendarReservations"),
            }, indent=2, ensure_ascii=False))
        elif args.command == "faq":
            _, page = ensure_logged_in("/")
            sb = page["props"]["selectedBusiness"]["data"]
            faq_mods = [m for m in sb.get("modules", []) if m.get("module_type") == "faq"]
            print(json.dumps(faq_mods, indent=2, ensure_ascii=False))
        elif args.command == "orders":
            _, o_page = ensure_logged_in("/eshop/orders")
            cleaned = clean_props(o_page)
            cleaned["props"].pop("selectedBusiness", None)
            cleaned["props"].pop("businesses", None)
            print(json.dumps(cleaned["props"], indent=2, ensure_ascii=False))
        elif args.command == "get":
            _, page = ensure_logged_in(args.path)
            cleaned = clean_props(page, include_translations=args.raw)
            print(json.dumps(cleaned, indent=2, ensure_ascii=False))
        elif args.command == "request":
            sess, page = ensure_logged_in("/")
            version = page.get("version", "") if page else ""
            url = args.path if args.path.startswith("http") else f"{ADMIN_BASE}/{args.path.lstrip('/')}"
            headers = {
                "Content-Type": "application/json",
                "Accept": "text/html, application/xhtml+xml, application/json",
                "X-Requested-With": "XMLHttpRequest",
                "X-Inertia": "true",
                "Origin": ADMIN_BASE,
                "Referer": ADMIN_BASE,
            }
            if version:
                headers["X-Inertia-Version"] = version
            _, _, out = sess.request(args.method, url, headers=headers, data=args.json)
            resp_page = extract_inertia_page(out)
            if resp_page:
                print(json.dumps(clean_props(resp_page), indent=2, ensure_ascii=False))
            else:
                print(out[:2000])
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, indent=2, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
