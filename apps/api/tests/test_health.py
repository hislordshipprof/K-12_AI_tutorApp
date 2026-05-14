"""Smoke tests for the health endpoints."""

from __future__ import annotations

from typing import Any


def test_root(client: Any) -> None:
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "K-12 AI Tutor API"
    assert body["version"] == "0.1.0"


def test_health_ok(client: Any) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "models" in body
    # All five models should be exposed.
    assert set(body["models"]).issuperset({"text", "vision", "live", "pro", "embed"})
    assert body["models"]["text"].startswith("gemini-")


def test_health_includes_request_id_header(client: Any) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.headers.get("X-Request-ID")


def test_authed_health_requires_auth(client: Any) -> None:
    r = client.get("/v1/healthz")
    assert r.status_code == 401


def test_authed_health_dev_header(client: Any, dev_headers: dict[str, str]) -> None:
    r = client.get("/v1/healthz", headers=dev_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["user_id"] == dev_headers["X-Dev-User-Id"]


def test_courses_public(client: Any) -> None:
    r = client.get("/v1/courses")
    assert r.status_code == 200
    courses = r.json()
    assert isinstance(courses, list)
    assert len(courses) >= 1
    assert "slug" in courses[0]
