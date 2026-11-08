#!/usr/bin/env python3
"""
Yankee Drive - Zoho Mail CLI Manager (servis@yankeedrive.sk)
Supports listing, reading, creating drafts, and sending emails via Zoho Mail (IMAP/SMTP or Zoho REST API).
"""

import argparse
import email
import email.policy
from email.header import decode_header
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
import imaplib
import json
import os
from pathlib import Path
import smtplib
import socket
import ssl
import sys
import time
import urllib.parse
import urllib.request

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"


def load_env():
    """Load configuration from .env file in persistent directory."""
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


def get_config():
    load_env()
    return {
        "email": os.environ.get("ZOHO_EMAIL", "servis@yankeedrive.sk"),
        "password": os.environ.get("ZOHO_APP_PASSWORD", ""),
        "region": os.environ.get("ZOHO_REGION", "eu"),  # 'eu' or 'com'
        "imap_host": os.environ.get("ZOHO_IMAP_HOST", ""),
        "imap_port": int(os.environ.get("ZOHO_IMAP_PORT", "993")),
        "smtp_host": os.environ.get("ZOHO_SMTP_HOST", ""),
        "smtp_port": int(os.environ.get("ZOHO_SMTP_PORT", "465")),
        "drafts_folder": os.environ.get("ZOHO_DRAFTS_FOLDER", "Drafts"),
        # Optional OAuth2 REST API config
        "client_id": os.environ.get("ZOHO_CLIENT_ID", ""),
        "client_secret": os.environ.get("ZOHO_CLIENT_SECRET", ""),
        "refresh_token": os.environ.get("ZOHO_REFRESH_TOKEN", ""),
        "account_id": os.environ.get("ZOHO_ACCOUNT_ID", ""),
    }


def decode_mime_str(value):
    if not value:
        return ""
    parts = decode_header(value)
    decoded = []
    for part, enc in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            decoded.append(str(part))
    return "".join(decoded)


