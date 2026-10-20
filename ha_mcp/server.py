"""MCP server exposing Home Assistant tools to AI agents.

Credentials are resolved per request in this order:
1. Per-request headers: `X-Home-Assistant-Url` and the standard
   `Authorization: Bearer <token>` (or `X-Home-Assistant-Token`).
2. Environment variables `HA_URL` / `HA_TOKEN` (single-user local use).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from .client import HomeAssistantClient, HomeAssistantError

mcp = MCPServer(
    name="home-assistant",
    title="Home Assistant",
    description=(
        "Check and control your Home Assistant smart home devices, "
        "and trigger automations."
    ),
)

HA_URL_HEADER = "x-home-assistant-url"
HA_TOKEN_HEADER = "x-home-assistant-token"
HA_READ_ONLY_HEADER = "x-home-assistant-readonly"

READ_ONLY_ENV = "HA_MCP_READ_ONLY"


class ReadOnlyError(ToolError):
    """Raised when actuation is attempted while read-only mode is active."""


def _read_only_from_env() -> bool:
    """Fail-closed: unparsable or unset values deny actuation."""
    return os.environ.get(READ_ONLY_ENV, "true").strip().lower() not in ("false", "0", "no", "off")


def _is_read_only(ctx: Context) -> bool:
    """Per-request override wins over the environment; otherwise fail-closed."""
    headers = ctx.headers or {}
    override = ""
    for key, value in headers.items():
        if key.lower() == HA_READ_ONLY_HEADER:
            override = value.strip()
            break
    if override:
        return override.lower() not in ("false", "0", "no", "off")
    return _read_only_from_env()


def _require_actuation(ctx: Context) -> None:
    if _is_read_only(ctx):
        raise ReadOnlyError(
            "This connector is in read-only mode; service calls and "
            "automation triggers are disabled."
        )


def _client_from_headers(ctx: Context) -> HomeAssistantClient:
    headers = ctx.headers or {}

    def header_value(*names: str) -> str:
        for name in names:
            for key, value in headers.items():
                if key.lower() == name:
                    return value.strip()
        return ""

    base_url = header_value(HA_URL_HEADER)
    token = header_value(HA_TOKEN_HEADER)
    if not token:
        auth = header_value("authorization")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()

    if not base_url:
        base_url = os.environ.get("HA_URL", "")
    if not token:
        token = os.environ.get("HA_TOKEN", "")
    verify_ssl = os.environ.get("HA_VERIFY_SSL", "true").lower() != "false"

    return HomeAssistantClient(base_url, token, verify_ssl)


@mcp.tool()
async def list_entities(
    domain: str | None = None, ctx: Context = None
) -> list[dict[str, Any]]:
    """List Home Assistant entities, optionally filtered by domain.

    Args:
        domain: Optional domain filter such as light, switch, climate,
            sensor, automation. Omit to list everything.
    """
    return _client_from_headers(ctx).get_states(domain)


@mcp.tool()
async def get_state(entity_id: str, ctx: Context = None) -> dict[str, Any]:
    """Get the current state and attributes of one entity.

    Args:
        entity_id: Entity ID such as light.living_room.
    """
    return _client_from_headers(ctx).get_state(entity_id)


@mcp.tool()
async def call_service(
    domain: str,
    service: str,
    data: dict[str, Any] | None = None,
    ctx: Context = None,
) -> Any:
    """Call a Home Assistant service. Only use when the user explicitly asks.

    Args:
        domain: Service domain, e.g. light, switch, climate, media_player.
        service: Service name, e.g. turn_on, turn_off, set_temperature.
        data: Optional service payload, e.g. {"entity_id": "light.living_room"}.
    """
    _require_actuation(ctx)
    return _client_from_headers(ctx).call_service(domain, service, data)


@mcp.tool()
async def list_automations(ctx: Context = None) -> list[dict[str, Any]]:
    """List Home Assistant automations with their entity IDs and state."""
    return _client_from_headers(ctx).get_automations()


@mcp.tool()
async def run_automation(entity_id: str, ctx: Context = None) -> Any:
    """Trigger a Home Assistant automation. Only use when the user explicitly asks.

    Args:
        entity_id: Automation entity ID such as automation.good_morning.
    """
    _require_actuation(ctx)
    return _client_from_headers(ctx).trigger_automation(entity_id)


def main() -> None:
    transport = os.environ.get("HA_MCP_TRANSPORT", "stdio")
    if transport == "http":
        host = os.environ.get("HA_MCP_HOST", "0.0.0.0")
        port = int(os.environ.get("HA_MCP_PORT", "8000"))
        security: TransportSecuritySettings | None = None
        allowed_hosts = [
            h.strip()
            for h in os.environ.get("HA_MCP_ALLOWED_HOSTS", "").split(",")
            if h.strip()
        ]
        if allowed_hosts:
            security = TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=allowed_hosts,
            )
        asyncio.run(
            mcp.run_streamable_http_async(
                host=host, port=port, transport_security=security
            )
        )
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    try:
        main()
    except HomeAssistantError as exc:
        raise SystemExit(str(exc)) from exc
