#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""intern_gw.py — OpenAI-compatible gateway поверх Intern InkStone (discovery.intern-ai.org.cn).
Пул jwt из intern_full.jsonl, ротация round-robin, failover на следующий при ошибке.
Endpoints: GET /v1/models, POST /v1/chat/completions (stream + non-stream).
Модели-маппинг: gpt-4o / intern / default -> 书生-S2; deep -> 书生-Agents-A1; dawn -> 书生-Atria-Dawn-Preview.
Запуск: python intern_gw.py [port]  (default 8750)
Smoke: curl http://127.0.0.1:8750/v1/chat/completions -H 'Content-Type: application/json' \
       -d '{"model":"intern","messages":[{"role":"user","content":"hi"}]}'
"""
import json, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BANK = os.environ.get("INTERN_FULL", "./intern_full.jsonl")
DISC = "https://discovery.intern-ai.org.cn"
MODEL_MAP = {
    "intern": "书生-S2", "gpt-4o": "书生-S2", "intern-s2": "书生-S2", "default": "Default",
    "deep": "书生-Agents-A1", "agents-a1": "书生-Agents-A1",
    "dawn": "书生-Atria-Dawn-Preview", "atria": "书生-Atria-Dawn-Preview",
    "kimi-k2.7-code": "Kimi-K2.7-Code", "kimi": "Kimi-K2.7-Code",
    "deepseek-v4-flash": "DeepSeek-V4-Flash", "deepseek": "DeepSeek-V4-Flash",
    "qwen3.7-plus": "Qwen3.7-Plus", "qwen": "Qwen3.7-Plus",
    "qwen3.8-flash": "Qwen3.8-Flash", "qwen-flash": "Qwen3.8-Flash",
}
MODELS = list(MODEL_MAP.keys())

_pool = []
_lock = threading.Lock()
_idx = 0

def load_pool():
    global _pool
    rows = []
    seen = set()
    for l in open(BANK, encoding="utf-8"):
        l = l.strip()
        if not l:
            continue
        r = json.loads(l)
        if not r.get("chat_ok") or r["ssoUid"] in seen:
            continue
        seen.add(r["ssoUid"])
        rows.append(r)
    with _lock:
        _pool = rows
    return len(rows)

def next_acc():
    global _idx
    with _lock:
        if not _pool:
            return None
        acc = _pool[_idx % len(_pool)]
        _idx += 1
        return acc

def hdr(jwt):
    return {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0 Safari/537.36",
            "lang": "zh-CN", "Authorization": "Bea" + "rer " + jwt, "Content-Type": "application/json",
            "Origin": "https://discovery.intern-ai.org.cn", "Referer": "https://discovery.intern-ai.org.cn/moce"}

def chat(acc, model, messages):
    """Возвращает генератор SSE-строк орбита: (chat_id, answer_text)."""
    import requests
    h = hdr(acc["jwt"])
    r = requests.post(DISC + "/api/orbit/v1/chat/new", headers=h, json={}, timeout=25)
    cid = r.json()["data"]["id"]
    # склеиваем историю в один query (орбит не принимает messages)
    q = "\n".join(f"{m.get('role','user')}: {m.get('content','')}" for m in messages)
    r = requests.post(DISC + "/api/orbit/v1/chat", headers=h,
                      json={"chat_id": cid, "query": q, "model": model}, timeout=120, stream=True)
    if r.status_code != 200:
        raise RuntimeError("orbit chat %s" % r.status_code)
    return r

class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "*")
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/v1/models"):
            self._send(200, {"object": "list", "data": [{"id": m, "object": "model", "owned_by": "intern"} for m in MODELS]})
        elif self.path == "/health":
            self._send(200, {"pool": len(_pool)})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self.path.startswith("/v1/chat/completions"):
            return self._send(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._send(400, {"error": "bad json"})
        model = MODEL_MAP.get(req.get("model", "intern"), "书生-S2")
        stream = bool(req.get("stream"))
        msgs = req.get("messages", [])
        last_err = None
        for _ in range(min(6, max(1, len(_pool)))):
            acc = next_acc()
            if not acc:
                return self._send(503, {"error": "empty pool"})
            try:
                r = chat(acc, model, msgs)
                full = []
                prev = ""
                if stream:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    for line in r.iter_lines():
                        if not line or b'"answer"' not in line:
                            continue
                        try:
                            d = json.loads(line[5:] if line.startswith(b"data:") else line)
                        except Exception:
                            continue
                        piece = d.get("answer", "")
                        if piece:
                            full.append(piece)
                            chunk = {"id": "cmpl-intern", "object": "chat.completion.chunk",
                                     "created": int(time.time()), "model": req.get("model", "intern"),
                                     "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]}
                            self.wfile.write(b"data: " + json.dumps(chunk, ensure_ascii=False).encode("utf-8") + b"\n\n")
                            self.wfile.flush()
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                else:
                    for line in r.iter_lines():
                        if line and b'"answer"' in line:
                            try:
                                d = json.loads(line[5:] if line.startswith(b"data:") else line)
                                piece = d.get("answer", "")
                                if piece:
                                    full.append(piece)
                            except Exception:
                                pass
                    final = "".join(full)
                    self._send(200, {"id": "cmpl-intern", "object": "chat.completion",
                                     "created": int(time.time()), "model": req.get("model", "intern"),
                                     "choices": [{"index": 0, "message": {"role": "assistant", "content": final}, "finish_reason": "stop"}]})
                return
            except Exception as e:
                last_err = str(e)[:120]
                continue
        self._send(502, {"error": {"message": "all accounts failed: %s" % last_err, "type": "upstream"}})

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8750
    print("pool:", load_pool(), flush=True)
    # hot-reload пула раз в 60с
    def reloader():
        while True:
            time.sleep(60)
            try:
                load_pool()
            except Exception:
                pass
    threading.Thread(target=reloader, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
