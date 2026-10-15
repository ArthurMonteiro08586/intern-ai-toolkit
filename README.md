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