def extract_body(msg):
    """Extract plain text (preferred) or stripped HTML body from an email.message.Message."""
    plain_parts = []
    html_parts = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if "attachment" in disp.lower():
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if ctype == "text/plain":
                plain_parts.append(text)
            elif ctype == "text/html":
                html_parts.append(text)
    else:
        payload = msg.get_payload(decode=True)
        if payload is not None:
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                html_parts.append(text)
            else:
                plain_parts.append(text)

    if plain_parts:
        return "\n".join(plain_parts).strip()
    if html_parts:
        import re
        raw_html = "\n".join(html_parts)
        cleaned = re.sub(r"<style[^>]*>.*?</style>", "", raw_html, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<script[^>]*>.*?</script>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<br\s*/?>", "\n", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"</p>", "\n\n", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"<[^>]+>", "", cleaned)
        return cleaned.strip()
    return ""


# =====================================================================
# Zoho REST API Client (HTTPS OAuth2 - works cleanly via HTTPS proxy)
# =====================================================================
class ZohoRestClient:
    def __init__(self, cfg):
        self.cfg = cfg
        region = cfg["region"]
        self.accounts_url = f"https://accounts.zoho.{region}"
        self.mail_url = f"https://mail.zoho.{region}/api"
        self._access_token = None

    def get_access_token(self):
        if self._access_token:
            return self._access_token
        data = urllib.parse.urlencode({
            "refresh_token": self.cfg["refresh_token"],
            "client_id": self.cfg["client_id"],
            "client_secret": self.cfg["client_secret"],
            "grant_type": "refresh_token",
        }).encode("utf-8")
        req = urllib.request.Request(f"{self.accounts_url}/oauth/v2/token", data=data, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            res = json.loads(resp.read().decode("utf-8"))
        if "access_token" not in res:
            raise RuntimeError(f"Chyba pri získavaní Zoho OAuth tokenu: {res}")
        self._access_token = res["access_token"]
        return self._access_token

    def _api_request(self, method, path, params=None, body=None):
        token = self.get_access_token()
        url = f"{self.mail_url}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {
            "Authorization": f"Zoho-oauthtoken {token}",
            "Accept": "application/json",
        }
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def get_account_id(self):
        if self.cfg["account_id"]:
            return self.cfg["account_id"]
        res = self._api_request("GET", "/accounts")
        accounts = res.get("data", [])
        if not accounts:
            raise RuntimeError("Nenašiel sa žiadny Zoho Mail účet.")
        return str(accounts[0]["accountId"])

    def list_messages(self, limit=10, unread=False, folder=None):
        acc_id = self.get_account_id()
        params = {"limit": limit}
        if unread:
            params["status"] = "unread"
        res = self._api_request("GET", f"/accounts/{acc_id}/messages/view", params=params)
        items = res.get("data", [])
        output = []
        for item in items:
            output.append({
                "id": str(item.get("messageId")),
                "folder_id": str(item.get("folderId", "")),
                "from": item.get("fromAddress", ""),
                "sender_name": item.get("sender", ""),
                "to": item.get("toAddress", ""),
                "subject": item.get("subject", "(Bez predmetu)"),
                "date": item.get("receivedTime", ""),
                "summary": item.get("summary", ""),
                "unread": item.get("status") == "0" or item.get("isRead") is False,
            })
        return output

    def read_message(self, message_id, folder_id=None):
        acc_id = self.get_account_id()
        if not folder_id:
            # Find message folder_id from recent messages
            msgs = self.list_messages(limit=50)
            for m in msgs:
                if m["id"] == str(message_id):
                    folder_id = m["folder_id"]
                    break
        if not folder_id:
            raise RuntimeError("Pre čítanie správy cez REST API zadajte alebo vyhľadajte ID správy zo zoznamu.")
        details = self._api_request(
            "GET", f"/accounts/{acc_id}/folders/{folder_id}/messages/{message_id}/details"
        ).get("data", {})
        content = self._api_request(
            "GET", f"/accounts/{acc_id}/folders/{folder_id}/messages/{message_id}/content"
        ).get("data", {})
        return {
            "id": str(message_id),
            "folder_id": str(folder_id),
            "from": details.get("fromAddress", ""),
            "to": details.get("toAddress", ""),
            "subject": details.get("subject", ""),
            "date": details.get("receivedTime", ""),
            "body": content.get("content", ""),
        }

    def save_draft(self, to_addr, subject, body, reply_to=None):
        acc_id = self.get_account_id()
        payload = {
            "fromAddress": self.cfg["email"],
            "toAddress": to_addr,
            "subject": subject,
            "content": body.replace("\n", "<br>"),
            "mode": "draft",
            "mailFormat": "html",
        }
        if reply_to:
            payload["action"] = "reply"
            payload["parentMessageId"] = str(reply_to)
        res = self._api_request("POST", f"/accounts/{acc_id}/messages", body=payload)
        return res.get("data", {})

    def send_message(self, to_addr, subject, body, reply_to=None):
        acc_id = self.get_account_id()
        payload = {
            "fromAddress": self.cfg["email"],
            "toAddress": to_addr,
            "subject": subject,
            "content": body.replace("\n", "<br>"),
            "mailFormat": "html",
        }
        if reply_to:
            payload["action"] = "reply"
            payload["parentMessageId"] = str(reply_to)
        res = self._api_request("POST", f"/accounts/{acc_id}/messages", body=payload)
        return res.get("data", {})


# =====================================================================
# Zoho IMAP / SMTP Client
# =====================================================================
class ZohoImapSmtpClient:
    def __init__(self, cfg):
        self.cfg = cfg
        region = cfg["region"]
        self.imap_host = cfg["imap_host"] or f"imaps.zoho.{region}"
        self.imap_port = cfg["imap_port"]
        self.smtp_host = cfg["smtp_host"] or f"smtp.zoho.{region}"
        self.smtp_port = cfg["smtp_port"]

    def _connect_imap(self):
        if not self.cfg["password"]:
            raise RuntimeError(
                "Chýba ZOHO_APP_PASSWORD alebo OAuth konfigurácia v /home/antigravity/.gemini/yankee-drive-assistant/.env"
            )
        M = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
        M.login(self.cfg["email"], self.cfg["password"])
        return M

    def list_messages(self, limit=10, unread=False, folder="INBOX"):
        M = self._connect_imap()
        try:
            status, _ = M.select(folder, readonly=True)
            if status != "OK":
                raise RuntimeError(f"Nepodarilo sa otvoriť priečinok {folder}")
            criterion = "UNSEEN" if unread else "ALL"
            status, data = M.search(None, criterion)
            if status != "OK" or not data or not data[0]:
                return []
            ids = data[0].split()
            recent_ids = ids[-limit:][::-1]
            results = []
            for msg_id in recent_ids:
                status, msg_data = M.fetch(msg_id, "(BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID)] FLAGS)")
                if status != "OK" or not msg_data or not msg_data[0]:
                    continue
                raw_headers = msg_data[0][1]
                flags_raw = msg_data[0][0].decode("utf-8", errors="ignore")
                msg = email.message_from_bytes(raw_headers)
                results.append({
                    "id": msg_id.decode("utf-8"),
                    "from": decode_mime_str(msg.get("From", "")),
                    "to": decode_mime_str(msg.get("To", "")),
                    "subject": decode_mime_str(msg.get("Subject", "(Bez predmetu)")),
                    "date": msg.get("Date", ""),
                    "message_id_header": msg.get("Message-ID", "").strip(),
                    "unread": "\\Seen" not in flags_raw,
                })
            return results
        finally:
            try:
                M.logout()
            except Exception:
                pass

    def read_message(self, msg_id, folder="INBOX"):
        M = self._connect_imap()
        try:
            M.select(folder, readonly=True)
            status, msg_data = M.fetch(str(msg_id), "(BODY.PEEK[])")
            if status != "OK" or not msg_data or not msg_data[0]:
                raise RuntimeError(f"Správa s ID {msg_id} sa nenašla.")
            raw_bytes = msg_data[0][1]
            msg = email.message_from_bytes(raw_bytes)
            return {
                "id": str(msg_id),
                "from": decode_mime_str(msg.get("From", "")),
                "to": decode_mime_str(msg.get("To", "")),
                "subject": decode_mime_str(msg.get("Subject", "(Bez predmetu)")),
                "date": msg.get("Date", ""),
                "message_id_header": msg.get("Message-ID", "").strip(),
                "references": msg.get("References", "").strip(),
                "body": extract_body(msg),
            }
        finally:
            try:
                M.logout()
            except Exception:
                pass

    def _build_mime_message(self, to_addr, subject, body, reply_to=None):
        msg = EmailMessage()
        msg["From"] = f"Yankee Drive <{self.cfg['email']}>"
        msg["To"] = to_addr
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain="yankeedrive.sk")

        if reply_to:
            try:
                orig = self.read_message(reply_to)
                if not subject:
                    orig_subj = orig["subject"]
                    subject = orig_subj if orig_subj.lower().startswith("re:") else f"Re: {orig_subj}"
                if orig.get("message_id_header"):
                    msg["In-Reply-To"] = orig["message_id_header"]
                    refs = orig.get("references", "")
                    msg["References"] = (refs + " " + orig["message_id_header"]).strip()
            except Exception:
                pass

        msg["Subject"] = subject or "Yankee Drive - Odpoveď"
        msg.set_content(body)
        return msg

    def save_draft(self, to_addr, subject, body, reply_to=None):
        msg = self._build_mime_message(to_addr, subject, body, reply_to=reply_to)
        M = self._connect_imap()
        try:
            draft_folder = self.cfg["drafts_folder"]
            raw_bytes = msg.as_bytes()
            status, _ = M.append(draft_folder, "\\Draft", imaplib.Time2Internaldate(time.time()), raw_bytes)
            if status != "OK":
                # Try fallback folder names common in Zoho Mail
                for alt in ["Drafts", "INBOX.Drafts", "Koncepty"]:
                    status, _ = M.append(alt, "\\Draft", imaplib.Time2Internaldate(time.time()), raw_bytes)
                    if status == "OK":
                        draft_folder = alt
                        break
            if status != "OK":
                raise RuntimeError("Nepodarilo sa uložiť koncept do priečinka Drafts/Koncepty.")
            return {"status": "draft_saved", "folder": draft_folder, "to": to_addr, "subject": msg["Subject"]}
        finally:
            try:
                M.logout()
            except Exception:
                pass

    def send_message(self, to_addr, subject, body, reply_to=None):
        msg = self._build_mime_message(to_addr, subject, body, reply_to=reply_to)
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, context=context) as server:
            server.login(self.cfg["email"], self.cfg["password"])
            server.send_message(msg)
        return {"status": "sent", "to": to_addr, "subject": msg["Subject"]}


