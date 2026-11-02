# Grok Premium usage spike — 2026-11-02

## What Jon sees

Grok Bot desktop (`%APPDATA%\Roaming\Grok Bot`) shows Premium usage in the app menu (example: 38%). That profile only stored Cloudflare cookies (`__cf_bm`) and no bearer token we can reuse.

## Decision

**A for the grok CLI billing API, not for the Grok Bot desktop profile.**

- Endpoint: `GET https://cli-chat-proxy.grok.com/v1/billing?format=credits`
- Auth: bearer token from `~/.grok/auth.json` (or a token file in Settings)
- Header: `x-xai-token-auth: xai-grok-cli`
- Percent: `config.creditUsagePercent`

The floater implements that path as the **Grok Premium** row. It does not read the Grok Bot Electron session, because no usage token is stored there.
