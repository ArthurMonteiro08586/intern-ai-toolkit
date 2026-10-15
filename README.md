# intern-ai-toolkit

Авторег + гейтвей для Intern InkStone (discovery.intern-ai.org.cn, OpenXLab SSO).

## Что делает

- **intern_reg.py** — авторегистрация аккаунтов через OpenXLab SSO + GitHub OAuth:
  `GH login -> POST /gw/uaa-be/api/v1/login/oauthaddress {oauthFrom:github} -> github.com/login/oauth/authorize -> POST /gw/uaa-be/api/v1/login/oauth {code,state} -> jwt + ssoUid`.
  Банк: `intern_bank.jsonl` (login, sso.jwt, sso.ssoUid).
- **intern_keygen.py** — для каждого аккаунта банка: выпуск sk-ключа
  (`POST /api/moce/v1/apikey/create`), smoke orbit-chat (`/api/orbit/v1/chat/new` + `/chat`, SSE)
  и внешнего роутера. Банк: `intern_full.jsonl`.
- **intern_gw.py** — OpenAI-compatible гейтвей поверх пула jwt:
  `GET /v1/models`, `POST /v1/chat/completions` (stream + non-stream), ротация аккаунтов, failover.
  Модели: `intern`/`gpt-4o` (书生-S2), `deep` (书生-Agents-A1, deep-research), `dawn` (书生-Atria-Dawn-Preview).

## Запуск

```bash
python intern_reg.py 10 0          # волна 10 аккаунтов, старт с idx 0 пула
python intern_keygen.py            # ключи + smoke по банку
python intern_gw.py 8752           # гейтвей на :8752
curl http://127.0.0.1:8752/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"intern","messages":[{"role":"user","content":"hi"}]}'
```

## Env

- `GH_POOL` — json-пул GitHub-аккаунтов (login/password/totp), default `./gh_accounts.json`
- `INTERN_BANK` / `INTERN_FULL` / `INTERN_USED` — файлы банка

## API-контракт (реверс 15.10.2026)

- SSO: `https://sso.openxlab.org.cn/gw/uaa-be/api/v1/login/oauthaddress|oauth`, header `lang: zh-CN`
- Moce (ключи): `https://discovery.intern-ai.org.cn/api/moce/v1/apikey/{create,list,update,delete}`, Bearer jwt
- Orbit (чат): `/api/orbit/v1/chat/new {} -> {data.id}`; `/api/orbit/v1/chat {chat_id,query,model}` -> SSE
  `{"event":"message","answer":"<delta>"}` (answer — ДЕЛЬТЫ, склеивать)
- Модели: `/api/orbit/v1/models` -> Default / 书生-Agents-A1 (deep search) / 书生-S2 / 书生-Atria-Dawn-Preview
- Внешний роутер `https://discovery-api.intern-ai.org.cn/v1` на 15.10 sk-ключи moce НЕ принимает
  (401 invalid_api_key) — вероятно отдельная выдача/синк; веб-чат работает напрямую через jwt.

## Замечания

- Новый GH-аккаунт без verified email может дать ошибку на authorize — пул с verified email обязателен.
- consent GitHub (Authorize openmmlab) headless проходится через GHSession.oauth_code.
- Лимиты на аккаунт не опубликованы; пул 21 акк держал 3 параллельных чата без троттлинга.

---

# dolphin-wallet-farm

**Dolphin (v2.dphn.ai)** — DePIN AI-роутер. Регистрация = подпись challenge ЛЮБЫМ новым ETH-кошельком (аккаунты БЕСКОНЕЧНЫ), но для redeem-кода и API-ключа нужен Telegram-вериф (1 TG-акк = 1 кошелёк, бот @DolphinNM_bot).

## Флоу (dolphin_tg.py)

1. `Account.create()` → `GET /api/auth/challenge?address=` → `{message, nonce}`
2. `sign_message(encode_defunct(message))` → `POST /api/auth/verify {address, nonce, signature}` → session cookie + cookie `dolphin_csrf`
3. `POST /api/telegram/link` (X-CSRF-Token = dolphin_csrf) → `deep_link` (TTL 900s)
4. Telethon: `send_message('DolphinNM_bot', '/start <token>')` → `GET /api/telegram/status` → verified
5. `POST /api/credits {code: "API10"}` → +$10 (FCFS-код из канала bozdrop, 14.10)
6. `POST /api/keys {name}` → 201 `{key: "dp-..."}`

## Роутер (работает сразу, в отличие от intern)

- Base: `https://lighthouse.dphn.ai/run/text-v/v1` — нативный OpenAI-compat
- Модели: `deepseek-ai/DeepSeek-V4.1-Flash` (1M ctx), `unsloth/Qwen3.8-27B-NVFP4` (262K ctx), с reasoning
- `dolphin_gw.py [port]` — локальный ротатор пула dp-ключей (:8753 default), failover 401/402/429, stream

## Pitfalls

- POST без `Origin: https://v2.dphn.ai` → 403 "Cross-site POST form submissions are forbidden"
- `/api/keys` отвечает **201**, не 200
- TG-сессия привязывается к первому кошельку НАВСЕГДА — reuse не работает (verified=False на следующих)
- Пул сессий: ~50% NOT_AUTH (мёртвые) — маркать used, не ретраить

## Env (dolphin_tg.py)

`DOLPHIN_BANK`, `DOLPHIN_GOOD_TG`, `DOLPHIN_USED_TG`, `TG_AVAIL` (json-список имён .session), `TG_SESSION_DIRS` (pathsep-separated), `TG_API_ID`, `TG_API_HASH`
