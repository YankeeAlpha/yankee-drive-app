#!/usr/bin/env python3
"""
Yankee Drive - Export zákazníkov, objednávok z e-shopu a online rezervácií čistenia do Excel/CSV tabuľky
+ Obojsmerná synchronizácia s Firebase Firestore databázou Vernostného Klubu (yankee-drive-loyality-card).
Generuje (do priečinka exports/, ktorý je v .gitignore – NIKDY necommitovať do verejného repa):
1. yankee_drive_zakaznici.csv (Unikátni zákazníci + celková útrata + vernostné body 1 € = 1 bod)
2. yankee_drive_objednavky.csv (Všetky objednávky z e-shopu a rezervácie čistenia)
3. customers_data.json (lokálny súhrn)

Zápis do Firestore ide cez servisný účet Firebase (premenná FIREBASE_SERVICE_ACCOUNT
s obsahom JSON kľúča, uložená ako GitHub Secret). Bez nej sa synchronizácia preskočí –
anonymný zápis už Firestore pravidlá nepovoľujú.
"""

import argparse
import csv
import json
import os
import re
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request

TOOLS_DIR = Path(__file__).resolve().parent
BASE_DIR = TOOLS_DIR.parent
DEFAULT_EXPORT_DIR = BASE_DIR / "exports"
FIRESTORE_BASE = "https://firestore.googleapis.com/v1/projects/yankee-drive-loyality-card/databases/(default)/documents"

sys.path.insert(0, str(TOOLS_DIR))
import welcomio_admin  # noqa: E402


def fetch_all_records():
    records = []
    customers_map = {}

    # 1. E-shop Orders (open, fulfilled, cancelled)
    for tab in ["open", "fulfilled", "cancelled"]:
        try:
            _, page = welcomio_admin.ensure_logged_in(f"/eshop/orders?tab={tab}")
            orders = (welcomio_admin.clean_props(page)["props"].get("orders") or {}).get("data", [])
        except Exception:
            orders = []

        for o in orders:
            addr = o.get("address") or {}
            cust = o.get("order_customer") or {}
            sd = addr.get("shipping_details") or {}
            first_name = (addr.get("first_name") or "").strip()
            last_name = (addr.get("last_name") or "").strip()
            full_name = f"{first_name} {last_name}".strip() or "Neznámy zákazník"
            email = (cust.get("email") or "").strip().lower()
            phone = (addr.get("phone") or "").strip()
            if phone and not phone.startswith("+") and phone.startswith("9"):
                phone = "+421 " + phone
            city = (sd.get("city") or addr.get("city") or "").strip()
            street = (sd.get("name") or addr.get("street") or "").strip()
            total_eur = round((o.get("total_amount") or 0) / 100.0, 2)
            status_label = (o.get("status") or {}).get("label") or tab
            created_at = (o.get("created_at") or "")[:10]
            items_str = ", ".join(
                f"{it.get('quantity', 1)}x {it.get('product_name') or it.get('title') or 'Produkt'}"
                for it in (o.get("items") or [])
            )

            records.append({
                "type": "E-shop objednávka",
                "number": o.get("order_number") or o.get("id", "")[:8],
                "date": created_at,
                "name": full_name,
                "email": email,
                "phone": phone,
                "city": city,
                "address": street,
                "items": items_str,
                "total_eur": total_eur,
                "status": status_label,
                "payment": o.get("payment_method_name") or "",
                "shipping": o.get("shipping_method_name") or "",
            })

            key = email if email else full_name.lower()
            if key not in customers_map:
                customers_map[key] = {
                    "name": full_name,
                    "email": email,
                    "phone": phone,
                    "city": city,
                    "address": street,
                    "orders_count": 0,
                    "total_spent_eur": 0.0,
                    "loyalty_points": 0,
                    "last_order_date": created_at,
                    "history": [],
                }
            c_entry = customers_map[key]
            if status_label.lower() not in ("zrušené", "cancelled"):
                c_entry["orders_count"] += 1
                c_entry["total_spent_eur"] = round(c_entry["total_spent_eur"] + total_eur, 2)
                c_entry["loyalty_points"] = int(round(c_entry["total_spent_eur"]))
            if created_at > c_entry["last_order_date"]:
                c_entry["last_order_date"] = created_at
            c_entry["history"].append(f"{created_at}: {items_str} ({total_eur:.2f} € - {status_label})")

    # 2. Online Cleaning Reservations (upcoming, past, cancelled)
    seen_res_ids = set()
    for rtab in ["upcoming", "past", "cancelled"]:
        try:
            _, r_page = welcomio_admin.ensure_logged_in(f"/bookings/reservations?tab={rtab}")
            res_list = (welcomio_admin.clean_props(r_page)["props"].get("reservations") or {}).get("data", [])
        except Exception:
            res_list = []

        for r in res_list:
            rid = r.get("id")
            if rid in seen_res_ids:
                continue
            seen_res_ids.add(rid)
            c_name = (r.get("customer_name") or r.get("name") or "Zákazník rezervácie").strip()
            c_email = (r.get("customer_email") or r.get("email") or "").strip().lower()
            c_phone = (r.get("customer_phone") or r.get("phone") or "").strip()
            srv_name = (r.get("service_name") or (r.get("service") or {}).get("name") or "Detailing / Čistenie").strip()
            price_eur = round((r.get("price") or 0) / 100.0, 2)
            r_date = (r.get("starts_at") or r.get("created_at") or "")[:10]
            r_status = r.get("status_label") or str(r.get("status") or rtab)

            records.append({
                "type": "Rezervácia čistenia",
                "number": str(rid)[:8],
                "date": r_date,
                "name": c_name,
                "email": c_email,
                "phone": c_phone,
                "city": "",
                "address": r.get("note") or "",
                "items": srv_name,
                "total_eur": price_eur,
                "status": r_status,
                "payment": "Na mieste / Faktúra",
                "shipping": "Osobný odber / Door-to-Door",
            })

            key = c_email if c_email else c_name.lower()
            if key not in customers_map:
                customers_map[key] = {
                    "name": c_name,
                    "email": c_email,
                    "phone": c_phone,
                    "city": "",
                    "address": "",
                    "orders_count": 0,
                    "total_spent_eur": 0.0,
                    "loyalty_points": 0,
                    "last_order_date": r_date,
                    "history": [],
                }
            c_entry = customers_map[key]
            c_entry["orders_count"] += 1
            c_entry["total_spent_eur"] = round(c_entry["total_spent_eur"] + price_eur, 2)
            c_entry["loyalty_points"] = int(round(c_entry["total_spent_eur"]))
            c_entry["history"].append(f"{r_date}: {srv_name} ({price_eur:.2f} €)")

    records.sort(key=lambda x: x["date"], reverse=True)
    customers = sorted(customers_map.values(), key=lambda x: x["total_spent_eur"], reverse=True)
    return customers, records


