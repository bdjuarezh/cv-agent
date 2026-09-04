"""Estado construido una sola vez en el lifespan (carga costosa va en el lifespan, no por request),
expuesto como dependencia de FastAPI para poder sobreescribirlo en tests con `FakeProvider`
(`app.dependency_overrides[get_app_state] = ...`) sin tocar `app.state` directamente."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from fastapi import Request

from cv_agent.agent.tools import ToolContext
from cv_agent.providers.base import Provider
from cv_agent.state.response_store import ResponseStore


@dataclass
class AppState:
    tool_ctx: ToolContext
    system_prompt: str
    response_store: ResponseStore
    provider: Provider | None


def get_app_state(request: Request) -> AppState:
    return cast(AppState, request.app.state.cv_agent)
