"""经费接口：预算测算、借款单、报销单、单据导出。"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import BudgetRequest, LoanRequest, Reimbursement, Team
from ..services import budget as budget_svc
from ..services import export as export_svc

router = APIRouter(prefix="/api/finance", tags=["经费"])


# ---------------------------------------------------------------- 标准
@router.get("/rules")
def get_rules(db: Session = Depends(get_db)) -> dict:
    return budget_svc.get_rules(db)


@router.put("/rules")
def put_rules(payload: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    if "standards" not in payload:
        raise HTTPException(400, "缺少 standards 字段")
    return budget_svc.save_rules(db, payload)


# ---------------------------------------------------------------- 预算
@router.post("/budget/compute")
def budget_compute(payload: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    return budget_svc.compute_budget(db, payload)


@router.post("/budget/save")
def budget_save(payload: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    result = budget_svc.compute_budget(db, payload) if payload.get("recompute", True) else payload
    no = budget_svc.next_no(db, "BUD", BudgetRequest)
    row = BudgetRequest(
        budget_no=no,
        team_id=payload.get("team_id"),
        title=payload.get("competition") or "竞赛经费预算",
        items=result.get("items", []),
        total=result.get("total", 0.0),
        applicant=payload.get("applicant") or "",
        status=payload.get("status") or "草稿",
    )
    db.add(row)
    db.commit()
    return {"ok": True, "id": row.id, "budget_no": row.budget_no}


@router.get("/budget/list")
def budget_list(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(BudgetRequest).order_by(BudgetRequest.id.desc()).limit(100).all()
    return [
        {
            "id": r.id,
            "budget_no": r.budget_no,
            "title": r.title,
            "total": r.total,
            "approved_amount": r.approved_amount,
            "status": r.status,
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M"),
        }
        for r in rows
    ]


@router.post("/budget/export")
def budget_export(payload: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    if payload.get("budget_id"):
        row = db.get(BudgetRequest, int(payload["budget_id"]))
        if not row:
            raise HTTPException(404, "预算不存在")
        data = {
            "items": row.items,
            "total": row.total,
            "competition": row.title,
            "team_name": "",
            "people": payload.get("people", 3),
            "days": payload.get("days", 3),
            "scope": payload.get("scope", "省内"),
            "level": payload.get("level", "省级"),
            "statement": payload.get("statement", ""),
            "warnings": [],
        }
    else:
        data = budget_svc.compute_budget(db, payload)
    path = export_svc.export_budget_docx(data)
    return {"ok": True, "filename": path.name, "download_url": f"/api/files/{path.name}"}


# ---------------------------------------------------------------- 借款
@router.post("/loan/build")
def loan_build(payload: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    return budget_svc.build_loan(db, payload)


@router.post("/loan/save")
def loan_save(payload: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    loan = budget_svc.build_loan(db, payload)
    no = budget_svc.next_no(db, "LOA", LoanRequest)
    row = LoanRequest(
        loan_no=no,
        budget_id=payload.get("budget_id"),
        team_id=payload.get("team_id"),
        amount=loan["amount"],
        borrower=loan["borrower"],
        payee=loan["payee"],
        bank_account=loan["bank_account"],
        purpose=loan["purpose"],
        status=payload.get("status") or "草稿",
    )
    db.add(row)
    db.commit()
    return {"ok": True, "id": row.id, "loan_no": no, "loan": loan}


@router.post("/loan/export")
def loan_export(payload: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    loan = budget_svc.build_loan(db, payload)
    loan["loan_no"] = payload.get("loan_no") or budget_svc.next_no(db, "LOA", LoanRequest)
    path = export_svc.export_loan_docx(loan)
    return {"ok": True, "filename": path.name, "download_url": f"/api/files/{path.name}"}


# ---------------------------------------------------------------- 报销
@router.post("/reimburse/check")
def reimburse_check(payload: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    return budget_svc.check_reimbursement(db, payload)


@router.post("/reimburse/save")
def reimburse_save(payload: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    result = budget_svc.check_reimbursement(db, payload)
    no = budget_svc.next_no(db, "REI", Reimbursement)
    row = Reimbursement(
        reimb_no=no,
        team_id=payload.get("team_id"),
        budget_id=payload.get("budget_id"),
        items=payload.get("items") or [],
        total=result["total"],
        status="待审核" if result["pass"] else "已退回",
        check_result=result,
    )
    db.add(row)
    db.commit()
    return {"ok": True, "id": row.id, "reimb_no": no, "check": result}


@router.get("/reimburse/list")
def reimburse_list(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(Reimbursement).order_by(Reimbursement.id.desc()).limit(100).all()
    return [
        {
            "id": r.id,
            "reimb_no": r.reimb_no,
            "total": r.total,
            "status": r.status,
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M"),
        }
        for r in rows
    ]


@router.post("/reimburse/export")
def reimburse_export(payload: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    result = budget_svc.check_reimbursement(db, payload)
    result["reimb_no"] = payload.get("reimb_no") or budget_svc.next_no(db, "REI", Reimbursement)
    result["items"] = payload.get("items") or []
    result["total_cn"] = budget_svc.money_to_chinese(result["total"])
    path = export_svc.export_reimburse_docx(result)
    return {"ok": True, "filename": path.name, "download_url": f"/api/files/{path.name}"}


# ---------------------------------------------------------------- 队伍选择
@router.get("/teams-options")
def teams_options(keyword: str = "", db: Session = Depends(get_db)) -> list[dict]:
    q = db.query(Team).filter(Team.status.in_(["报名", "备赛", "参赛", "获奖"]))
    if keyword:
        q = q.filter(Team.project_name.like(f"%{keyword}%"))
    rows = q.order_by(Team.id.desc()).limit(50).all()
    out = []
    for t in rows:
        ed = t.edition
        comp = ed.competition if ed else None
        out.append(
            {
                "id": t.id,
                "project": t.project_name,
                "competition": comp.name if comp else "",
                "level": comp.level if comp else "",
                "year": ed.year if ed else None,
                "leader": t.leader.name if t.leader else "",
                "teacher": t.teacher.name if t.teacher else "",
            }
        )
    return out
