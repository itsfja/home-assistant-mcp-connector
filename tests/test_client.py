"""Offline tests for the HA client and tool definitions against a mock API."""

import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

os.environ["HA_URL"] = "http://127.0.0.1:8199"
os.environ["HA_TOKEN"] = "test-token"

STATES = [
    {"entity_id": "light.living_room", "state": "on", "attributes": {"brightness": 200}},
    {"entity_id": "switch.pump", "state": "off", "attributes": {}},
    {"entity_id": "automation.good_morning", "state": "off", "attributes": {}},
]
CALLED = []


class MockHA(BaseHTTPRequestHandler):
    def _send(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def do_GET(self):
        if self.path == "/api/states":
            self._send(200, STATES)
        elif self.path.startswith("/api/states/"):
            eid = self.path[len("/api/states/"):]
            match = [s for s in STATES if s["entity_id"] == eid]
            if match:
                self._send(200, match[0])
            else:
                self._send(404, {"message": "not found"})
        else:
            self._send(404, {"message": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        CALLED.append((self.path, body))
        self._send(200, [{"ok": True}])

    def log_message(self, *a):
        pass


class FakeCtx:
    def __init__(self, headers):
        self.headers = headers


def test_all():
    server = HTTPServer(("127.0.0.1", 8199), MockHA)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        from ha_mcp.client import HomeAssistantClient, HomeAssistantError

        c = HomeAssistantClient("http://127.0.0.1:8199", "test-token")
        assert len(c.get_states()) == 3
        assert len(c.get_states("light")) == 1
        assert c.get_state("light.living_room")["state"] == "on"
        c.call_service("light", "turn_on", {"entity_id": "light.living_room"})
        assert CALLED[-1] == ("/api/services/light/turn_on", {"entity_id": "light.living_room"})
        autos = c.get_automations()
        assert len(autos) == 1 and autos[0]["entity_id"] == "automation.good_morning"
        c.trigger_automation("automation.good_morning")
        assert CALLED[-1] == ("/api/services/automation/trigger", {"entity_id": "automation.good_morning"})

        try:
            HomeAssistantClient("", "")
            raise AssertionError("expected HomeAssistantError for missing credentials")
        except HomeAssistantError:
            pass

        import ha_mcp.server as srv
        from ha_mcp.server import (
            ReadOnlyError,
            _client,
            _compact_entity,
            _is_read_only,
            _require_actuation,
        )

        # --- single-user client from env config ---
        client = _client()
        assert client.base_url == "http://127.0.0.1:8199", client.base_url
        assert client.token == "test-token", client.token

        url_backup = os.environ.pop("HA_URL")
        try:
            _client()
            raise AssertionError("expected HomeAssistantError when HA_URL unset")
        except HomeAssistantError:
            pass
        finally:
            os.environ["HA_URL"] = url_backup

        # --- compact summaries ---
        compact = _compact_entity(STATES[0])
        assert compact in (
            {"entity_id": "light.living_room", "state": "on"},
            {"entity_id": "light.living_room", "state": "on", "friendly_name": "Living Room"},
        ), compact
        assert "attributes" not in compact
        assert "brightness" not in compact

        big_attrs = {f"k{i}": "x" * 100 for i in range(50)}
        big_attrs["friendly_name"] = "Big Entity"
        big = _compact_entity({"entity_id": "sensor.big", "state": "1", "attributes": big_attrs})
        assert big == {"entity_id": "sensor.big", "state": "1", "friendly_name": "Big Entity"}

        tools = {t.name for t in asyncio.run(srv.mcp.list_tools())}
        assert tools == {"list_entities", "get_state", "call_service", "list_automations", "run_automation"}, tools

        # --- read-only mode ---
        ctx_plain = FakeCtx({})
        ctx_true = FakeCtx({"X-Home-Assistant-ReadOnly": "true"})
        ctx_false = FakeCtx({"x-home-assistant-readonly": "false"})

        os.environ.pop("HA_MCP_READ_ONLY", None)
        assert _is_read_only(ctx_plain) is True, "default must be fail-closed read-only"
        assert _is_read_only(ctx_true) is True
        assert _is_read_only(ctx_false) is False

        os.environ["HA_MCP_READ_ONLY"] = "not-a-bool"
        assert _is_read_only(ctx_plain) is True, "unparsable value must fail closed"

        os.environ["HA_MCP_READ_ONLY"] = "false"
        assert _is_read_only(ctx_plain) is False
        assert _is_read_only(ctx_true) is True, "per-request header must override env"

        os.environ["HA_MCP_READ_ONLY"] = "true"
        try:
            _require_actuation(ctx_plain)
            raise AssertionError("expected ReadOnlyError in read-only mode")
        except ReadOnlyError:
            pass

        print("All client/tool tests passed.")
    finally:
        os.environ.pop("HA_MCP_READ_ONLY", None)
        server.shutdown()


if __name__ == "__main__":
    test_all()
