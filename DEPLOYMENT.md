# Deployment Guide — Proxmox LXC + Cloudflare Tunnel

This guide captures the complete, battle-tested deployment path for the
Home Assistant MCP connector, including every gotcha hit along the way.
Follow it top to bottom for a fresh deployment, or jump to
[Troubleshooting](#troubleshooting) when something breaks.

Architecture:

```
Mistral platform → Cloudflare (TLS + Access auth) → Tunnel → Proxmox LXC (ha-mcp) → Home Assistant
```

The connector is single-user: one Home Assistant instance, credentials held
server-side. Requests carry no credentials, so **Cloudflare Access is the
access control** — do not skip it.

---

## 1. Proxmox: create the LXC container

```bash
pveam update
pveam available | grep debian          # note the exact template name/version
pveam download local debian-13-standard_13.0-1_amd64.tar.zst
pct create 200 local:vztmpl/debian-13-standard_13.0-1_amd64.tar.zst \
  --hostname ha-mcp --unprivileged 1 --memory 512 --swap 0 \
  --rootfs local-lvm:2 --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --features nesting=1 --start 1
```

### Gotchas

- **Template reference syntax:** the template argument is ONE token:
  `storage:vztmpl/<filename>`. Common failures:
  - `local debian-...` (two words) → `400 too many arguments`
  - `local:ztmpl/...` (missing **v**) → `unable to parse directory volume name`
  - `local:debian-...` (missing `vztmpl/`) → `volume does not exist`
- **Template must be downloaded first:** `pct create` fails with
  `volume 'local:vztmpl/...' does not exist` if you never ran
  `pveam download`. Check with `pveam list local`, and make sure it's on the
  storage you reference (the web UI may have put it elsewhere).
- Debian 13 works fine; the template version number in the filename changes
  over time — always copy the exact name from `pveam available`.
- A failed `pct create` cleans up after itself; if it doesn't,
  `pct stop 200 && pct destroy 200` before retrying.

## 2. Inside the container: get the code

```bash
pct enter 200
apt update && apt install -y python3 python3-venv git openssh-client curl
```

The repo is **private**. Recommended: a read-only **deploy key** (no token
string stored in the container):

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519
cat ~/.ssh/id_ed25519.pub    # paste into GitHub: repo → Settings → Deploy keys (read-only)
git clone git@github.com:itsfja/home-assistant-mcp-connector.git /opt/ha-mcp
```

Then:

```bash
cd /opt/ha-mcp
python3 -m venv .venv
.venv/bin/pip install -e .
python tests/test_client.py     # expect: All client/tool tests passed.
```

### Gotchas

- **HTTPS clone fails with `Password authentication is not supported`:**
  GitHub requires SSH keys or tokens for private repos — the deploy-key
  flow above avoids the problem entirely.
- **`ModuleNotFoundError: No module named 'ha_mcp'` when running tests:**
  fixed by installing the package (`pip install -e .`); tests run directly
  with no `PYTHONPATH=.` prefix.
- **`curl: command not found`:** minimal container templates don't include
  curl — `apt install -y curl` first.

## 3. systemd service

`/etc/systemd/system/ha-mcp.service`:

```ini
[Unit]
Description=Home Assistant MCP connector
After=network-online.target

[Service]
WorkingDirectory=/opt/ha-mcp
Environment=HA_MCP_TRANSPORT=http
Environment=HA_MCP_HOST=127.0.0.1
Environment=HA_MCP_PORT=8000
Environment=HA_URL=http://192.168.x.x:8123
Environment=HA_TOKEN=your-long-lived-token
ExecStart=/opt/ha-mcp/.venv/bin/python -m ha_mcp
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now ha-mcp
systemctl status ha-mcp        # expect: active (running)
```

### Gotchas

- **`systemctl edit` changes don't take effect:** editing the drop-in only
  changes the config; the **running process keeps its old environment** until
  you `systemctl restart ha-mcp`. Verify with
  `systemctl show ha-mcp -p Environment` AND check
  `ActiveEnterTimestamp` is recent — a stale timestamp means you forgot the
  restart.
- The service binds `127.0.0.1` only — the tunnel talks to it via loopback,
  so nothing else on the LAN can reach it directly.

## 4. Home Assistant token

HA web UI → profile (bottom-left) → **Security** → Long-Lived Access Tokens →
Create Token. **Copy it immediately — it is shown once.**

### Important

- Use a dedicated token for this connector, not your session token.
- Even better: issue it from a restricted HA user that only sees the
  devices/areas you want the agent to touch.
- The token grants full control of whatever user issued it. Never commit or
  log it.

## 5. Cloudflare Tunnel (no inbound ports)

```bash
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared
chmod +x /usr/local/bin/cloudflared
cloudflared tunnel login                 # browser flow; pick the RIGHT domain
cloudflared tunnel create ha-mcp         # note the tunnel UUID
mkdir -p /etc/cloudflared
nano /etc/cloudflared/config.yml
```

`/etc/cloudflared/config.yml`:

```yaml
tunnel: <tunnel-uuid>
credentials-file: /root/.cloudflared/<tunnel-uuid>.json
ingress:
  - hostname: ha-mcp.yourdomain.com
    service: http://127.0.0.1:8000
  - service: http_status:404
```

```bash
cloudflared tunnel route dns ha-mcp ha-mcp.yourdomain.com
cloudflared service install
systemctl enable --now cloudflared
```

### Gotchas

- **`cloudflared` not on PATH:** if `command not found`, fully qualify as
  `/usr/local/bin/cloudflared ...` — worked in practice.
- **`cloudflared service install` was never run** → the tunnel exists on
  Cloudflare's side but nothing serves it. Symptom from outside:
  **HTTP 530, `error code: 1033`** (Argo Tunnel error = tunnel not
  connected). Check `systemctl status cloudflared`; look for
  `Registered tunnel connection` lines in the journal.
- **Wrong domain authorized during `tunnel login` or `route dns`:** fully
  recoverable. Re-run `cloudflared tunnel login` and pick the right zone;
  delete the bad CNAME in the Cloudflare DNS dashboard; re-run
  `cloudflared tunnel route dns` with the right hostname; fix the
  `hostname:` line in `config.yml`; `systemctl restart cloudflared`.
- The tunnel ID and credentials filename in `config.yml` must match
  `cloudflared tunnel list` exactly. If you recreate a tunnel, update both
  lines.

## 6. Cloudflare Access (the actual access control)

Since the connector serves one instance with server-side credentials and
requests carry none, **the Access layer is the only thing stopping randos
on the internet from driving your home.** Configure it in this exact
order; each step below was validated in a production deployment.

### 6.1 Create the application

Cloudflare dashboard → **Zero Trust** → Access → Applications →
Add an application → **Self-hosted and private** → **Public DNS**
(first visit forces onboarding; the **Free** plan suffices):

- **Name:** `ha-mcp`
- **Public hostname:** subdomain `ha-mcp`, domain `yourdomain.com`,
  **path empty** (an explicit `/` can behave differently from blank)

### 6.2 Create the service token (for the Mistral platform)

Access → **Service credentials → Service Tokens** → Create Service Token →
copy the **Client ID** (ends in `.access`) and **Client Secret** (shown
**once** — store it in a password manager immediately).

### 6.3 Create the policies — and get the Action right

This is the step that silently eats hours if done wrong.

- **Token policy** (for the platform's machine calls):
  Action **Service Auth** — *not* Allow — Include → Service Token →
  select your token. Per Cloudflare's docs, anything else makes Access
  prompt the caller for identity-provider login, which a machine cannot
  do: every request 302s to the login page, no matter how correct the
  credentials are.
- **Email policy** (for you in a browser):
  Action **Allow** → Include → Emails → your address. Login is one-time-PIN
  to your inbox.

### 6.4 Attach the policies to the application

Policies are **reusable objects in a library** — creating one does nothing
until it is **attached to the application**: open the `ha-mcp` app →
Access policies → **Add existing policy** → select both. A policy showing
"Used by applications: 0" is a red flag you have missed this step.

Then the Mistral connector carries the pair as headers:
`CF-Access-Client-Id: <id>` and `CF-Access-Client-Secret: <secret>`.

### 6.5 The verification pair (do this before touching Mistral)

From a machine with real curl (the Proxmox host works well):

```bash
# Bare request - must be 302 (the bouncer is on the door)
curl -s -o /dev/null -w "%{http_code}" https://ha-mcp.yourdomain.com/mcp

# Credentialed request - must be 200 (the token passes)
curl -s -o /dev/null -w "%{http_code}" \
  -H "CF-Access-Client-Id: <id>" -H "CF-Access-Client-Secret: <secret>" \
  -X POST -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}' \
  https://ha-mcp.yourdomain.com/mcp
