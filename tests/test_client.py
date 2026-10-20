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


def test_all():
    server = HTTPServer(("127.0.0.1", 8199), MockHA)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        from ha_mcp.client import HomeAssistantClient

        c = HomeAssistantClient()
        assert len(c.get_states()) == 3
        assert len(c.get_states("light")) == 1
        assert c.get_state("light.living_room")["state"] == "on"
        c.call_service("light", "turn_on", {"entity_id": "light.living_room"})
        assert CALLED[-1] == ("/api/services/light/turn_on", {"entity_id": "light.living_room"})
        autos = c.get_automations()
        assert len(autos) == 1 and autos[0]["entity_id"] == "automation.good_morning"
        c.trigger_automation("automation.good_morning")
        assert CALLED[-1] == ("/api/services/automation/trigger", {"entity_id": "automation.good_morning"})

        import ha_mcp.server as srv
        tools = {t.name for t in asyncio.run(srv.mcp.list_tools())}
        assert tools == {"list_entities", "get_state", "call_service", "list_automations", "run_automation"}, tools
        print("All client/tool tests passed.")
    finally:
        server.shutdown()


if __name__ == "__main__":
    test_all()
