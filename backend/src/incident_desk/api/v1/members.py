"""Membership endpoints: members, role changes, invitations."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from incident_desk.api.authz import AuthContext, require
from incident_desk.api.deps import CurrentUser
from incident_desk.api.v1.auth import get_email_sender
from incident_desk.authz import Permission
from incident_desk.db.engine import get_db_session
from incident_desk.schemas.common import Data
from incident_desk.schemas.members import (
    AcceptedInvitationOut,
    AcceptInvitationRequest,
    ChangeRoleRequest,
    InvitationOut,
    InviteRequest,
    MemberOut,
)
from incident_desk.services import members as member_service
from incident_desk.services.emails import EmailSender

router = APIRouter(prefix="/orgs/{org_slug}", tags=["members"])
accept_router = APIRouter(prefix="/invitations", tags=["members"])

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
SenderDep = Annotated[EmailSender, Depends(get_email_sender)]

MemberViewCtx = Annotated[AuthContext, Depends(require(Permission.MEMBER_VIEW))]
MemberManageCtx = Annotated[AuthContext, Depends(require(Permission.MEMBER_MANAGE))]


@router.get("/members", summary="List members")
async def list_members(ctx: MemberViewCtx, session: SessionDep) -> Data[list[MemberOut]]:
    pairs = await member_service.list_members(session, ctx.org)
    return Data(
        data=[
            MemberOut(
                user_id=user.id,
                email=user.email,
                full_name=user.full_name,
                avatar_url=user.avatar_url,
                role=membership.role,
                joined_at=membership.joined_at,
            )
            for user, membership in pairs
        ]
    )


@router.patch(
    "/members/{user_id}",
    summary="Change a member's role",
    description=(
        "Admins manage responder and viewer roles; only owners may grant or take "
        "the owner role. The last owner can never be demoted."
    ),
)
async def change_role(
    user_id: UUID,
    payload: ChangeRoleRequest,
    ctx: MemberManageCtx,
    session: SessionDep,
) -> Data[MemberOut]:
    membership = await member_service.change_role(
        session, ctx.org, actor_role=ctx.role, user_id=user_id, new_role=payload.role
    )
    await session.commit()
    pairs = await member_service.list_members(session, ctx.org)
    user, m = next((u, m) for u, m in pairs if u.id == membership.user_id)
    return Data(
        data=MemberOut(
            user_id=user.id,
            email=user.email,
            full_name=user.full_name,
            avatar_url=user.avatar_url,
            role=m.role,
            joined_at=m.joined_at,
        )
    )


@router.delete(
    "/members/{user_id}",
    status_code=204,
    summary="Remove a member",
    description="The last owner cannot be removed.",
)
async def remove_member(user_id: UUID, ctx: MemberManageCtx, session: SessionDep) -> None:
    await member_service.remove_member(session, ctx.org, actor_role=ctx.role, user_id=user_id)
    await session.commit()


@router.post(
    "/invitations",
    status_code=201,
    summary="Invite someone",
    description="Emails an invitation link valid for 7 days.",
)
async def invite(
    payload: InviteRequest,
    ctx: MemberManageCtx,
    session: SessionDep,
    sender: SenderDep,
) -> Data[InvitationOut]:
    invitation, token = await member_service.create_invitation(
        session,
        ctx.org,
        email=payload.email,
        role=payload.role,
        invited_by=ctx.user,
        actor_role=ctx.role,
    )
    await session.commit()
    await sender.send_invitation_email(to=invitation.email, org_name=ctx.org.name, token=token)
    return Data(data=InvitationOut.model_validate(invitation))


@router.get("/invitations", summary="List pending invitations")
async def list_invitations(ctx: MemberManageCtx, session: SessionDep) -> Data[list[InvitationOut]]:
    pending = await member_service.list_pending_invitations(session, ctx.org)
    return Data(data=[InvitationOut.model_validate(i) for i in pending])


@router.delete("/invitations/{invitation_id}", status_code=204, summary="Revoke an invitation")
async def revoke_invitation(invitation_id: UUID, ctx: MemberManageCtx, session: SessionDep) -> None:
    await member_service.revoke_invitation(session, ctx.org, invitation_id)
    await session.commit()


@accept_router.post(
    "/accept",
    summary="Accept an invitation",
    description=(
        "Turns an emailed invitation token into a membership for the logged-in "
        "account. The account email must match the invited address."
    ),
)
async def accept_invitation(
    payload: AcceptInvitationRequest, user: CurrentUser, session: SessionDep
) -> Data[AcceptedInvitationOut]:
    org, membership = await member_service.accept_invitation(session, user, payload.token)
    await session.commit()
    return Data(
        data=AcceptedInvitationOut(org_slug=org.slug, org_name=org.name, role=membership.role)
    )
