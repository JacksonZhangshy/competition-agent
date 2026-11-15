"""竞赛台账与统计接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import case, func
from sqlalchemy.orm import Session, joinedload

from ..agent import workflows
from ..database import get_db
from ..models import Competition, Edition, Student, Team
from ..services import export as export_svc
from ..services import stats as stats_svc

router = APIRouter(prefix="/api/data", tags=["数据"])


class StatsAsk(BaseModel):
    question: str


def _filters(
    year: str | None,
    year_from: str | None,
    year_to: str | None,
    competition: str | None,
    level: str | None,
    category: str | None,
    award_grade: str | None,
    award_level: str | None,
    major: str | None,
    teacher: str | None,
    student: str | None,
    status: str | None,
    awarded_only: bool,
) -> stats_svc.Filters:
    return stats_svc.Filters(
        year=year,
        year_from=year_from,
        year_to=year_to,
        competition=competition,
        level=level,
        category=category,
        award_grade=award_grade,
        award_level=award_level,
        major=major,
        teacher=teacher,
        student=student,
        status=status,
        awarded_only=awarded_only,
    )


@router.get("/overview")
def overview(db: Session = Depends(get_db)) -> dict:
    data = stats_svc.overview(db)
    data["award_distribution"] = stats_svc.award_distribution(db)
    data["year_trend"] = stats_svc.year_trend(db)
    data["teacher_top"] = stats_svc.teacher_ranking(db, limit=8)
    data["level_distribution"] = stats_svc.aggregate(db, stats_svc.Filters(), "level")["items"]
    return data


@router.get("/competitions")
def competitions(
    level: str = "", category: str = "", keyword: str = "", db: Session = Depends(get_db)
) -> dict:
    q = db.query(Competition).filter(Competition.is_active.is_(True))
    if level:
        q = q.filter(Competition.level == level)
    if category:
        q = q.filter(Competition.category == category)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter((Competition.name.like(like)) | (Competition.short_name.like(like)))
    rows = q.order_by(Competition.level, Competition.name).all()

    out = []
    for c in rows:
        latest = db.query(Edition).filter(Edition.competition_id == c.id).order_by(Edition.year.desc()).first()
        agg = (
            db.query(func.count(Team.id), func.sum(case((Team.award_level != "无", 1), else_=0)))
            .join(Edition, Team.edition_id == Edition.id)
            .filter(Edition.competition_id == c.id)
            .first()
        )
        total, awards = (agg[0] or 0, agg[1] or 0) if agg else (0, 0)
        out.append(
            {
                "id": c.id,
                "code": c.code,
                "name": c.name,
                "short_name": c.short_name,
                "level": c.level,
                "category": c.category,
                "organizer": c.organizer,
                "majors": c.majors,
                "grades": c.grades,
                "difficulty": c.difficulty,
                "description": c.description,
                "latest_year": latest.year if latest else None,
                "latest_status": latest.status if latest else "未开始",
                "signup_end": latest.signup_end.isoformat() if latest and latest.signup_end else None,
                "fee": latest.fee if latest else 0,
                "team_count": int(total),
                "award_count": int(awards),
                "award_rate": round(awards / total * 100, 1) if total else 0.0,
            }
        )
    return {"count": len(out), "items": out}


@router.get("/competitions/{comp_id}")
def competition_detail(comp_id: int, db: Session = Depends(get_db)) -> dict:
    c = db.get(Competition, comp_id)
    if not c:
        raise HTTPException(404, "赛事不存在")
    editions = db.query(Edition).filter(Edition.competition_id == c.id).order_by(Edition.year.desc()).all()
    return {
        "id": c.id,
        "code": c.code,
        "name": c.name,
        "level": c.level,
        "category": c.category,
        "organizer": c.organizer,
        "official_url": c.official_url,
        "majors": c.majors,
        "grades": c.grades,
        "difficulty": c.difficulty,
        "workload": c.workload,
        "description": c.description,
        "tags": c.tags,
        "editions": [
            {
                "id": e.id,
                "year": e.year,
                "seq": e.seq,
                "status": e.status,
                "notice_title": e.notice_title,
                "signup_start": e.signup_start.isoformat() if e.signup_start else None,
                "signup_end": e.signup_end.isoformat() if e.signup_end else None,
                "contest_start": e.contest_start.isoformat() if e.contest_start else None,
                "contest_end": e.contest_end.isoformat() if e.contest_end else None,
                "fee": e.fee,
                "venue": e.venue,
                "rules": e.rules_json or {},
            }
            for e in editions
        ],
    }


@router.get("/teams")
def teams(
    year: str = "",
    competition: str = "",
    level: str = "",
    award_level: str = "",
    major: str = "",
    teacher: str = "",
    keyword: str = "",
    page: int = 1,
    size: int = 50,
    db: Session = Depends(get_db),
) -> dict:
    f = stats_svc.Filters(
        year=year or None, competition=competition or None, level=level or None,
        award_level=award_level or None, major=major or None, teacher=teacher or None,
    )
    q = stats_svc.base_query(db, f)
    if keyword:
        q = q.filter(Team.project_name.like(f"%{keyword}%"))
    total = q.count()
    rows = (
        q.options(
            joinedload(Team.edition).joinedload(Edition.competition),
            joinedload(Team.leader),
            joinedload(Team.teacher),
        )
        .order_by(Edition.year.desc(), Team.id.desc())
        .offset(max(0, (page - 1) * size))
        .limit(size)
        .all()
    )

    items = []
    for t in rows:
        ed = t.edition
        comp = ed.competition if ed else None
        items.append(
            {
                "id": t.id,
                "year": ed.year if ed else None,
                "competition": comp.name if comp else "",
                "short_name": comp.short_name if comp else "",
                "level": comp.level if comp else "",
                "project": t.project_name,
                "leader": t.leader.name if t.leader else "",
                "major": t.leader.major if t.leader else "",
                "teacher": t.teacher.name if t.teacher else "",
                "award_grade": t.award_grade,
                "award_level": t.award_level,
                "status": t.status,
                "budget": t.budget_total,
                "member_count": len(t.members),
            }
        )
    return {"total": total, "page": page, "size": size, "items": items}


@router.get("/teams/{team_id}")
def team_detail(team_id: int, db: Session = Depends(get_db)) -> dict:
    t = (
        db.query(Team)
        .options(joinedload(Team.edition).joinedload(Edition.competition), joinedload(Team.leader), joinedload(Team.teacher))
        .filter(Team.id == team_id)
        .first()
    )
    if not t:
        raise HTTPException(404, "项目不存在")
    ed = t.edition
    comp = ed.competition if ed else None
    return {
        "id": t.id,
        "year": ed.year if ed else None,
        "competition": comp.name if comp else "",
        "level": comp.level if comp else "",
        "project": t.project_name,
        "leader": t.leader.name if t.leader else "",
        "major": t.leader.major if t.leader else "",
        "teacher": t.teacher.name if t.teacher else "",
        "award_grade": t.award_grade,
        "award_level": t.award_level,
        "status": t.status,
        "budget": t.budget_total,
        "remark": t.remark,
        "members": stats_svc.team_members(db, t.id),
    }


@router.get("/students")
def students(keyword: str = "", page: int = 1, size: int = 30, db: Session = Depends(get_db)) -> dict:
    q = db.query(Student)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter((Student.name.like(like)) | (Student.sno.like(like)) | (Student.major.like(like)))
    total = q.count()
    rows = q.order_by(Student.sno).offset(max(0, (page - 1) * size)).limit(size).all()
    return {
        "total": total,
        "items": [
            {
                "id": s.id,
                "sno": s.sno,
                "name": s.name,
                "major": s.major,
                "grade": s.grade,
                "grade_label": s.grade_label,
                "class_name": s.class_name,
            }
            for s in rows
        ],
    }


@router.get("/statistics")
def statistics(
    group_by: str = "year",
    year: str = "",
    year_from: str = "",
    year_to: str = "",
    competition: str = "",
    level: str = "",
    category: str = "",
    award_grade: str = "",
    award_level: str = "",
    major: str = "",
    teacher: str = "",
    student: str = "",
    status: str = "",
    awarded_only: bool = False,
    db: Session = Depends(get_db),
) -> dict:
    f = _filters(year, year_from, year_to, competition, level, category, award_grade,
                 award_level, major, teacher, student, status, awarded_only)
    try:
        return stats_svc.aggregate(db, f, group_by)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/statistics/ask")
def statistics_ask(payload: StatsAsk, db: Session = Depends(get_db)) -> dict:
    try:
        result = workflows.run("stats", {"question": payload.question}, db)
    except Exception as e:
        raise HTTPException(500, f"统计失败：{e}") from e
    return result


@router.post("/statistics/export")
def export_statistics(
    group_by: str = "year",
    year: str = "",
    competition: str = "",
    level: str = "",
    award_grade: str = "",
    award_level: str = "",
    major: str = "",
    teacher: str = "",
    with_detail: bool = True,
    db: Session = Depends(get_db),
) -> dict:
    f = stats_svc.Filters(year=year or None, competition=competition or None, level=level or None,
                          award_grade=award_grade or None, award_level=award_level or None,
                          major=major or None, teacher=teacher or None)
    result = stats_svc.aggregate(db, f, group_by)
    detail = stats_svc.detail_rows(db, f, limit=2000) if with_detail else None
    path = export_svc.export_stats_workbook(result, detail)
    return {"ok": True, "filename": path.name, "download_url": f"/api/files/{path.name}"}


@router.get("/dimensions")
def dimensions() -> dict:
    return {"groups": stats_svc.GROUP_FIELDS, "metrics": stats_svc.METRICS, "award_levels": stats_svc.AWARD_LEVELS}
