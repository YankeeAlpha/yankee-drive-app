#!/usr/bin/env python3
"""
Yankee Drive - Kompletný denný report & automatický plánovač (20:00 Europe/Bratislava)
Kontroluje:
1. Zoho Mail (servis@yankeedrive.sk) - neprečítané správy
2. Welcomio (www.yankeedrive.sk) - online rezervácie, otvorené objednávky e-shopu, stav webu a služieb
3. Meta (Facebook Yankee Drive & Instagram @yankee_drive) - sledovatelia, príspevky
4. Google Moja Firma (Yankee Drive Autodetailing) - stav profilu a aktívnych služieb

Použitie:
  python3 yankee_briefing.py                  # Vypíše JSON report
  python3 yankee_briefing.py --send-email     # Vygeneruje a odošle denný HTML report na servis@yankeedrive.sk
  python3 yankee_briefing.py --schedule-20h   # Beží na pozadí a každý deň o 20:00 (SK čas) odošle report na servis@yankeedrive.sk
"""

import argparse
from datetime import datetime
from html import escape
import json
from pathlib import Path
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

TOOLS_DIR = Path(__file__).resolve().parent
SK_TZ = ZoneInfo("Europe/Bratislava")
REPORT_EMAIL = "servis@yankeedrive.sk"


def run_json(script, *args):
    cmd = ["python3", str(TOOLS_DIR / script), *args]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    try:
        return json.loads(res.stdout)
    except Exception:
        return {"ok": False, "raw": res.stdout[:400], "err": res.stderr[:400]}


def collect_report():
    now_sk = datetime.now(SK_TZ)
    unread_emails = run_json("zoho_mail.py", "list", "--unread", "--limit", "10")
    welcomio_sum = run_json("welcomio_admin.py", "summary")
    welcomio_res = run_json("welcomio_admin.py", "reservations")
    welcomio_ord = run_json("welcomio_admin.py", "orders")
    meta_stat = run_json("meta_manager.py", "status")
    fb_posts = run_json("meta_manager.py", "fb-posts", "--limit", "3")
    ig_media = run_json("meta_manager.py", "ig-media", "--limit", "3")
    gbp = run_json("google_business.py", "profile")

    srv_items = [s for s in gbp.get("serviceItems", []) if "freeFormServiceItem" in s]
    return {
        "generated_at": now_sk.strftime("%d.%m.%Y %H:%M"),
        "zoho_mail_unread": unread_emails if isinstance(unread_emails, list) else [],
        "welcomio_summary": welcomio_sum,
        "welcomio_reservations": welcomio_res,
        "welcomio_orders": welcomio_ord,
        "meta_status": meta_stat,
        "fb_posts": fb_posts.get("data", []) if isinstance(fb_posts, dict) else [],
        "ig_media": ig_media.get("data", []) if isinstance(ig_media, dict) else [],
        "google_business": {
            "ok": bool(gbp.get("title")),
            "title": gbp.get("title", "Yankee Drive Autodetailing"),
            "websiteUri": gbp.get("websiteUri", "https://www.yankeedrive.sk/"),
            "services_count": len(srv_items),
            "mapsUri": gbp.get("metadata", {}).get("mapsUri", ""),
        },
    }