```

Any other combination means a layer is misconfigured. Also useful: the
token's **Last Seen** field in Service Auth ticks only when credentials
actually match — "Not Seen Yet" after a credentialed probe means the pair
never matched a token (wrong ID, dead token, or truncated secret).

### 6.6 Header hygiene

Exactly one space after the header colon. A stray double-space becomes
part of the value and fails silently. When a credential has transited any
chat, ticket, or screen-share, **rotate it**: Service Tokens → the token →
three dots → Rotate secret (with a grace period so you can update
consumers before the old secret dies).

## 7. Register in Mistral

Mistral platform → Connectors → **+ Add Connector** → **Add custom connector**:

- **Server:** `https://ha-mcp.yourdomain.com/mcp`
- **Title:** `Home Assistant`
- **Authentication:** Custom → connection header
  `CF-Access-Client-Id: <value>`, and put `CF-Access-Client-Secret` in the
  advanced/global headers if the form supports it (see gotcha below)
- Validate. **Read this first:** the form probes the URL *before*
  authentication is configured, and Access correctly blocks unauthenticated
  probes — so validation fails while your security is working as designed.
  Create the connector during a temporary **Bypass window**:

  1. Zero Trust → Policies → create a reusable policy `temporary-bypass`,
     **Action: Bypass**, Include: **Everyone**
  2. Attach it to the `ha-mcp` app (Bypass evaluates first, so it wins)
  3. Confirm with the bare curl from §6.5 — it must now return **400**
  4. Immediately create the connector in Mistral — the probe passes
  5. **Remove the bypass policy from the app** and confirm the bare curl
     is 302 again
  6. Delete the bypass policy from the library

  The exposure window is a couple of minutes; the server answers anyone
  in that window, so do not wander off mid-task.

