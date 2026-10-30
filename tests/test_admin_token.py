"""hm-#862: an unset or default ADMIN_TOKEN must switch admin off, not open it."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from agentpool import config, server


def _req(token=None, body=None):
    headers = {} if token is None else {"x-admin-token": token}

    async def _json():
        return body if body is not None else {}

    return SimpleNamespace(headers=headers, json=_json)


def _status(route, request):
    resp = asyncio.run(route(request))
    return resp.status_code


@pytest.mark.parametrize("configured", ["change-me", ""])
def test_default_or_empty_token_disables_admin(monkeypatch, configured):
    monkeypatch.setattr(config, "ADMIN_TOKEN", configured)
    # Sending the default (or nothing) must not unlock anything.
    for sent in (configured, "change-me", None):
        assert server._admin_ok(_req(sent)) is False


def test_real_token_still_works(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_TOKEN", "a-real-long-secret")
    assert server._admin_ok(_req("a-real-long-secret")) is True
    assert server._admin_ok(_req("wrong")) is False
    assert server._admin_ok(_req(None)) is False


@pytest.mark.parametrize("token", [None, "change-me"])
def test_admin_routes_403_with_default_config(monkeypatch, token):
    monkeypatch.setattr(config, "ADMIN_TOKEN", "change-me")
    for route in (server.admin_reset, server.admin_purge_tier, server.admin_purge_handle):
        assert _status(route, _req(token, {"handle": "x"})) == 403


def test_register_non_free_tier_403_with_default_config(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_TOKEN", "change-me")
    resp = asyncio.run(server.register_route(_req("change-me", {"handle": "h", "tier": "pro"})))
    assert resp.status_code == 403
    assert "admin token required" in json.loads(resp.body)["error"]
