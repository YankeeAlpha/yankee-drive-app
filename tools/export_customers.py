#!/usr/bin/env python3
"""
Yankee Drive - Export zákazníkov, objednávok z e-shopu a online rezervácií čistenia do Excel/CSV tabuľky
Generuje:
1. yankee_drive_zakaznici.csv (Unikátni zákazníci + celková útrata + vernostné body 1 € = 1 bod)
2. yankee_drive_objednavky.csv (Všetky objednávky z e-shopu a rezervácie čistenia)
3. customers_data.json (Pre zobrazenie a 1-klikové stiahnutie do Excelu v internej aplikácii)
"""

import csv
import json
from pathlib import Path
import sys

TOOLS_DIR = Path(__file__).resolve().parent
BASE_DIR = TOOLS_DIR.parent
EXPORT_DIR = BASE_DIR / "exports"

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
            email = (cust.get("email") or "").strip()
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

            key = email.lower() if email else full_name.lower()
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
            c_email = (r.get("customer_email") or r.get("email") or "").strip()
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

            key = c_email.lower() if c_email else c_name.lower()
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


def export_all():
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    customers, records = fetch_all_records()

    # 1. Write yankee_drive_zakaznici.csv (UTF-8 with BOM + ';' delimiter for Slovak Excel)
    cust_csv = EXPORT_DIR / "yankee_drive_zakaznici.csv"
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
    ord_csv = EXPORT_DIR / "yankee_drive_objednavky.csv"
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
    json_path = EXPORT_DIR / "customers_data.json"
    payload = {
        "ok": True,
        "customers_count": len(customers),
        "records_count": len(records),
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
    out = export_all()
    print(json.dumps(out, indent=2, ensure_ascii=False))