def exchange_grant_code(client_id, client_secret, grant_code, region="eu"):
    """Exchange a Zoho Self-Client grant token (code) for a permanent refresh_token and save to .env."""
    accounts_url = f"https://accounts.zoho.{region}/oauth/v2/token"
    data = urllib.parse.urlencode({
        "code": grant_code,
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "authorization_code",
    }).encode("utf-8")
    req = urllib.request.Request(accounts_url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        res = json.loads(resp.read().decode("utf-8"))
    if "refresh_token" not in res:
        raise RuntimeError(f"Nepodarilo sa vymeniť kód za refresh_token: {res}")

    refresh_token = res["refresh_token"]
    # Save into .env
    env_Map = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env_Map[k.strip()] = v.strip()
    env_Map["ZOHO_EMAIL"] = env_Map.get("ZOHO_EMAIL", "servis@yankeedrive.sk")
    env_Map["ZOHO_REGION"] = region
    env_Map["ZOHO_CLIENT_ID"] = client_id
    env_Map["ZOHO_CLIENT_SECRET"] = client_secret
    env_Map["ZOHO_REFRESH_TOKEN"] = refresh_token

    # Fetch account_id right away using the new token
    os.environ["ZOHO_CLIENT_ID"] = client_id
    os.environ["ZOHO_CLIENT_SECRET"] = client_secret
    os.environ["ZOHO_REFRESH_TOKEN"] = refresh_token
    os.environ["ZOHO_REGION"] = region
    client = ZohoRestClient(get_config())
    client._access_token = res.get("access_token")
    account_id = client.get_account_id()
    env_Map["ZOHO_ACCOUNT_ID"] = account_id

    lines = [
        "# Konfigurácia pre Yankee Drive Zoho Mail (servis@yankeedrive.sk)",
        f"ZOHO_EMAIL={env_Map.get('ZOHO_EMAIL', 'servis@yankeedrive.sk')}",
        f"ZOHO_REGION={region}",
        f"ZOHO_APP_PASSWORD={env_Map.get('ZOHO_APP_PASSWORD', '')}",
        f"ZOHO_CLIENT_ID={client_id}",
        f"ZOHO_CLIENT_SECRET={client_secret}",
        f"ZOHO_REFRESH_TOKEN={refresh_token}",
        f"ZOHO_ACCOUNT_ID={account_id}",
        "",
    ]
    ENV_FILE.write_text("\n".join(lines), encoding="utf-8")
    return {"ok": True, "account_id": account_id, "refresh_token_saved": True}


def get_client():
    cfg = get_config()
    if cfg["client_id"] and cfg["client_secret"] and cfg["refresh_token"]:
        return ZohoRestClient(cfg), "rest"
    return ZohoImapSmtpClient(cfg), "imap"


def main():
    parser = argparse.ArgumentParser(description="Yankee Drive - Zoho Mail Manager (servis@yankeedrive.sk)")
    sub = parser.add_subparsers(dest="command", required=True)

    # auth
    p_auth = sub.add_parser("auth", help="Aktivovať Zoho OAuth2 cez Self Client kód a uložiť do .env")
    p_auth.add_argument("--client-id", required=True, help="Zoho Client ID")
    p_auth.add_argument("--client-secret", required=True, help="Zoho Client Secret")
    p_auth.add_argument("--code", required=True, help="Jednorazový Grant Code zo Zoho API Console")
    p_auth.add_argument("--region", default="eu", help="Región (eu alebo com)")

    # list
    p_list = sub.add_parser("list", help="Zobraziť zoznam posledných e-mailov")
    p_list.add_argument("--limit", type=int, default=10, help="Počet správ (predvolené: 10)")
    p_list.add_argument("--unread", action="store_true", help="Iba neprečítané správy")
    p_list.add_argument("--folder", default="INBOX", help="Priečinok (predvolené: INBOX)")

    # read
    p_read = sub.add_parser("read", help="Prečítať konkrétny e-mail podľa ID")
    p_read.add_argument("id", help="ID správy zo zoznamu")
    p_read.add_argument("--folder", default="INBOX", help="Priečinok (predvolené: INBOX)")

    # draft
    p_draft = sub.add_parser("draft", help="Vytvoriť koncept odpovede (bezpečné, neodošle e-mail)")
    p_draft.add_argument("--to", required=True, help="Adresa príjemcu")
    p_draft.add_argument("--subject", required=True, help="Predmet správy")
    p_draft.add_argument("--body", required=True, help="Text správy")
    p_draft.add_argument("--reply-to", default=None, help="ID pôvodnej správy pre odpoveď vo vlákne")

    # send
    p_send = sub.add_parser("send", help="Odoslať e-mail (IBA po výslovnom odsúhlasení používateľom!)")
    p_send.add_argument("--to", required=True, help="Adresa príjemcu")
    p_send.add_argument("--subject", required=True, help="Predmet správy")
    p_send.add_argument("--body", required=True, help="Text správy")
    p_send.add_argument("--reply-to", default=None, help="ID pôvodnej správy")

    # status / test
    sub.add_parser("test", help="Otestovať pripojenie a konfiguráciu Zoho Mail")

    args = parser.parse_args()

    try:
        if args.command == "auth":
            res = exchange_grant_code(args.client_id, args.client_secret, args.code, region=args.region)
            print(json.dumps(res, indent=2, ensure_ascii=False))
            return
        client, mode = get_client()
        if args.command == "test":
            msgs = client.list_messages(limit=3)
            print(json.dumps({
                "ok": True,
                "mode": mode,
                "email": get_config()["email"],
                "sample_count": len(msgs),
                "recent": msgs,
            }, indent=2, ensure_ascii=False))
        elif args.command == "list":
            msgs = client.list_messages(limit=args.limit, unread=args.unread, folder=args.folder)
            print(json.dumps(msgs, indent=2, ensure_ascii=False))
        elif args.command == "read":
            msg = client.read_message(args.id, folder=args.folder) if mode == "imap" else client.read_message(args.id)
            print(json.dumps(msg, indent=2, ensure_ascii=False))
        elif args.command == "draft":
            res = client.save_draft(args.to, args.subject, args.body, reply_to=args.reply_to)
            print(json.dumps(res, indent=2, ensure_ascii=False))
        elif args.command == "send":
            res = client.send_message(args.to, args.subject, args.body, reply_to=args.reply_to)
            print(json.dumps(res, indent=2, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, indent=2, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
