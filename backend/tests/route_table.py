"""A flattened view of the app's route table.

FastAPI defers router inclusion: ``app.routes`` holds ``_IncludedRouter``
mounts instead of flat ``APIRoute`` objects. This helper resolves both shapes
into one list so the security suites (route-registration, tenant isolation)
always see every route regardless of FastAPI's internal representation.
"""

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute


@dataclass(frozen=True)
class RouteInfo:
    path: str
    method: str
    dependant: Dependant


def iter_api_routes(app: FastAPI) -> list[RouteInfo]:
    infos: list[RouteInfo] = []

    def add(path: str, methods: Any, dependant: Dependant) -> None:
        for method in sorted(set(methods or ()) - {"HEAD", "OPTIONS"}):
            infos.append(RouteInfo(path=path, method=method, dependant=dependant))

    for route in app.routes:
        if isinstance(route, APIRoute):
            add(route.path, route.methods, route.dependant)
        elif hasattr(route, "effective_route_contexts"):
            for ctx in route.effective_route_contexts():
                add(ctx.path, ctx.methods, ctx.dependant)
    return infos
