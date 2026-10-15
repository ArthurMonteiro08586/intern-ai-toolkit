#!/usr/bin/env python3
# Intern InkStone (discovery.intern-ai.org.cn) autoreg via OpenXLab SSO GitHub OAuth
# Flow: GH login -> oauthaddress -> oauth_code -> login/oauth -> token
import os
import sys, os, json, re, time, random, requests
sys.path.insert(0, 'C:/Users/User/tmp/regfarm/github_oauth')
from gh_http import GHSession

SSO = "https://sso.openxlab.org.cn/gw/uaa-be"
GH_CID = "a141a8596ab840790774"          # OpenXLab SSO GitHub OAuth app
SSO_CID = "dagw07mkg1bazlxzoy31"         # discovery.intern-ai SSO client
POOL = json.load(open('C:/Users/User/tmp/gh_accounts.json', encoding='utf-8'))
USED = 'C:/Users/User/tmp/intern_ai/used_gh.txt'
BANK = 'C:/Users/User/tmp/intern_ai/intern_bank.jsonl'
os.makedirs('C:/Users/User/tmp/intern_ai', exist_ok=True)

HDRS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0 Safari/537.36",
    "Referer": "https://sso.openxlab.org.cn/wechat",
    "Origin": "https://sso.openxlab.org.cn",
    "Content-Type": "application/json",
    "lang": "zh-CN",
}

def used_load():
    if os.path.exists(USED):
        return set(open(USED, encoding='utf-8').read().split())
    return set()

def reg_one(acc, used):
    login = acc.get('login') or acc.get('username') or acc.get('email', '').split('@')[0]
    if login in used:
        return None, "used"
    pwd = acc.get('password') or acc.get('pass')
    totp = acc.get('totp') or acc.get('seed_2fa') or acc.get('2fa')
    ghs = GHSession(bind=False)
    lok, lmsg = ghs.login(login, pwd, totp)
    if not lok:
        return None, "gh login fail: " + str(lmsg)[:80]
    s = requests.Session()
    s.headers.update(HDRS)
    # 1. oauth address
    r = s.post(SSO + "/api/v1/login/oauthaddress",
               json={"oauthFrom": "github", "state": "intern_auto"}, timeout=30)
    j = r.json()
    if not j.get('success'):
        return None, "oauthaddress fail: " + j.get('msg', '')[:100]
    addr = j['data']['oauthAddress']
    m = re.search(r'state=([^&]+)', addr)
    state = m.group(1) if m else 'intern_auto'
    # 2. github oauth code (возвращает (code, err))
    code, cerr = ghs.oauth_code(GH_CID, state, scope='user')
    if not code:
        return None, "no gh code: " + str(cerr)[:100]
    # 3. exchange via sso login/oauth
    r = s.post(SSO + "/api/v1/login/oauth",
               json={"code": code, "oauthFrom": "github", "autoLogin": True,
                     "source": "discovery", "clientId": SSO_CID}, timeout=40)
    j = r.json()
    if not j.get('success'):
        return None, "login/oauth fail: " + json.dumps(j)[:200]
    data = j.get('data') or {}
    rec = {"login": login, "ts": time.strftime('%Y-%m-%d %H:%M:%S'), "sso": data}
    with open(BANK, 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    with open(USED, 'a', encoding='utf-8') as f:
        f.write(login + "\n")
    return rec, "ok"

def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    start = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    used = used_load()
    ok = fail = 0
    for acc in POOL[start:start + n * 4]:
        if ok >= n:
            break
        try:
            rec, msg = reg_one(acc, used)
        except Exception as e:
            rec, msg = None, "exc: " + repr(e)[:120]
        if rec:
            ok += 1
            print(f"[OK] {rec['login']} keys={list((rec['sso'] or {}).keys())}")
            print(json.dumps(rec['sso'])[:400])
        else:
            fail += 1
            lg = (acc.get('login') or acc.get('username') or '?')
            print(f"[FAIL] {lg}: {msg}")
        time.sleep(random.uniform(20, 40))
    print(f"done ok={ok} fail={fail}")

if __name__ == '__main__':
    main()
