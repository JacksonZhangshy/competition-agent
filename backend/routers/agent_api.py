"""智能体接口：工作流编排、执行、轨迹查询。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..agent import workflows
from ..agent.tools import tool_list
from ..database import get_db
from ..llm import llm
from ..models import AgentRun

router = APIRouter(prefix="/api/agent", tags=["智能体"])


class RunPayload(BaseModel):
    workflow: str
    payload: dict = {}


@router.get("/status")
def status() -> dict:
    return {
        "llm": llm.status(),
        "workflows": list(workflows.WORKFLOW_LABELS.keys()),
        "ready": True,
    }


@router.get("/workflows")
def list_workflows() -> list[dict]:
    return workflows.describe_all()


@router.get("/workflows/{key}")
def workflow_detail(key: str) -> dict:
    graph = workflows.GRAPHS.get(key)
    if graph is None:
        raise HTTPException(404, "工作流不存在")
    return {
        "key": key,
        "label": workflows.WORKFLOW_LABELS.get(key, key),
        "graph": graph.describe(),
        "mermaid": graph.to_mermaid(),
    }


@router.get("/tools")
def tools() -> list[dict]:
    return tool_list()


@router.post("/run")
def run(payload: RunPayload, db: Session = Depends(get_db)) -> dict:
    if payload.workflow not in workflows.WORKFLOWS:
        raise HTTPException(400, f"未知工作流：{payload.workflow}")
    try:
        result = workflows.run(payload.workflow, payload.payload or {}, db)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        db.add(
            AgentRun(
                workflow=payload.workflow,
                status="error",
                input_data=payload.payload or {},
                output_data={"error": str(e)},
                trace=[],
                duration_ms=0,
            )
        )
        db.commit()
        raise HTTPException(500, f"执行失败：{e}") from e

    db.add(
        AgentRun(
            workflow=payload.workflow,
            status="success",
            input_data=payload.payload or {},
            output_data={"answer": (result.get("answer") or "")[:2000]},
            trace=result.get("trace", []),
            duration_ms=result.get("duration_ms", 0),
        )
    )
    db.commit()
    return result


@router.get("/runs")
def runs(limit: int = 50, workflow: str = "", db: Session = Depends(get_db)) -> list[dict]:
    q = db.query(AgentRun)
    if workflow:
        q = q.filter(AgentRun.workflow == workflow)
    rows = q.order_by(AgentRun.id.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "workflow": r.workflow,
            "label": workflows.WORKFLOW_LABELS.get(r.workflow, r.workflow),
            "status": r.status,
            "duration_ms": r.duration_ms,
            "steps": len(r.trace or []),
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        }
        for r in rows
    ]


@router.get("/runs/{run_id}")
def run_detail(run_id: int, db: Session = Depends(get_db)) -> dict:
    r = db.get(AgentRun, run_id)
    if not r:
        raise HTTPException(404, "记录不存在")
    return {
        "id": r.id,
        "workflow": r.workflow,
        "label": workflows.WORKFLOW_LABELS.get(r.workflow, r.workflow),
        "status": r.status,
        "input": r.input_data,
        "output": r.output_data,
        "trace": r.trace or [],
        "duration_ms": r.duration_ms,
        "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S"),
    }
