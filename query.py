from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import User
from ..schemas import QueryRequest, QueryResult
from ..services.agent import AgentService


router = APIRouter(prefix="/api", tags=["query"])
agent_service = AgentService()


@router.post("/query", response_model=QueryResult)
def query(payload: QueryRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> QueryResult:
    return agent_service.answer(db, user=user, query=payload.query, domain=payload.domain, top_k=payload.top_k, code=payload.code)

