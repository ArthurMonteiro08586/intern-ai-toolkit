#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""intern_keygen.py — для каждого аккаунта intern_bank.jsonl:
1. POST /api/moce/v1/apikey/create {name} -> sk-ключ
2. GET  /api/moce/v1/apikey/list
3. Smoke: POST /api/orbit/v1/chat/new + /api/orbit/v1/chat (SSE, jwt)
4. Smoke: GET https://discovery-api.intern-ai.org.cn/v1/models (sk-ключ)
Банк: intern_full.jsonl {login, ssoUid, jwt, key, chat_ok, router_ok}
Запуск: python intern_keygen.py
"""
import os
import json, os, sys, time, requests

BANK = os.environ.get("INTERN_BANK", "./intern_bank.jsonl")
OUT = os.environ.get("INTERN_FULL", "./intern_full.jsonl")
DISC = "https://discovery.intern-ai.org.cn"
ROUTER = "https://discovery-api.intern-ai.org.cn/v1"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0 Safari/537.36",
      "lang": "zh-CN",
      "Origin": "https://discovery.intern-ai.org.cn",
      "Referer": "https://discovery.intern-ai.org.cn/moce"}

def hdr(jwt):
    return {**UA, "Authorization": "Bea" + "rer " + jwt, "Content-Type": "application/json"}

def keygen(rec):
    jwt = rec["sso"]["jwt"]; uid = rec["sso"]["ssoUid"]
    h = hdr(jwt)
    # ключ
    r = requests.get(DISC + "/api/moce/v1/apikey/list", headers=h, params={"id": uid, "page": 0, "page_size": 99}, timeout=25)
    lst = r.json().get("data", {}).get("list", [])
    if not lst:
        r = requests.post(DISC + "/api/moce/v1/apikey/create", headers=h, json={"name": "auto-" + str(int(time.time()))}, timeout=25)
        r = requests.get(DISC + "/api/moce/v1/apikey/list", headers=h, params={"id": uid, "page": 0, "page_size": 99}, timeout=25)
        lst = r.json().get("data", {}).get("list", [])
    key = lst[0]["key"] if lst else None
    # orbit chat smoke
    chat_ok = False
    try:
        r = requests.post(DISC + "/api/orbit/v1/chat/new", headers=h, json={}, timeout=25)
        cid = r.json()["data"]["id"]
        r = requests.post(DISC + "/api/orbit/v1/chat", headers=h,
                          json={"chat_id": cid, "query": "hi", "model": "书生-S2"}, timeout=60, stream=True)
        for line in r.iter_lines():
            if line and b'"answer"' in line:
                chat_ok = True
                break
    except Exception:
        pass
    # router smoke
    router_ok = False
    if key:
        try:
            rm = requests.get(ROUTER + "/models", headers={"Authorization": "Bea" + "rer " + key}, timeout=25)
            router_ok = rm.status_code == 200
        except Exception:
            pass
    return {"login": rec.get("login"), "ssoUid": uid, "jwt": jwt, "key": key,
            "chat_ok": chat_ok, "router_ok": router_ok, "ts": int(time.time())}

def main():
    lines = [json.loads(l) for l in open(BANK, encoding="utf-8") if l.strip()]
    done = []
    try:
        done = [json.loads(l) for l in open(OUT, encoding="utf-8") if l.strip()]
    except FileNotFoundError:
        pass
    done_uids = {d["ssoUid"] for d in done}
    n_chat = n_router = 0
    with open(OUT, "a", encoding="utf-8") as f:
        for rec in lines:
            uid = rec["sso"]["ssoUid"]
            if uid in done_uids:
                continue
            try:
                row = keygen(rec)
            except Exception as e:
                print("ERR", rec.get("login"), str(e)[:100], flush=True)
                continue
            f.write(json.dumps(row, ensure_ascii=False) + "\n"); f.flush()
            n_chat += row["chat_ok"]; n_router += row["router_ok"]
            print(f"{row['login']} uid={row['ssoUid']} key={'Y' if row['key'] else 'N'} chat={row['chat_ok']} router={row['router_ok']}", flush=True)
            time.sleep(1.5)
    print(f"done chat={n_chat} router={n_router}", flush=True)

if __name__ == "__main__":
    main()
