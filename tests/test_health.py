"""Smoke test: the app can start, and /health reaches both MCP servers.

This runs without an API key, so CI never needs a secret to prove the app boots.
"""

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_reports_both_mcp_servers():
    # "with" starts the app properly, which also starts the MCP servers.
    with TestClient(create_app()) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["mcp"]["policy"]["status"] == "ok"
    assert body["mcp"]["hr"]["status"] == "ok"
    assert "search_policy_documents" in body["mcp"]["policy"]["tools"]


def test_health_never_leaks_the_key():
    with TestClient(create_app()) as client:
        body = client.get("/health").text
    assert "sk-ant" not in body
