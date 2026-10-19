# Active sales service

Run from the repository root after applying migrations 004, 005 and 006:

```powershell
python -m pip install -r core/requirements.txt
python -m uvicorn Sleyz.sales_main:app --host 127.0.0.1 --port 8001
```

The entry point loads `Sleyz/.env` and then `core/.env` without overriding existing
process environment. Set `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SALES_BOT_TOKEN`,
`HUAWEI_MAAS_API_KEY`, `HUAWEI_MAAS_MODEL`, `SALES_WEBHOOK_SECRET` and
`MANAGER_BOT_TOKEN`. Register Telegram's webhook `/webhook` with its `secret_token`
set to `SALES_WEBHOOK_SECRET`. The bot token must match an organization's
`tg_connections.bot_token`; shared tokens across organizations are unsupported.
Business connection updates must come from the stored workspace owner.

The manager bot token posts review cards in the stored organization's
`group_chat_id`. Telegram bots cannot send review messages to one another. If the
group/token is unconfigured, the draft stays reviewable in the dashboard and a
sanitized configuration warning is logged. The manager and sales services must
share the same database and updated workflow migrations.

A buyer message is logged under the organization and prospect. Generation creates
`PENDING_DRAFT` first, claims generation, loads shared identity/search/catalog and
the latest twenty prospect messages, then calls Huawei. Failures retain a draft
with a sanitized generation error. Success transitions to `AWAITING_HITL` before
notification. No reply is sent until approval/edit. Every delivery goes through
the shared Telegram publisher, with authoritative stored text and destinations,
receipt verification and explicit handling of uncertain sends. Resolution remains
a separate owner action.

Docker uses repository-root build context and explicit source copies:

```powershell
docker compose -f Sleyz/docker-compose.yml build
docker compose -f Sleyz/docker-compose.yml up -d sales-bot
```

No environment files are copied into the image. Kubernetes deployment uses the
`converza-sales-runtime` Secret; `bridge/base/runtime-secret.template.yaml` lists
required key names without values. Existing exposed credentials from historical
manifests must be rotated before deployment. Do not apply the empty template over
a populated runtime Secret.

Local deterministic checks:

```powershell
$env:PYTHONPATH='core'
python -m unittest discover -s core/tests -p test_sleyz_service.py -v
```

A restart of this sales service and the manager service is required for these
changes. This workflow adds no publishing channel beyond the existing Telegram
reply path.
