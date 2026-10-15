#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dolphin_gw.py — OpenAI-compatible gateway over Dolphin (dphn.ai) key pool.

Upstream: https://lighthouse.dphn.ai/run/text-v/v1 (native OpenAI: /models, /chat/completions).
Pool: dolphin_bank.jsonl (key field). Rotation round-robin + failover (401/402/429 -> next key).

Usage: PYTHONPATH="" Python311 dolphin_gw.py [port=8753]
"""
import json, os, sys, time, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import requests

requests.packages.urllib3.disable_warnings()

BANK = os.environ.get("DOLPHIN_BANK", os.path.join(os.path.dirname(os.path.abspath(__file__)), "dolphin_bank.jsonl"))
UPSTREAM = "https://lighthouse.dphn.ai/run/text-v/v1"
UA = {"User-Agent": "Mozilla/5.0"}

LOCK = threading.Lock()
IDX = 0
DEAD = {}  # key -> ts


def load_keys():
    keys = []
    try:
        for l in open(BANK, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            k = r.get("key")
            if not k and r.get("key_err"):
                import re
                m = re.search(r'"key":"(dp-[^"]+)"', r["key_err"])
                if m:
                    k = m.group(1)
            if k and k not in keys:
                keys.append(k)
    except FileNotFoundError:
        pass
    return keys


KEYS = load_keys()


def next_key():
    global IDX
    with LOCK:
        live = [k for k in KEYS if time.time() - DEAD.get(k, 0) > 600]
        if not live:
            DEAD.clear()
            live = list(KEYS)
        if not live:
            return None
        k = live[IDX % len(live)]
        IDX += 1
        return k


def mark_dead(k):
    with LOCK:
        DEAD[k] = time.time()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj, raw=None):
        body = raw if raw is not None else json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "*")
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"ok": True, "pool": len(KEYS), "dead": len(DEAD)})
        elif self.path.startswith("/v1/models"):
            k = next_key()
            if not k:
                self._send(503, {"err": "no keys"})
                return
            r = requests.get(UPSTREAM + "/models", headers={**UA, "Authorization": "Bea" + "rer " + k}, timeout=30, verify=False)
            self._send(r.status_code, None, raw=r.content)
        else:
            self._send(404, {"err": "not found"})

    def do_POST(self):
        if not self.path.startswith("/v1/chat/completions"):
            self._send(404, {"err": "not found"})
            return
        n = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(n) or b"{}")
        tries = min(4, max(1, len(KEYS)))
        last = None
        for _ in range(tries):
            k = next_key()
            if not k:
                break
            h = {**UA, "Authorization": "Bea" + "rer " + k, "Content-Type": "application/json"}
            try:
                if payload.get("stream"):
                    r = requests.post(UPSTREAM + "/chat/completions", headers=h, json=payload, timeout=300, verify=False, stream=True)
                    if r.status_code in (401, 402, 403, 429):
                        mark_dead(k)
                        last = (r.status_code, r.text[:200])
                        continue
                    self.send_response(r.status_code)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    for chunk in r.iter_content(4096):
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    return
                else:
                    r = requests.post(UPSTREAM + "/chat/completions", headers=h, json=payload, timeout=300, verify=False)
                    if r.status_code in (401, 402, 403, 429):
                        mark_dead(k)
                        last = (r.status_code, r.text[:200])
                        continue
                    self._send(r.status_code, None, raw=r.content)
                    return
            except Exception as e:
                mark_dead(k)
                last = (0, str(e)[:150])
        self._send(502, {"err": "pool exhausted", "last": last})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8753
    print(f"dolphin_gw :{port} pool={len(KEYS)} upstream={UPSTREAM}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