_TOKEN_CACHE = {}


def get_firestore_token():
    """Vráti OAuth token servisného účtu (Firebase Admin) alebo None, ak nie je nastavený."""
    if "token" in _TOKEN_CACHE:
        return _TOKEN_CACHE["token"]
    raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "").strip()
    if not raw:
        return None
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
    except ImportError:
        print("Chýba balík google-auth (pip install google-auth requests) – Firestore sync preskočený.", file=sys.stderr)
        return None
    info = json.loads(raw)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/datastore"]
    )
    creds.refresh(Request())
    _TOKEN_CACHE["token"] = creds.token
    return creds.token


def _fs_request(url, token, method="GET", body=None):
    headers = {"Authorization": f"Bearer {token}", "User-Agent": "YankeeDriveExport/2.0"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8", errors="ignore") or "{}")


def _int_field(fields, name):
    v = fields.get(name) or {}
    try:
        return int(v.get("integerValue", v.get("doubleValue", 0)))
    except (TypeError, ValueError):
        return 0


def sync_to_firestore(customers, records=None):
    """Zapíše zákazníkov (customers) a objednávky (orders) do Firestore cez servisný účet.

    Zákazníkom sa aktualizujú iba polia z Welcomio (updateMask), takže sa NEPREPÍŠU
    body pripísané obsluhou, minuté body, poukazy ani história zápisov obsluhy.
    """
    token = get_firestore_token()
    if not token:
        print("FIREBASE_SERVICE_ACCOUNT nie je nastavený – Firestore sync preskočený.", file=sys.stderr)
        return 0
    synced = 0
    mask_fields = [
        "email", "name", "phone", "city", "address", "ordersCount", "totalSpentEur",
        "welcomioPoints", "points", "lastOrderDate", "welcomioHistoryText",
    ]
    mask_qs = "&".join("updateMask.fieldPaths=" + f for f in mask_fields)
    for c in customers:
        email = (c.get("email") or "").strip().lower()
        if not email:
            continue
        doc_url = f"{FIRESTORE_BASE}/customers/{urllib.parse.quote(email, safe='@.')}"
        existing_fields = {}
        try:
            existing_fields = _fs_request(doc_url, token).get("fields", {})
        except urllib.error.HTTPError as e:
            if e.code != 404:
                print(f"Firestore read warning (HTTP {e.code})", file=sys.stderr)
                continue
        except Exception as e:
            print(f"Firestore read warning: {type(e).__name__}", file=sys.stderr)
            continue

        bonus_points = _int_field(existing_fields, "bonusPoints")
        redeemed_points = _int_field(existing_fields, "redeemedPoints")
        welcomio_points = int(c["loyalty_points"])
        final_points = max(0, welcomio_points + bonus_points - redeemed_points)
        prev_last = (existing_fields.get("lastOrderDate") or {}).get("stringValue", "")
        last_order = max(prev_last, c["last_order_date"] or "")

        body = {
            "fields": {
                "email": {"stringValue": email},
                "name": {"stringValue": c["name"]},
                "phone": {"stringValue": c["phone"] or ""},
                "city": {"stringValue": c["city"] or ""},
                "address": {"stringValue": c["address"] or ""},
                "ordersCount": {"integerValue": str(c["orders_count"])},
                "totalSpentEur": {"doubleValue": float(c["total_spent_eur"])},
                "welcomioPoints": {"integerValue": str(welcomio_points)},
                "points": {"integerValue": str(final_points)},
                "lastOrderDate": {"stringValue": last_order},
                "welcomioHistoryText": {"stringValue": " | ".join(c["history"])[:5000]},
            }
        }
        try:
            _fs_request(f"{doc_url}?{mask_qs}", token, method="PATCH", body=body)
            synced += 1
        except Exception as e:
            print(f"Firestore write warning: {type(e).__name__}", file=sys.stderr)

    for r in records or []:
        prefix = "eshop" if str(r.get("type", "")).startswith("E-shop") else "rezervacia"
        doc_id = re.sub(r"[^A-Za-z0-9_-]", "_", f"{prefix}-{r.get('number') or ''}")[:120]
        if doc_id.endswith("-"):
            continue
        body = {"fields": {
            "type": {"stringValue": r["type"]},
            "number": {"stringValue": str(r["number"])},
            "date": {"stringValue": r["date"] or ""},
            "name": {"stringValue": r["name"] or ""},
            "email": {"stringValue": r["email"] or ""},
            "phone": {"stringValue": r["phone"] or ""},
            "city": {"stringValue": r["city"] or ""},
            "address": {"stringValue": r["address"] or ""},
            "items": {"stringValue": r["items"] or ""},
            "total_eur": {"doubleValue": float(r["total_eur"] or 0)},
            "status": {"stringValue": r["status"] or ""},
            "payment": {"stringValue": r["payment"] or ""},
            "shipping": {"stringValue": r["shipping"] or ""},
            "source": {"stringValue": "welcomio"},
        }}
        try:
            _fs_request(f"{FIRESTORE_BASE}/orders/{doc_id}", token, method="PATCH", body=body)
        except Exception as e:
            print(f"Firestore order write warning: {type(e).__name__}", file=sys.stderr)
    return synced


def export_all(output_dir=None):
    export_dir = Path(output_dir).resolve() if output_dir else DEFAULT_EXPORT_DIR
    export_dir.mkdir(parents=True, exist_ok=True)
    customers, records = fetch_all_records()
    firestore_synced = sync_to_firestore(customers, records)

    # 1. Write yankee_drive_zakaznici.csv (UTF-8 with BOM + ';' delimiter for Slovak Excel)
    cust_csv = export_dir / "yankee_drive_zakaznici.csv"
    with cust_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow([
            "Meno a priezvisko",
            "E-mail",
            "Telefón",
            "Mesto",
            "Adresa / Výdajné miesto",
            "Počet platných objednávok",
            "Celková útrata (EUR)",
            "Vernostné body (1 € = 1 bod)",
            "Posledná objednávka",
            "História nákupov a služieb",
        ])
        for c in customers:
            writer.writerow([
                c["name"],
                c["email"],
                c["phone"],
                c["city"],
                c["address"],
                c["orders_count"],
                f"{c['total_spent_eur']:.2f}".replace(".", ","),
                c["loyalty_points"],
                c["last_order_date"],
                " | ".join(c["history"]),
            ])

    # 2. Write yankee_drive_objednavky.csv
    ord_csv = export_dir / "yankee_drive_objednavky.csv"
    with ord_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow([
            "Typ",
            "Číslo obj./rez.",
            "Dátum",
            "Zákazník",
            "E-mail",
            "Telefón",
            "Mesto",
            "Adresa / Poznámka",
            "Služba / Produkty",
            "Suma (EUR)",
            "Stav",
            "Platba",
            "Doprava",
        ])
        for r in records:
            writer.writerow([
                r["type"],
                r["number"],
                r["date"],
                r["name"],
                r["email"],
                r["phone"],
                r["city"],
                r["address"],
                r["items"],
                f"{r['total_eur']:.2f}".replace(".", ","),
                r["status"],
                r["payment"],
                r["shipping"],
            ])

    # 3. Write JSON summary
    json_path = export_dir / "customers_data.json"
    payload = {
        "ok": True,
        "customers_count": len(customers),
        "records_count": len(records),
        "firestore_synced": firestore_synced,
        "customers": customers,
        "records": records,
        "files": {
            "customers_csv": str(cust_csv),
            "orders_csv": str(ord_csv),
        },
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Yankee Drive - Export zákazníkov do Excel/CSV a Firebase")
    parser.add_argument("--output-dir", default=None, help="Cieľový priečinok pre CSV a JSON súbory (predvolene exports/, mimo gitu)")
    args = parser.parse_args()
    out = export_all(args.output_dir)
    # Do logu iba počty – logy GitHub Actions vo verejnom repe sú verejné.
    print(json.dumps({
        "ok": out.get("ok"),
        "customers_count": out.get("customers_count"),
        "records_count": out.get("records_count"),
        "firestore_synced": out.get("firestore_synced"),
    }, ensure_ascii=False))
