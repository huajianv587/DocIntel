from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import Ticket, User
from ..schemas import TicketCreate, TicketOut, TicketUpdate


router = APIRouter(prefix="/api/tickets", tags=["tickets"])


@router.get("", response_model=list[TicketOut])
def list_tickets(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[Ticket]:
    statement = select(Ticket).order_by(Ticket.updated_at.desc())
    if user.role != "admin":
        statement = statement.where((Ticket.created_by == user.id) | (Ticket.assignee_id == user.id))
    return list(db.scalars(statement).all())


@router.post("", response_model=TicketOut)
def create_ticket(payload: TicketCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Ticket:
    values = payload.model_dump()
    values["extra_metadata"] = values.pop("metadata", {})
    ticket = Ticket(created_by=user.id, **values)
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


@router.patch("/{ticket_id}", response_model=TicketOut)
def update_ticket(ticket_id: str, payload: TicketUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Ticket:
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if user.role != "admin" and ticket.created_by != user.id and ticket.assignee_id != user.id:
        raise HTTPException(status_code=403, detail="Ticket access denied")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(ticket, key, value)
    db.commit()
    db.refresh(ticket)
    return ticket

