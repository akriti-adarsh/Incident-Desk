"""Service catalogue: the things incidents happen to."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.db import models
from incident_desk.enums import ServiceTier
from incident_desk.errors import ConflictError, NotFoundError


class ServiceNameTakenError(ConflictError):
    code = "service_name_taken"


class ServiceInUseError(ConflictError):
    code = "service_in_use"


async def list_services(session: AsyncSession, org: models.Organization) -> list[models.Service]:
    rows = await session.scalars(
        select(models.Service)
        .where(models.Service.org_id == org.id)
        .order_by(models.Service.name, models.Service.id)
    )
    return list(rows)


async def get_service(
    session: AsyncSession, org: models.Organization, service_id: UUID
) -> models.Service:
    """Org scope applied in the query itself; a foreign id is a plain 404."""
    service = await session.scalar(
        select(models.Service).where(
            models.Service.org_id == org.id, models.Service.id == service_id
        )
    )
    if service is None:
        raise NotFoundError("Service not found")
    return service


async def create_service(
    session: AsyncSession,
    org: models.Organization,
    *,
    name: str,
    description: str,
    owner_team: str,
    tier: ServiceTier,
) -> models.Service:
    service = models.Service(
        org_id=org.id, name=name, description=description, owner_team=owner_team, tier=tier
    )
    session.add(service)
    try:
        # SAVEPOINT around the flush: on constraint failure only this
        # statement is rolled back and the session stays healthy.
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as exc:
        raise ServiceNameTakenError("A service with this name already exists") from exc
    return service


async def update_service(
    session: AsyncSession,
    org: models.Organization,
    service_id: UUID,
    *,
    name: str | None,
    description: str | None,
    owner_team: str | None,
    tier: ServiceTier | None,
) -> models.Service:
    service = await get_service(session, org, service_id)
    if name is not None:
        service.name = name
    if description is not None:
        service.description = description
    if owner_team is not None:
        service.owner_team = owner_team
    if tier is not None:
        service.tier = tier
    try:
        # SAVEPOINT around the flush: on constraint failure only this
        # statement is rolled back and the session stays healthy.
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as exc:
        raise ServiceNameTakenError("A service with this name already exists") from exc
    return service


async def delete_service(session: AsyncSession, org: models.Organization, service_id: UUID) -> None:
    service = await get_service(session, org, service_id)
    await session.delete(service)
    try:
        # SAVEPOINT around the flush: on constraint failure only this
        # statement is rolled back and the session stays healthy.
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as exc:
        # incidents.service_id is ON DELETE RESTRICT: history wins over tidiness.
        raise ServiceInUseError(
            "This service has incidents recorded against it and cannot be deleted"
        ) from exc
