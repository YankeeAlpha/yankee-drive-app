#!/usr/bin/env python3
"""Testy synchronizácie do Firestore na falošných (mock) dátach – bez siete a bez kľúča.

Spustenie:  python3 tools/test_export_customers.py
"""
import sys
import types
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.modules.setdefault("welcomio_admin", types.ModuleType("welcomio_admin"))
import export_customers as ec  # noqa: E402


def fs_int(v):
    return {"integerValue": str(v)}


def fs_str(v):
    return {"stringValue": v}


class FakeFirestore:
    def __init__(self, docs):
        self.docs = docs  # {email: fields}
        self.writes = {}

    def request(self, url, token, method="GET", body=None):
        path = url.split("/documents/", 1)[1].split("?", 1)[0]
        coll, doc_id = path.split("/", 1)
        doc_id = urllib.parse.unquote(doc_id)
        if method == "GET":
            if coll == "customers" and doc_id in self.docs:
                return {"fields": self.docs[doc_id]}
            raise urllib.error.HTTPError(url, 404, "not found", None, None)
        self.writes[(coll, doc_id)] = body["fields"]
        return {}


def customer(email, points, history):
    return {
        "name": "Test Zákazník", "email": email, "phone": "", "city": "", "address": "",
        "orders_count": len(history), "total_spent_eur": float(points),
        "loyalty_points": points, "last_order_date": "2026-11-01", "history": history,
    }


class ExportTests(unittest.TestCase):
    def run_sync(self, docs, customers):
        fake = FakeFirestore(docs)
        ec._fs_request = fake.request
        ec.get_firestore_token = lambda: "fake-token"
        ec.sync_to_firestore(customers, [])
        return fake

    def written(self, fake, email):
        f = fake.writes[("customers", email)]
        return int(f["points"]["integerValue"]), f["welcomioHistoryText"]["stringValue"]

    def test_new_customer_gets_welcomio_points(self):
        fake = self.run_sync({}, [customer("a@test.sk", 40, ["2026-11-01: Refresh (40.00 €)"])])
        pts, hist = self.written(fake, "a@test.sk")
        self.assertEqual(pts, 40)
        self.assertEqual(hist, "2026-11-01: Refresh (40.00 €)")

    def test_points_never_lowered_legacy_record(self):
        # starý záznam: 210 b zadaných obsluhou, bonus iba 15, bez welcomioPoints/redeemedPoints
        docs = {"b@test.sk": {"points": fs_int(210), "bonusPoints": fs_int(15)}}
        fake = self.run_sync(docs, [customer("b@test.sk", 100, [])])
        self.assertEqual(self.written(fake, "b@test.sk")[0], 210)

    def test_points_never_lowered_when_welcomio_drops(self):
        # zrušená objednávka vo Welcomio zníži welcomio body – body zákazníka ostanú
        docs = {"c@test.sk": {"points": fs_int(124), "welcomioPoints": fs_int(124),
                              "bonusPoints": fs_int(0), "redeemedPoints": fs_int(0)}}
        fake = self.run_sync(docs, [customer("c@test.sk", 100, [])])
        self.assertEqual(self.written(fake, "c@test.sk")[0], 124)

    def test_new_purchase_added_to_legacy_record(self):
        docs = {"d@test.sk": {"points": fs_int(210), "welcomioPoints": fs_int(100), "bonusPoints": fs_int(15)}}
        fake = self.run_sync(docs, [customer("d@test.sk", 130, [])])
        self.assertEqual(self.written(fake, "d@test.sk")[0], 240)

    def test_consistent_record_with_redemption(self):
        # 250 Welcomio + 50 bonus - 100 minuté = 200; nový nákup +20 -> 220
        docs = {"e@test.sk": {"points": fs_int(200), "welcomioPoints": fs_int(250),
                              "bonusPoints": fs_int(50), "redeemedPoints": fs_int(100)}}
        fake = self.run_sync(docs, [customer("e@test.sk", 270, [])])
        self.assertEqual(self.written(fake, "e@test.sk")[0], 220)

    def test_history_not_duplicated_even_if_status_changed(self):
        old = "2026-08-20: 1x InsectOff 500ml (20.80 € - Odoslané) | 2026-08-17: 1x Sealant (27.50 € - Ukončené)"
        docs = {"f@test.sk": {"points": fs_int(48), "welcomioPoints": fs_int(48), "historyText": fs_str(old)}}
        hist = ["2026-08-20: 1x InsectOff 500ml (20.80 € - Ukončené)",  # zmenený stav
                "2026-08-17: 1x Sealant (27.50 € - Ukončené)",
                "2026-11-05: 1x Green Star 1L (12.00 € - Odoslané)"]       # nový riadok
        fake = self.run_sync(docs, [customer("f@test.sk", 60, hist)])
        pts, whist = self.written(fake, "f@test.sk")
        self.assertEqual(whist, "2026-11-05: 1x Green Star 1L (12.00 € - Odoslané)")
        self.assertEqual(pts, 60)

    def test_history_fully_present_writes_empty(self):
        old = "2026-09-09: 1x DriveCard25 (25.00 € - Odoslané)"
        docs = {"g@test.sk": {"points": fs_int(25), "welcomioPoints": fs_int(25), "historyText": fs_str(old)}}
        fake = self.run_sync(docs, [customer("g@test.sk", 25, [old])])
        self.assertEqual(self.written(fake, "g@test.sk")[1], "")

    def test_staff_fields_not_in_update_mask(self):
        captured = {}
        fake = FakeFirestore({})
        def req(url, token, method="GET", body=None):
            if method == "PATCH":
                captured["url"] = url
            return fake.request(url, token, method, body)
        ec._fs_request = req
        ec.get_firestore_token = lambda: "fake-token"
        ec.sync_to_firestore([customer("h@test.sk", 10, [])], [])
        for field in ("bonusPoints", "redeemedPoints", "historyText", "lastCouponCode"):
            self.assertNotIn("fieldPaths=" + field + "&", captured["url"] + "&")


if __name__ == "__main__":
    unittest.main(verbosity=2)
