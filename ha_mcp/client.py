"""Thin Home Assistant REST API client used by the MCP tools."""

from __future__ import annotations

import os
from typing import Any

import requests


class HomeAssistantError(Exception):
    """Raised when the Home Assistant API returns an error."""


class HomeAssistantClient:
    def __init__(self) -> None:
        self.base_url = (os.environ.get("HA_URL") or "").rstrip("/")
        self.token = os.environ.get("HA_TOKEN") or ""
        self.verify_ssl = os.environ.get("HA_VERIFY_SSL", "true").lower() != "false"
        if not self.base_url or not self.token:
            raise RuntimeError(
                "HA_URL and HA_TOKEN environment variables must be set."
            )

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}{path}"
        try:
            resp = requests.request(
                method,
                url,
                headers=self._headers(),
                timeout=15,
                verify=self.verify_ssl,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise HomeAssistantError(f"Could not reach Home Assistant: {exc}") from exc
        if resp.status_code == 401:
            raise HomeAssistantError(
                "Home Assistant rejected the token (401). Check HA_TOKEN."
            )
        if resp.status_code == 404:
            raise HomeAssistantError(f"Not found: {path}")
        if not resp.ok:
            raise HomeAssistantError(
                f"Home Assistant error {resp.status_code}: {resp.text[:300]}"
            )
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    def get_states(self, domain: str | None = None) -> list[dict[str, Any]]:
        states = self._request("GET", "/api/states")
        if domain:
            states = [
                s for s in states if s["entity_id"].startswith(f"{domain}.")
            ]
        return states

    def get_state(self, entity_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/states/{entity_id}")

    def call_service(
        self, domain: str, service: str, data: dict[str, Any] | None = None
    ) -> Any:
        return self._request(
            "POST", f"/api/services/{domain}/{service}", json=data or {}
        )

    def get_automations(self) -> list[dict[str, Any]]:
        return self.get_states("automation")

    def trigger_automation(self, entity_id: str) -> Any:
        return self.call_service("automation", "trigger", {"entity_id": entity_id})
