"""MCP server exposing Home Assistant tools to AI agents."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from mcp.server.mcpserver import MCPServer

from .client import HomeAssistantClient, HomeAssistantError

mcp = MCPServer(
    name="home-assistant",
    title="Home Assistant",
    description=(
        "Check and control your Home Assistant smart home devices, "
        "and trigger automations."
    ),
)


def _client() -> HomeAssistantClient:
    return HomeAssistantClient()


@mcp.tool()
def list_entities(domain: str | None = None) -> list[dict[str, Any]]:
    """List Home Assistant entities, optionally filtered by domain.

    Args:
        domain: Optional domain filter such as light, switch, climate,
            sensor, automation. Omit to list everything.
    """
    return _client().get_states(domain)


@mcp.tool()
def get_state(entity_id: str) -> dict[str, Any]:
    """Get the current state and attributes of one entity.

    Args:
        entity_id: Entity ID such as light.living_room.
    """
    return _client().get_state(entity_id)


@mcp.tool()
def call_service(
    domain: str, service: str, data: dict[str, Any] | None = None
) -> Any:
    """Call a Home Assistant service. Only use when the user explicitly asks.

    Args:
        domain: Service domain, e.g. light, switch, climate, media_player.
        service: Service name, e.g. turn_on, turn_off, set_temperature.
        data: Optional service payload, e.g. {"entity_id": "light.living_room"}.
    """
    return _client().call_service(domain, service, data)


@mcp.tool()
def list_automations() -> list[dict[str, Any]]:
    """List Home Assistant automations with their entity IDs and state."""
    return _client().get_automations()


@mcp.tool()
def run_automation(entity_id: str) -> Any:
    """Trigger a Home Assistant automation. Only use when the user explicitly asks.

    Args:
        entity_id: Automation entity ID such as automation.good_morning.
    """
    return _client().trigger_automation(entity_id)


def main() -> None:
    transport = os.environ.get("HA_MCP_TRANSPORT", "stdio")
    if transport == "http":
        host = os.environ.get("HA_MCP_HOST", "0.0.0.0")
        port = int(os.environ.get("HA_MCP_PORT", "8000"))
        asyncio.run(
            mcp.run_streamable_http_async(host=host, port=port)
        )
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    try:
        main()
    except HomeAssistantError as exc:
        raise SystemExit(str(exc)) from exc
