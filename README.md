# Home Assistant MCP Connector

An MCP (Model Context Protocol) server that exposes **one** Home Assistant
instance to AI agents such as Mistral's Vibe. Once deployed and registered as
a custom MCP connector, agents can discover entities, inspect their state,
call services (lights, switches, climate...), and trigger automations — on
request only, never proactively.

**Single-user by design:** the connector is configured server-side with one
Home Assistant URL and one access token. Requests carry no credentials.

## Tools exposed

| Tool | Purpose |
|---|---|
| `list_entities` | List entities (compact summaries), optionally filtered by domain |
| `get_state` | Get current state and attributes of one entity |
| `call_service` | Call any Home Assistant service (e.g. `light.turn_on`) |
| `list_automations` | List available automations |
| `run_automation` | Trigger a Home Assistant automation |

The tool surface is intentionally small and read-heavy. Actuation
(`call_service`, `run_automation`) should only be invoked when the user
explicitly asks for it.

`list_entities` and `list_automations` return **compact summaries**
(`entity_id`, `state`, `friendly_name`, `unit_of_measurement`) instead of the
raw Home Assistant state payload — on large instances the raw payload can
exceed a megabyte of JSON. Use `get_state` for the full attributes of any
single entity.

## Configuration

The server is configured via environment variables (see `.env.example`):

| Variable | Required | Description |
|---|---|---|
| `HA_URL` | yes | Base URL of your Home Assistant instance, e.g. `http://192.168.1.50:8123` or your Nabu Casa URL |
| `HA_TOKEN` | yes | Long-lived access token (HA profile → Security → Long-Lived Access Tokens) |
| `HA_VERIFY_SSL` | no | Set `false` for self-signed certs (default `true`) |
| `HA_MCP_TRANSPORT` | no | `stdio` (default) or `http` |
| `HA_MCP_HOST` / `HA_MCP_PORT` | no | HTTP bind address (default `0.0.0.0:8000`) |
| `HA_MCP_READ_ONLY` | no | `true` (default) denies actuation; set `false` to allow service calls and automation triggers. Unparsable values fail closed to read-only. |
| `HA_MCP_ALLOWED_HOSTS` | no | Comma-separated Host header values permitted by the HTTP transport's DNS-rebinding protection when deployed behind a reverse proxy/tunnel (e.g. `ha-mcp.yourdomain.com`). Unset disables the Host check (loopback/local use). |

**Never commit or log your token.** The token grants full control of your
Home Assistant instance.

### Read-only mode

The connector **defaults to read-only**: `call_service` and `run_automation`
refuse to run unless actuation is explicitly enabled. This makes deployments
safe by default — agents can discover and inspect the smart home but cannot
actuate devices.

- Enable actuation with `HA_MCP_READ_ONLY=false`.
- A per-request `X-Home-Assistant-ReadOnly: true|false` header overrides the
  environment setting.
- Unparsable or missing values fail closed to read-only.

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
HA_URL=... HA_TOKEN=... HA_MCP_TRANSPORT=http python -m ha_mcp
```

The streamable HTTP transport listens on `0.0.0.0:8000` by default in a
container; set `HA_MCP_HOST`/`HA_MCP_PORT` to change this. **Always place the
server behind TLS and an authenticating reverse proxy before exposing it.**

## Docker

```bash
docker build -t ha-mcp-connector .
docker run --rm -p 8000:8000 \
  -e HA_URL=http://192.168.1.50:8123 \
  -e HA_TOKEN=xxx \
  ha-mcp-connector
```

## Registering as a Mistral connector

Once the server is reachable over HTTPS (e.g. via a Cloudflare Tunnel):

1. In the Mistral platform, add a custom MCP connector pointing at the
   server URL (the `/mcp` endpoint).
2. Suggested metadata:
   - **name**: `home_assistant`
   - **protocol**: `mcp`
   - **title**: `Home Assistant`
   - **description**: "Check and control your Home Assistant smart home
     devices, and trigger automations."
   - **authentication**: since credentials are server-side, the connector
     can be registered with No Authentication — but protect the endpoint
     itself (see below).
3. Protect the endpoint: put Cloudflare Access (or an equivalent
   authenticating proxy) in front of the server and configure the connector's
   connection header to pass the proxy's credentials (e.g.
   `CF-Access-Client-Id`/`CF-Access-Client-Secret`). Without this, anyone
   who discovers the URL can drive your Home Assistant.
4. Keep the connector private/user-scoped: a shared connector definition is
   effectively shared access to your home.

After registration, tools appear under the connector (e.g.
`home_assistant_list_entities`) and users enable it through the standard
connector enablement flow.
