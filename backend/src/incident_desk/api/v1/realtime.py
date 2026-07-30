"""WebSocket ticket endpoint."""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from incident_desk.api.deps import CurrentUser
from incident_desk.schemas.common import Data
from incident_desk.services import realtime

router = APIRouter(tags=["realtime"])


class WsTicketOut(BaseModel):
    ticket: str = Field(description="Single use; consumed atomically on connect")
    expires_in: int = Field(description="Seconds until the ticket dies unused")


@router.post(
    "/ws-ticket",
    summary="Mint a WebSocket ticket",
    description=(
        "Returns a single-use ticket valid for 30 seconds. Connect with "
        "/ws?ticket=... within that window; the server consumes the ticket "
        "atomically, so a replay is rejected. This keeps long-lived JWTs out "
        "of URLs and access logs."
    ),
)
async def create_ws_ticket(user: CurrentUser, request: Request) -> Data[WsTicketOut]:
    ticket = await realtime.issue_ticket(request.app.state.redis, user.id)
    return Data(data=WsTicketOut(ticket=ticket, expires_in=realtime.TICKET_TTL_SECONDS))