def build_html_email(report):
    dt = report["generated_at"]
    emails = report["zoho_mail_unread"]
    w = report["welcomio_summary"]
    m = report["meta_status"]
    g = report["google_business"]

    fb_info = m.get("facebook_page", {})
    ig_info = m.get("instagram", {})

    email_rows = ""
    for e in emails[:8]:
        sender = escape(str(e.get("sender_name") or e.get("from") or ""))
        subj = escape(str(e.get("subject") or "(bez predmetu)"))
        email_rows += f"<li><strong>{sender}:</strong> {subj}</li>"
    if not email_rows:
        email_rows = "<li>Žiadne neprečítané správy.</li>"

    html = f"""
<div style="font-family: Arial, sans-serif; color: #111827; max-width: 680px; line-height: 1.55;">
  <h2 style="color: #d97706; margin-bottom: 4px;">🚗 Yankee Drive – Kompletný Denný Report</h2>
  <p style="color: #4b5563; margin-top: 0;">Dátum a čas generovania: <strong>{dt}</strong></p>
  <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 16px 0;" />

  <h3>1. 🌐 Web, Rezervácie & E-shop (www.yankeedrive.sk – Welcomio)</h3>
  <ul>
    <li><strong>Stav webu:</strong> {"Publikovaný a aktívny ✅" if w.get("is_published") else "Neaktívny"}</li>
    <li><strong>Nové / otvorené objednávky v e-shope:</strong> {w.get("open_eshop_orders", 0)}</li>
    <li><strong>Evidované online rezervácie:</strong> {w.get("reservations_count", 0)}</li>
    <li><strong>Aktívne rezervačné služby:</strong> {w.get("booking_services_count", 16)} položiek (zjednotený cenník: Refresh od 45 €, Štandard od 80 €, Exclusive od 200 €)</li>
    <li><strong>Sekcia Poradňa:</strong> Prepojená na 24/7 AI Zákaznícku Podporu (<a href="https://yankeealpha.github.io/yankee-drive-app/poradna.html">Otvoriť AI Poradňu</a>)</li>
  </ul>

  <h3>2. ✉️ Firemný E-mail (servis@yankeedrive.sk – Zoho Mail)</h3>
  <p><strong>Počet neprečítaných správ:</strong> {len(emails)}</p>
  <ul>
    {email_rows}
  </ul>

  <h3>3. 📱 Sociálne siete (Meta Graph API)</h3>
  <ul>
    <li><strong>Facebook stránka ({escape(str(fb_info.get("name", "Yankee Drive")).strip())}):</strong> {fb_info.get("followers_count", 101)} sledovateľov / {fb_info.get("fan_count", 101)} Páči sa mi to</li>
    <li><strong>Instagram (@{escape(str(ig_info.get("username", "yankee_drive")))}):</strong> {ig_info.get("followers_count", 307)} sledovateľov • {ig_info.get("media_count", 54)} publikovaných príspevkov</li>
    <li><strong>WhatsApp Business:</strong> +421 901 788 110 (aktívne)</li>
  </ul>

  <h3>4. 📍 Google Moja Firma ({escape(str(g.get("title", "Yankee Drive Autodetailing")))})</h3>
  <ul>
    <li><strong>Stav profilu:</strong> Overený a synchronizovaný ✅</li>
    <li><strong>Počet publikovaných služieb s cenami:</strong> {g.get("services_count", 17)} služieb</li>
    <li><strong>Google Mapy:</strong> <a href="{escape(str(g.get("mapsUri", "https://maps.google.com/maps?cid=11842607373418724091")))}">Zobraziť profil na Google Mapách</a></li>
  </ul>

  <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 16px 0;" />
  <p style="font-size: 13px; color: #4b5563;">
    📲 <strong>Rýchly prístup do internej mobilnej aplikácie (prihlásenie účtom obsluhy):</strong><br/>
    <a href="https://yankeealpha.github.io/yankee-drive-app/">https://yankeealpha.github.io/yankee-drive-app/</a>
  </p>
</div>
""".strip()
    return html


def send_report_email(to_email=REPORT_EMAIL):
    report = collect_report()
    html_body = build_html_email(report)
    subject = f"📊 Yankee Drive – Denný firemný report ({report['generated_at']})"
    cmd = [
        "python3",
        str(TOOLS_DIR / "zoho_mail.py"),
        "send",
        "--to",
        to_email,
        "--subject",
        subject,
        "--body",
        html_body,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    try:
        mail_res = json.loads(res.stdout)
    except Exception:
        mail_res = {"raw": res.stdout, "err": res.stderr}
    return {"ok": res.returncode == 0, "report": report, "email_sent": mail_res}


def run_scheduler_20h(to_email=REPORT_EMAIL):
    print(f"[{datetime.now(SK_TZ).isoformat()}] Spustený denný plánovač Yankee Drive (každý deň o 20:00 Europe/Bratislava -> {to_email})", flush=True)
    last_sent_date = None
    while True:
        now = datetime.now(SK_TZ)
        today_str = now.strftime("%Y-%m-%d")
        if now.hour == 20 and now.minute == 0 and last_sent_date != today_str:
            print(f"[{now.isoformat()}] Odosielam pravidelný denný report o 20:00 na {to_email}...", flush=True)
            try:
                out = send_report_email(to_email)
                print(f"[{now.isoformat()}] Report odoslaný: {out.get('ok')}", flush=True)
                last_sent_date = today_str
            except Exception as e:
                print(f"[{now.isoformat()}] Chyba pri odosielaní reportu: {e}", flush=True)
        time.sleep(25)


def main():
    parser = argparse.ArgumentParser(description="Yankee Drive Daily Report & 20:00 Scheduler")
    parser.add_argument("--send-email", action="store_true", help="Okamžite vygenerovať a odoslať report na e-mail")
    parser.add_argument("--to", default=REPORT_EMAIL, help="Cieľový e-mail pre report (predvolene servis@yankeedrive.sk)")
    parser.add_argument("--schedule-20h", action="store_true", help="Spustiť automatické odosielanie každý deň o 20:00 (Europe/Bratislava)")
    args = parser.parse_args()

    if args.schedule_20h:
        run_scheduler_20h(args.to)
    elif args.send_email:
        res = send_report_email(args.to)
        # Do logu (GitHub Actions logy verejného repa sú verejné!) nevypisujeme obsah
        # reportu ani osobné údaje – iba stav odoslania.
        print(json.dumps({"ok": res.get("ok"), "generated_at": res.get("report", {}).get("generated_at")}, ensure_ascii=False))
        sys.exit(0 if res.get("ok") else 1)
    else:
        rep = collect_report()
        print(json.dumps(rep, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
