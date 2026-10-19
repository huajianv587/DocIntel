from __future__ import annotations

import json
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import Conversation, Message, TraceRecord, User
from ..schemas import ConversationCreate, ConversationDetail, ConversationOut, MessageOut, QueryRequest, QueryResult, TraceOut
from ..services.agent import AgentService


router = APIRouter(prefix="/api/conversations", tags=["conversations"])
agent_service = AgentService()


def _conversation_or_404(db: Session, conversation_id: str, user: User) -> Conversation:
    conversation = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user.id))
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.get("", response_model=list[ConversationOut])
def list_conversations(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[Conversation]:
    return list(db.scalars(select(Conversation).where(Conversation.user_id == user.id).order_by(Conversation.updated_at.desc())).all())


@router.post("", response_model=ConversationOut)
def create_conversation(payload: ConversationCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Conversation:
    conversation = Conversation(user_id=user.id, title=payload.title, domain=payload.domain)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> ConversationDetail:
    conversation = _conversation_or_404(db, conversation_id, user)
    messages = list(db.scalars(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at.asc())).all())
    return ConversationDetail.model_validate({**ConversationOut.model_validate(conversation).model_dump(), "messages": [MessageOut.model_validate(item) for item in messages]})


@router.post("/{conversation_id}/messages", response_model=QueryResult)
def send_message(conversation_id: str, payload: QueryRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> QueryResult:
    conversation = _conversation_or_404(db, conversation_id, user)
    return agent_service.answer(db, user=user, query=payload.query, domain=conversation.domain, top_k=payload.top_k, conversation=conversation, code=payload.code)


@router.post("/{conversation_id}/messages/stream")
def stream_message(conversation_id: str, payload: QueryRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> StreamingResponse:
    conversation = _conversation_or_404(db, conversation_id, user)
    result = agent_service.answer(db, user=user, query=payload.query, domain=conversation.domain, top_k=payload.top_k, conversation=conversation, code=payload.code)

    def events() -> Iterator[str]:
        yield f"event: meta\ndata: {json.dumps({'trace_id': result.trace_id, 'route': result.route}, ensure_ascii=False)}\n\n"
        words = result.answer.split(" ")
        buffer = []
        for word in words:
            buffer.append(word)
            if len(buffer) >= 8:
                yield f"event: token\ndata: {json.dumps({'text': ' '.join(buffer) + ' '}, ensure_ascii=False)}\n\n"
                buffer = []
        if buffer:
            yield f"event: token\ndata: {json.dumps({'text': ' '.join(buffer)}, ensure_ascii=False)}\n\n"
        yield f"event: result\ndata: {result.model_dump_json()}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/{conversation_id}/trace", response_model=list[TraceOut])
def conversation_traces(conversation_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[TraceRecord]:
    conversation = _conversation_or_404(db, conversation_id, user)
    return list(db.scalars(select(TraceRecord).where(TraceRecord.conversation_id == conversation.id).order_by(TraceRecord.created_at.asc())).all())