### Gotchas

- **`The server could not be reached at all`** — usually a placeholder URL
  (`yourdomain.com` literally), or DNS/tunnel problems (see 530 below).
- **`HTTP status other than 200/401/403`** — could be the Access login
  redirect (fix: send the service-token headers) or one of the errors in the
  troubleshooting table.
- **The UI may only offer ONE connection-header slot.** Workarounds:
  put the CF Access client ID in the connection header and secret in
  global headers if available; otherwise reconsider the proxy auth method
  (e.g. a single shared-secret header checked by a Worker).
- **Tools appear only in NEW sessions.** A Vibe conversation that started
  before the connector existed cannot see its tools. Start a fresh chat to
  test.

## 8. First end-to-end test

In a **fresh** Vibe session: *"list my Home Assistant entities."*

Expect compact summaries. Actuation ("turn on X") is refused by default
(read-only); enable with `HA_MCP_READ_ONLY=false` when you trust it.

---

## Troubleshooting

Every error below was hit for real during deployment; the fixes are verified.

| Symptom | Cause | Fix |
|---|---|---|
| `400 too many arguments` from `pct create` | template given as two words | one token: `local:vztmpl/<file>` |
| `unable to parse directory volume name 'ztmpl/...'` | typo, missing `v` | `vztmpl` |
| `volume ... does not exist` | template not downloaded to that storage | `pveam list local`; `pveam download local <name>` |
| `Password authentication is not supported` on `git clone` | private repo over HTTPS | deploy key + SSH clone |
| `ModuleNotFoundError: ha_mcp` running tests | package not installed | `.venv/bin/pip install -e .` |
| `curl: command not found` | minimal template | `apt install -y curl` |
| `curl` in PowerShell prompts `Uri:` | `curl` is an alias for `Invoke-WebRequest` | use `curl.exe` (and escape JSON quotes `\"`) |
| `curl: (7) ... 127.0.1.1:443` **from inside the container** | container FQDN in `/etc/hosts` (`127.0.1.1`) shadows the real public DNS when container hostname == public hostname | edit `/etc/hosts` to keep only the short hostname; test from outside instead |
| `HTTP 530 / error code: 1033` | tunnel not connected: cloudflared service not installed/running | `cloudflared service install && systemctl enable --now cloudflared` |
| `HTTP 421 Misdirected Request — Invalid Host header` | MCP SDK DNS-rebinding protection rejects non-localhost Host headers | set `HA_MCP_ALLOWED_HOSTS=ha-mcp.yourdomain.com` and **restart** the service |
| Change made via `systemctl edit` but behavior unchanged | running process predates the edit | `systemctl restart ha-mcp`; check `ActiveEnterTimestamp` |
| `400 Bad Request: Missing session ID` on bare `GET /mcp` | **normal** streamable-HTTP MCP behavior | probe with a proper `initialize` POST instead |
| Mistral probe: "server could not be reached at all" | placeholder URL, or Cloudflare 530/421 in the way | real hostname; fix tunnel and Host header first |
| Connector registered but agent "can't find the tools" | session predates connector registration | start a new Vibe session |
| `list_entities` returns ~1 MB of JSON | large instance, raw payload | already fixed: compact summaries; use `domain` filter |
| Service-token request 302s forever; no audit entries; token "Not Seen Yet" | **policy Action is Allow, not Service Auth** — Access prompts machine callers for IdP login | set the token policy's Action to **Service Auth** (Cloudflare docs: "set the policy action to Service Auth; otherwise, Access will prompt for an identity provider login") |
| Policy configured correctly but has no effect | reusable policy exists in the library but is **not attached to the app** | app → Access policies → **Add existing policy**; check "Used by applications" >= 1 |
| Changed a policy but behavior unchanged | the edit was not saved (the Save control can sit below the fold) | scroll the full page; verify the change persisted after reload |
| Mistral form: "server was reachable, but MCP initialization failed" | form probes pre-auth; Access blocks unauthenticated probes (working as designed) | create the connector during a temporary Bypass window (§7), then remove it |
| Credentialed probe fails; Last Seen stays "Not Seen Yet" | pair doesn't match a token: wrong ID, disabled token, or truncated secret | compare the ID on the token's page character-for-character; rotate the secret if unsaved |
| Token page shows "Associated applications: 0" | the policy referencing the token is not attached to any app | attach the policy to the app (§6.4) |
| Deleting a service token is not offered | another object still references it | disable it instead — a disabled token cannot authenticate; delete later once unreferenced |


## Important notes

1. **Read-only is the default, fail-closed.** `call_service` and
   `run_automation` refuse until `HA_MCP_READ_ONLY=false`. Unparsable values
   also fail closed to read-only. Flip it deliberately.
2. **Cloudflare Access is not optional** in single-user mode. The server
   itself performs no authentication — Access is the only gate.
3. **Long-lived sessions over Cloudflare:** the streamable HTTP transport
   holds sessions; Cloudflare's proxy timeout (100 s default) can kill
   idle GET streams. If sessions drop, look at Access session lifetime and
   proxy timeouts.
4. **Token hygiene:** the HA token is a full-control credential for its
   issuing user. Dedicated token, restricted user, never committed, rotate
   if leaked (revoke in HA, update systemd, restart).
5. **Stale branches on the deployment box:** after merges, keep the
   container on `main` (`git checkout main && git pull`).
6. **GitHub auto-close gotcha:** an issue's `Closes #N` keyword only fires
   when the PR merges into the **default branch**. PRs merged into
   non-default branches (stacked PRs) will NOT close their issues and their
   content may not even reach `main` — verify with
   `git merge-base --is-ancestor <branch> main` before cleanup, and close
   orphaned issues manually with a reference comment.
