"""知识问答相关接口。"""
from __future__ import annotations

import datetime as dt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..agent import workflows
from ..database import get_db
from ..llm import llm
from ..models import AgentRun, Conversation, Message

router = APIRouter(prefix="/api/chat", tags=["问答"])


class AskPayload(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    conversation_id: int | None = None


class NewConversation(BaseModel):
    title: str = "新对话"


@router.post("/ask")
def ask(payload: AskPayload, db: Session = Depends(get_db)) -> dict:
    question = payload.question.strip()
    if not question:
        raise HTTPException(400, "问题不能为空")

    conv = db.get(Conversation, payload.conversation_id) if payload.conversation_id else None
    if conv is None:
        conv = Conversation(title=question[:20])
        db.add(conv)
        db.flush()

    db.add(Message(conversation_id=conv.id, role="user", content=question))
    db.commit()

    try:
        result = workflows.run("qa", {"question": question}, db)
    except Exception as e:  # 保留可读错误，不 500
        raise HTTPException(500, f"处理失败：{e}") from e

    assistant = Message(
        conversation_id=conv.id,
        role="assistant",
        content=result["answer"],
        citations=result.get("citations", []),
        meta={"mode": result.get("mode"), "steps": result.get("steps"), "duration_ms": result.get("duration_ms")},
    )
    db.add(assistant)

    if conv.title == "新对话" or not conv.title:
        conv.title = question[:20]
    conv.updated_at = dt.datetime.now()
    db.add(
        AgentRun(
            workflow="qa",
            status="success",
            input_data={"question": question},
            output_data={"answer": result["answer"][:2000]},
            trace=result.get("trace", []),
            duration_ms=result.get("duration_ms", 0),
        )
    )
    db.commit()

    return {
        "conversation_id": conv.id,
        "answer": result["answer"],
        "citations": result.get("citations", []),
        "mode": result.get("mode"),
        "trace": result.get("trace", []),
        "duration_ms": result.get("duration_ms"),
        "llm_available": llm.available,
    }


@router.get("/conversations")
def list_conversations(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(Conversation).order_by(Conversation.updated_at.desc()).limit(50).all()
    return [
        {
            "id": c.id,
            "title": c.title,
            "updated_at": c.updated_at.strftime("%m-%d %H:%M"),
            "message_count": len(c.messages),
        }
        for c in rows
    ]


@router.post("/conversations")
def create_conversation(payload: NewConversation, db: Session = Depends(get_db)) -> dict:
    conv = Conversation(title=payload.title)
    db.add(conv)
    db.commit()
    return {"id": conv.id, "title": conv.title}


@router.get("/conversations/{conv_id}")
def get_conversation(conv_id: int, db: Session = Depends(get_db)) -> dict:
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "会话不存在")
    return {
        "id": conv.id,
        "title": conv.title,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "citations": m.citations or [],
                "meta": m.meta or {},
                "time": m.created_at.strftime("%H:%M"),
            }
            for m in conv.messages
        ],
    }


@router.delete("/conversations/{conv_id}")
def delete_conversation(conv_id: int, db: Session = Depends(get_db)) -> dict:
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "会话不存在")
    db.delete(conv)
    db.commit()
    return {"ok": True}
