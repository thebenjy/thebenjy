"""Shared test fixtures and fakes (no network, no real API keys)."""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from podsummary.config import OpenAIConfig


class FakeLLM:
    """Records calls and returns deterministic, inspectable output."""

    def __init__(self, response: str = "SUMMARY"):
        self.response = response
        self.calls: List[Dict[str, Any]] = []

    def complete(self, system: str, user: str, model: str, **kwargs) -> str:
        self.calls.append({"system": system, "user": user, "model": model, **kwargs})
        # Echo the model so tests can assert which model handled which stage.
        return f"{self.response} [{model}]"


class FakeResponse:
    def __init__(self, payload: Any, status: int = 200):
        self._payload = payload
        self.status_code = status

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    """Routes GET/POST to queued responses keyed by URL substring."""

    def __init__(self):
        self.get_routes: List[tuple[str, FakeResponse]] = []
        self.post_routes: List[tuple[str, FakeResponse]] = []
        self.requests: List[tuple[str, str, dict]] = []

    def add_get(self, url_contains: str, payload: Any, status: int = 200):
        self.get_routes.append((url_contains, FakeResponse(payload, status)))

    def add_post(self, url_contains: str, payload: Any, status: int = 200):
        self.post_routes.append((url_contains, FakeResponse(payload, status)))

    def get(self, url: str, **kwargs) -> FakeResponse:
        self.requests.append(("GET", url, kwargs))
        for frag, resp in self.get_routes:
            if frag in url:
                return resp
        raise AssertionError(f"no GET route for {url}")

    def post(self, url: str, **kwargs) -> FakeResponse:
        self.requests.append(("POST", url, kwargs))
        for frag, resp in self.post_routes:
            if frag in url:
                return resp
        raise AssertionError(f"no POST route for {url}")


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def openai_config() -> OpenAIConfig:
    return OpenAIConfig(episode_model="episode-model", period_model="period-model")


@pytest.fixture
def fixtures_dir(request) -> str:
    return str(request.path.parent / "fixtures")
