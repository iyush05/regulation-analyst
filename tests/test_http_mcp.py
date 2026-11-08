"""Exercise the mounted transport, credentials, isolation and research behavior."""

import json

import anyio
import httpx
import pytest
from fastapi.testclient import TestClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import ValidationError

from regulation_analyst.api import Settings, create_app

ADMIN = "admin-test-token-0123456789"
ALICE = "alice-research-test-token-0123456789"
BOB = "bob-research-test-token-012345678901"
LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}


def settings(store, **kwargs):
    return Settings(
        database=store.path,
        token=ADMIN,
        mcp_allowed_hosts=["testserver"],
        mcp_tokens={"alice": ALICE, "bob": BOB},
        **kwargs,
    )


def headers(token=ALICE):
    return {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"}


def test_real_sdk_client_uses_hosted_tools_and_resources(store):
    async def run():
        app = create_app(settings(store))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), headers=headers()
            ) as client:
                async with streamable_http_client("http://testserver/mcp/", http_client=client) as (
                    read,
                    write,
                    _,
                ):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        assert len(tools.tools) == 10
                        assert all(tool.annotations.readOnlyHint for tool in tools.tools)
                        assert "ingest_company" not in {tool.name for tool in tools.tools}
                        result = await session.call_tool(
                            "answer_question", {"question": "Infosys operating margin FY25"}
                        )
                        assert not result.isError
                        assert result.structuredContent["status"] == "ok"
                        row = result.structuredContent["data"]["rows"][0]
                        assert row["calculation"]["display_value"] == "21.12"
                        coverage = await session.read_resource("research://coverage")
                        assert "infosys" in coverage.contents[0].text

    anyio.run(run)


def test_mcp_credentials_do_not_grant_rest_or_admin_access(store):
    with TestClient(create_app(settings(store))) as client:
        for token in (None, "wrong", ADMIN):
            response = client.post("/mcp/", headers=headers(token) if token else {})
            assert response.status_code == 401
            assert response.headers["www-authenticate"].startswith("Bearer")
        for path in ("/api/companies", "/api/jobs"):
            assert client.get(path, headers=headers()).status_code == 401
        for path in ("/api/ingest", "/api/agent", "/api/ingest/upload"):
            assert client.post(path, headers=headers(), json={}).status_code == 401
        assert client.get("/api/companies", headers=headers(ADMIN)).status_code == 200
        assert client.get("/api/health").status_code == 200


def test_transport_rejects_untrusted_hosts_and_origins(store):
    with TestClient(create_app(settings(store))) as client:
        response = client.post(
            "/mcp/", headers={**headers(), "Host": "attacker.example"}, json=LIST
        )
        assert response.status_code == 421
        response = client.post(
            "/mcp/", headers={**headers(), "Origin": "https://attacker.example"}, json=LIST
        )
        assert response.status_code == 403


def test_limits_are_per_credential_and_recover_after_window(store, monkeypatch):
    from types import SimpleNamespace

    from regulation_analyst import http_mcp

    now = [100.0]
    monkeypatch.setattr(http_mcp, "time", SimpleNamespace(monotonic=lambda: now[0]))
    with TestClient(create_app(settings(store, mcp_requests_per_minute=1))) as client:
        assert client.post("/mcp/", headers=headers(), json=LIST).status_code == 200
        limited = client.post("/mcp/", headers=headers(), json=LIST)
        assert limited.status_code == 429
        assert limited.headers["retry-after"] == "60"
        assert client.post("/mcp/", headers=headers(BOB), json=LIST).status_code == 200
        now[0] += 61
        assert client.post("/mcp/", headers=headers(), json=LIST).status_code == 200


def test_disabled_and_revoked_access(store):
    disabled = create_app(Settings(database=store.path, token=ADMIN))
    with TestClient(disabled) as client:
        assert client.post("/mcp/", headers=headers()).status_code == 404
    config = settings(store)
    config.mcp_tokens.pop("alice")
    with TestClient(create_app(config)) as client:
        assert client.post("/mcp/", headers=headers()).status_code == 401
        assert client.post("/mcp/", headers=headers(BOB), json=LIST).status_code == 200


@pytest.mark.parametrize("tokens", [{"user": "short"}, {"alice": ALICE, "bob": ALICE}, {"": ALICE}])
def test_bad_credentials_fail_without_disclosing_secrets(store, tokens):
    with pytest.raises(ValidationError) as error:
        Settings(database=store.path, token=ADMIN, mcp_tokens=tokens)
    assert json.dumps(tokens) not in str(error.value)
    assert ALICE not in str(error.value)


def test_admin_token_cannot_be_reused_for_mcp(store):
    with pytest.raises(ValidationError, match="distinct from the API token"):
        Settings(database=store.path, token=ALICE, mcp_tokens={"alice": ALICE})
