# Home Assistant MCP Connector

An MCP (Model Context Protocol) server that exposes Home Assistant to AI agents
such as Mistral's Vibe. Once deployed and registered as a custom MCP connector,
agents can discover your smart home entities, inspect their state, call
services (lights, switches, climate...), and trigger automations — on request
only, never proactively.

## Tools exposed

| Tool | Purpose |
|---|---|
| `list_entities` | List all entities, optionally filtered by domain |
| `get_state` | Get current state and attributes of one entity |
| `call_service` | Call any Home Assistant service (e.g. `light.turn_on`) |
| `run_automation` | Trigger a Home Assistant automation |
| `list_automations` | List available automations |

The tool surface is intentionally small and read-heavy. Actuation
(`call_service`, `run_automation`) should only be invoked when the user
explicitly asks for it.

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

**Never commit or log your token.** The token grants full control of your
Home Assistant instance. For multi-tenant deployments, do **not** set
`HA_URL`/`HA_TOKEN` in the environment — require per-request headers instead.

## Local development

```bash
pip install -r requirements.txt
HA_URL=http://localhost:8123 HA_TOKEN=xxx python -m ha_mcp.server
```

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
