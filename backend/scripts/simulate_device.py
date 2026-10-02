#!/usr/bin/env python3
"""
KOReader plugin simulator for the Kolibre sync protocol v2 (cantiere A1).

Drives the device-token endpoints exactly like the real Lua plugin will, so it
doubles as executable documentation of the wire contract for the plugin agent.
Stdlib only (urllib) — runnable with the project venv or any python3:

    venv/bin/python3 backend/scripts/simulate_device.py \
        --server http://localhost:8081 --token kolibre_tok_... <scenario>

Scenarios:
    full      v2 handshake -> download every send -> ack ok (path+pages)
              -> ack removes as deleted -> /pages -> finish
    declined  v2 handshake -> ack every remove as 'declined' -> finish
    missing   v2 handshake -> ack every remove as 'missing' -> finish
    light     v2 handshake -> finish -> second handshake carrying the
              library_token and NO managed_books (light sync)
    conflict  two v2 handshakes without finishing the first -> expects 409,
              then finishes the first session to clean up
    legacy    v1 handshake (no "protocol" field) -> downloads/deletions with
              queue_id -> /sync/confirm

Preconditions (queued sends/deletes) are created from the web GUI or via the
JWT API, e.g.:
    curl -X POST $SERVER/api/devices/<id>/queue -H "Authorization: Bearer $JWT" \
         -H 'Content-Type: application/json' \
         -d '{"calibre_book_id": 1, "library": "default", "action": "queued_download", "format": "EPUB"}'
"""

import argparse
import json
import urllib.error
import urllib.request

PLUGIN_VERSION = "simulate-0.1"


class Client:
    def __init__(self, server: str, token: str, verbose: bool = True):
        self.server = server.rstrip("/")
        self.token = token
        self.verbose = verbose

    def call(self, method: str, path: str, payload=None, expect_error=False):
        url = self.server + path
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        })
        if self.verbose:
            print(f"\n>>> {method} {path}")
            if payload is not None:
                print(json.dumps(payload, indent=2, ensure_ascii=False))
        try:
            with urllib.request.urlopen(req) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                status = resp.status
        except urllib.error.HTTPError as e:
            status = e.code
            try:
                body = json.loads(e.read().decode("utf-8"))
            except Exception:
                body = {"raw": "<non-JSON error body>"}
            if not expect_error:
                print(f"<<< HTTP {status}")
                print(json.dumps(body, indent=2, ensure_ascii=False))
                raise SystemExit(f"ERRORE: {method} {path} -> HTTP {status}")
        if self.verbose:
            print(f"<<< HTTP {status}")
            print(json.dumps(body, indent=2, ensure_ascii=False))
        return status, body

    def download(self, path: str) -> int:
        """Simulated book download: fetches the file and returns its size."""
        req = urllib.request.Request(self.server + path, headers={
            "Authorization": f"Bearer {self.token}",
        })
        with urllib.request.urlopen(req) as resp:
            size = len(resp.read())
        if self.verbose:
            print(f"\n>>> GET {path}\n<<< HTTP 200 ({size} bytes scaricati)")
        return size


def fake_device_path(send: dict) -> str:
    author = (send.get("author") or "Sconosciuto").replace("/", "_")
    title = (send.get("title") or f"book-{send['calibre_book_id']}").replace("/", "_")
    return f"/mnt/onboard/kolibre/{author}/{title} ({send['calibre_book_id']}).{send['format'].lower()}"


def handshake(c: Client, trigger: str, library_token=None, managed=None, missing=None, expect_error=False):
    payload = {"protocol": 2, "plugin_version": PLUGIN_VERSION, "trigger": trigger,
               "library_token": library_token}
    if managed is not None:
        payload["managed_books"] = managed
    if missing is not None:
        payload["missing_books"] = missing
    return c.call("POST", "/api/kolibre/devices/sync", payload, expect_error=expect_error)


def ack_and_finish(c: Client, session_id: str, downloads=None, deletions=None, outcome=None):
    if downloads or deletions:
        c.call("POST", "/api/kolibre/devices/sync/ack", {
            "session_id": session_id,
            "downloads": downloads or [],
            "deletions": deletions or [],
        })
    finish_payload = {"session_id": session_id}
    if outcome:
        finish_payload["outcome"] = outcome
    return c.call("POST", "/api/kolibre/devices/sync/finish", finish_payload)


