# Home Assistant MCP Connector

An MCP (Model Context Protocol) server that exposes Home Assistant to AI agents
such as Mistral's Vibe. Once deployed and registered as a custom MCP connector,
agents can discover your smart home entities, inspect their state, call
services (lights, switches, climate...), and trigger automations — on request
only, never proactively.

## Tools exposed

| Tool | Purpose |
|---|---|
| `list_entities` | List entities (compact summaries), optionally filtered by domain |
| `get_state` | Get current state and attributes of one entity |
| `call_service` | Call any Home Assistant service (e.g. `light.turn_on`) |
| `run_automation` | Trigger a Home Assistant automation |
| `list_automations` | List available automations |

The tool surface is intentionally small and read-heavy. Actuation
(`call_service`, `run_automation`) should only be invoked when the user
explicitly asks for it.

`list_entities` and `list_automations` return **compact summaries**
(`entity_id`, `state`, `friendly_name`, `unit_of_measurement`) instead of the
raw Home Assistant state payload — on large instances the raw payload can
exceed a megabyte of JSON. Use `get_state` for the full attributes of any
single entity.

## Configuration

The server resolves credentials **per request**, so one deployment can serve
many users (multi-tenant). Each request may carry:

| Header | Purpose |
|---|---|
| `X-Home-Assistant-Url` | Base URL of the user's Home Assistant instance |
| `Authorization: Bearer <token>` (or `X-Home-Assistant-Token`) | Long-lived access token (HA profile → Security → Long-Lived Access Tokens) |

Environment variables are still supported as a fallback for local,
single-user use:

| Variable | Required | Description |
|---|---|---|
| `HA_URL` | local fallback | Base URL when the request supplies no `X-Home-Assistant-Url` |
| `HA_TOKEN` | local fallback | Token when the request supplies none |
| `HA_VERIFY_SSL` | no | Set `false` for self-signed certs (default `true`) |
| `HA_MCP_TRANSPORT` | no | `stdio` (default) or `http` |
| `HA_MCP_HOST` / `HA_MCP_PORT` | no | HTTP bind address (default `0.0.0.0:8000`) |
| `HA_MCP_READ_ONLY` | no | `true` (default) denies actuation; set `false` to allow service calls and automation triggers. Unparsable values fail closed to read-only. |

### Read-only mode

The connector **defaults to read-only**: `call_service` and `run_automation`
refuse to run unless actuation is explicitly enabled. This makes pilot
deployments safe by default — agents can discover and inspect the smart
home but cannot actuate devices.

- Enable actuation with `HA_MCP_READ_ONLY=false`.
- A per-request `X-Home-Assistant-ReadOnly: true|false` header overrides the
  environment setting (useful for per-user policies in multi-tenant setups).
- Unparsable or missing values fail closed to read-only.

**Never commit or log your token.** The token grants full control of your
Home Assistant instance. For multi-tenant deployments, do **not** set
`HA_URL`/`HA_TOKEN` in the environment — require per-request headers instead.

## Local development

```bash
python -m venv .venv
.venv/bin/pip install -e .
HA_URL=http://localhost:8123 HA_TOKEN=xxx python -m ha_mcp
```

Installing the package (`pip install -e .`) puts `ha_mcp` on the import path
and provides an `ha-mcp` console script, so the tests run directly:
`python tests/test_client.py` (no `PYTHONPATH=.` workaround).

By default the server speaks stdio (for local agent testing). For remote
deployment use the streamable HTTP transport:

```bash
HA_URL=... HA_TOKEN=... HA_MCP_TRANSPORT=http python -m ha_mcp.server
```

The streamable HTTP transport listens on `0.0.0.0:8000` by default in a
container; set `HA_MCP_HOST`/`HA_MCP_PORT` to change this. **Always place the
server behind TLS and an authenticating reverse proxy before exposing it.**

## Docker

```bash
docker build -t ha-mcp-connector .
docker run --rm -p 8000:8000 -e HA_URL=... -e HA_TOKEN=... ha-mcp-connector
```

## Registering as a Mistral connector

Once the server is reachable over HTTPS:

1. In the Mistral platform, create a custom MCP connector pointing at the
   server URL.
2. Suggested metadata (mirroring the existing Homey connector):
   - **name**: `home_assistant`
   - **protocol**: `mcp`
   - **auth**: credential header `Authorization: Bearer <HA_TOKEN>`
   - **title**: `Home Assistant`
   - **description**: "Check and control your Home Assistant smart home
     devices, and trigger automations."
3. Keep visibility private/user-scoped while testing, then widen if desired.

After registration, tools appear under the connector (e.g.
`home_assistant_list_entities`) and users enable it through the standard
connector enablement flow.

| `HA_MCP_ALLOWED_HOSTS` | no | Comma-separated Host header values permitted by the HTTP transport's DNS-rebinding protection when deployed behind a reverse proxy/tunnel (e.g. `ha-mcp.yourdomain.com`). Unset disables the Host check (loopback/local use). |
