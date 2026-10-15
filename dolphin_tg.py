#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dolphin_tg.py — Dolphin (v2.dphn.ai) full E2E: wallet-auth -> Telegram verify -> redeem -> API key.

TG-часть: Telethon-сессия из пула (mia_avail tail минус used) -> /start <token> боту @DolphinNM_bot.
Reuse: proven-сессии (dolphin_good_tg.json) ротируются без потребления.

Usage: PYTHONPATH="" Python311 dolphin_tg.py <count> [code]
Bank: dolphin_bank.jsonl
"""
import sys, os, json, time, re, asyncio, argparse

import requests
from eth_account import Account
from eth_account.messages import encode_defunct

BASE = "https://v2.dphn.ai"
BOT = "DolphinNM_bot"
BANK = os.environ.get("DOLPHIN_BANK", "./dolphin_bank.jsonl")
GOOD_TG = os.environ.get("DOLPHIN_GOOD_TG", "./dolphin_good_tg.json")
USED = os.environ.get("DOLPHIN_USED_TG", "./dolphin_used_tg.json")
AVAIL = os.environ.get("TG_AVAIL", "./tg_avail_sessions.json")
DIRS = os.environ.get("TG_SESSION_DIRS", "./sessions").split(os.pathsep)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0 Safari/537.36",
      "Origin": BASE, "Referer": BASE + "/"}
requests.packages.urllib3.disable_warnings()

TG_ID = int(os.environ.get("TG_API_ID", "0"))
TG_HASH = os.environ.get("TG_API_HASH", "")


def log(*a):
    print(*a, flush=True)


def good_sessions():
    out = []
    try:
        for p in json.load(open(GOOD_TG)):
            if os.path.exists(p):
                out.append(p)
    except Exception:
        pass
    return out


def mark_good(path):
    try:
        g = json.load(open(GOOD_TG))
    except Exception:
        g = []
    if path not in g:
        g.append(path)
        json.dump(g, open(GOOD_TG, 'w'))


def tg_sessions(n=4):
    names = json.load(open(AVAIL))
    try:
        used = set(json.load(open(USED)))
    except Exception:
        used = set()
    tail = [b for b in names if b not in used][-n:]
    out = []
    for b in tail:
        for d in DIRS:
            p = os.path.join(d, b)
            if os.path.exists(p):
                out.append(p)
                break
    return out


def mark_used(sess_path):
    try:
        used = set(json.load(open(USED)))
    except Exception:
        used = set()
    used.add(os.path.basename(sess_path))
    json.dump(sorted(used), open(USED, 'w'))


async def bot_start(sess_path, token):
    from telethon import TelegramClient
    name = os.path.basename(sess_path)
    client = TelegramClient(sess_path.replace('.session', ''), TG_ID, TG_HASH)
    try:
        await asyncio.wait_for(client.connect(), 45)
        if not await client.is_user_authorized():
            return name, 'NOT_AUTH'
        await client.send_message(BOT, '/start ' + token)
        await asyncio.sleep(8)
        msgs = await client.get_messages(BOT, limit=4)
        txt = ' '.join((m.message or '')[:200] for m in msgs if not m.out).lower()
        if 'verif' in txt or 'success' in txt or 'linked' in txt:
            return name, 'OK'
        return name, 'REPLY:' + txt[:150]
    except Exception as e:
        return name, 'EXC:' + str(e)[:120]
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


def wallet_session():
    """новый кошелёк + verified http-сессия + csrf"""
    s = requests.Session()
    s.headers.update(UA)
    acc = Account.create()
    r = s.get(BASE + "/api/auth/challenge", params={"address": acc.address}, timeout=30, verify=False)
    d = r.json()
    if "data" in d:
        d = d["data"]
    signed = acc.sign_message(encode_defunct(text=str(d["message"])))
    sig = "0x" + signed.signature.hex()
    r = s.post(BASE + "/api/auth/verify",
               json={"address": acc.address, "nonce": str(d["nonce"]), "signature": sig},
               headers={"content-type": "application/json"}, timeout=30, verify=False)
    if r.status_code != 200:
        raise RuntimeError(f"verify {r.status_code}: {r.text[:120]}")
    return s, acc, s.cookies.get("dolphin_csrf", "")


def tg_link(s, csrf):
    r = s.post(BASE + "/api/telegram/link", headers={"X-CSRF-Token": csrf}, timeout=20, verify=False)
    if r.status_code != 200:
        raise RuntimeError(f"link {r.status_code}: {r.text[:120]}")
    return r.json()["deep_link"]


def tg_status(s):
    r = s.get(BASE + "/api/telegram/status", timeout=20, verify=False)
    try:
        return r.json()
    except Exception:
        return {}


def finish(s, csrf, code):
    rec = {}
    if code:
        r = s.post(BASE + "/api/credits", json={"code": code},
                   headers={"Content-Type": "application/json", "X-CSRF-Token": csrf}, timeout=30, verify=False)
        rec["redeem_status"] = r.status_code
        rec["redeem"] = r.text[:200]
        log("redeem:", r.status_code, r.text[:150])
    r = s.get(BASE + "/api/credits", timeout=30, verify=False)
    if r.status_code == 200:
        rec["balance"] = r.json()
        log("balance:", r.text[:120])
    r = s.post(BASE + "/api/keys", json={"name": "auto"},
               headers={"Content-Type": "application/json", "X-CSRF-Token": csrf}, timeout=30, verify=False)
    if r.status_code in (200, 201):
        rec["key"] = r.json().get("key")
        log("key:", str(rec["key"])[:18] + "...")
    else:
        rec["key_err"] = f"{r.status_code}: {r.text[:120]}"
        log("key err:", rec["key_err"])
    return rec


async def farm_one(code, tg_pool, idx):
    s, acc, csrf = wallet_session()
    log(f"[{idx}] wallet {acc.address[:12]} csrf=Y")
    deep = tg_link(s, csrf)
    token = deep.split("start=")[-1]
    sess = tg_pool[idx % len(tg_pool)]
    name, res = await bot_start(sess, token)
    log(f"[{idx}] tg {name}: {res[:100]}")
    if res == 'OK':
        mark_used(sess)  # dolphin: 1 TG session = 1 wallet (reuse forbidden)
    elif res == 'NOT_AUTH':
        mark_used(sess)
        return None
    # poll status
    verified = False
    for _ in range(6):
        st = tg_status(s)
        if st.get("verified"):
            verified = True
            break
        await asyncio.sleep(3)
    log(f"[{idx}] verified={verified}")
    if not verified and res.startswith('EXC'):
        mark_used(sess)
    rec = {"address": acc.address, "private_key": acc.key.hex(), "ts": int(time.time()),
           "tg_sess": name, "tg_res": res[:100], "verified": verified}
    rec.update(finish(s, csrf, code))
    with open(BANK, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("count", type=int)
    ap.add_argument("code", nargs="?", default="API10")
    args = ap.parse_args()
    code = "" if args.code == "none" else args.code
    # proven-good сессии уже привязаны к своим кошелькам — в used
    for p in good_sessions():
        mark_used(p)
    pool = tg_sessions(args.count + 6)
    log("tg pool:", len(pool), pool[:2])
    if not pool:
        log("NO TG SESSIONS")
        return
    ok = 0
    for i in range(args.count):
        try:
            r = await farm_one(code, pool, i)
            if r:
                ok += 1
        except Exception as e:
            log(f"[{i}] FAIL {str(e)[:160]}")
        await asyncio.sleep(3)
    log(f"OK {ok}/{args.count}")


if __name__ == "__main__":
    asyncio.run(main())