def scenario_full(c: Client):
    _, resp = handshake(c, trigger="manual", managed=[])
    session_id = resp["session_id"]
    downloads_ack, pages_report = [], []
    for send in resp["sends"]:
        size = c.download(send["download_url"])
        ok = size > 0
        entry = {"book_id": send["book_id"], "ok": ok}
        if ok:
            entry["path"] = fake_device_path(send)
            entry["pages"] = 100 + send["calibre_book_id"]  # fake on-device page count
        else:
            entry["error"] = "file vuoto"
        downloads_ack.append(entry)
        if send.get("delivery_hash"):
            pages_report.append({"hash": send["delivery_hash"], "pages": 100 + send["calibre_book_id"]})
    deletions_ack = [{"book_id": r["book_id"], "result": "deleted"} for r in resp["removes"]]
    if not downloads_ack and not deletions_ack:
        print("\n(!) Nessun send/remove in coda: accoda qualcosa via GUI/JWT prima di 'full'.")
    ack_and_finish(c, session_id, downloads_ack, deletions_ack)
    if pages_report:
        c.call("POST", "/api/kolibre/devices/pages", {"books": pages_report})
    print(f"\n== full: {len(downloads_ack)} download ok, {len(deletions_ack)} delete confermate ==")


def _scenario_delete_result(c: Client, result: str):
    _, resp = handshake(c, trigger="manual")
    session_id = resp["session_id"]
    deletions_ack = [{"book_id": r["book_id"], "result": result} for r in resp["removes"]]
    if not deletions_ack:
        print(f"\n(!) Nessuna remove in coda: accoda una queued_delete prima di '{result}'.")
    ack_and_finish(c, session_id, deletions=deletions_ack)
    print(f"\n== {result}: {len(deletions_ack)} remove marcate '{result}' ==")


def scenario_declined(c: Client):
    _scenario_delete_result(c, "declined")


def scenario_missing(c: Client):
    _scenario_delete_result(c, "missing")


def scenario_light(c: Client):
    _, first = handshake(c, trigger="auto_open", managed=[])
    ack_and_finish(c, first["session_id"])
    token = first["library_token"]
    print(f"\n-- secondo handshake con library_token={token} e SENZA managed_books --")
    _, second = handshake(c, trigger="auto_resume", library_token=token)
    ack_and_finish(c, second["session_id"])
    same = second["library_token"] == token
    print(f"\n== light: token {'INVARIATO (sync leggero ok)' if same else 'CAMBIATO (stato mutato lato server)'} ==")


def scenario_conflict(c: Client):
    _, first = handshake(c, trigger="manual")
    print("\n-- secondo handshake SENZA aver chiuso il primo: atteso 409 --")
    status, body = handshake(c, trigger="manual", expect_error=True)
    if status == 409:
        print("\n== conflict: 409 ricevuto come atteso ==")
    else:
        print(f"\n== conflict: ATTESO 409, ricevuto {status} — BUG ==")
    ack_and_finish(c, first["session_id"])  # cleanup
    if status != 409:
        raise SystemExit(1)


def scenario_legacy(c: Client):
    print("\n-- handshake v1: payload senza 'protocol' --")
    _, resp = c.call("POST", "/api/kolibre/devices/sync", {"managed_books": []})
    queue_ids = []
    for d in resp["downloads"]:
        c.download(d["download_url"])
        queue_ids.append(d["queue_id"])
    queue_ids += [d["queue_id"] for d in resp["deletions"]]
    if not queue_ids:
        print("\n(!) Coda vuota: accoda qualcosa prima di 'legacy'.")
    c.call("POST", "/api/kolibre/devices/sync/confirm", {"queue_ids": queue_ids})
    print(f"\n== legacy: {len(queue_ids)} voci confermate via /sync/confirm ==")


SCENARIOS = {
    "full": scenario_full,
    "declined": scenario_declined,
    "missing": scenario_missing,
    "light": scenario_light,
    "conflict": scenario_conflict,
    "legacy": scenario_legacy,
}


def main():
    parser = argparse.ArgumentParser(description="Simulatore del plugin KOReader per il protocollo di sync v2 di Kolibre")
    parser.add_argument("--server", default="http://localhost:8081", help="URL base del server Kolibre")
    parser.add_argument("--token", required=True, help="Device token (kolibre_tok_...)")
    parser.add_argument("scenario", choices=sorted(SCENARIOS), help="Scenario da eseguire")
    args = parser.parse_args()

    client = Client(args.server, args.token)
    SCENARIOS[args.scenario](client)


if __name__ == "__main__":
    main()
