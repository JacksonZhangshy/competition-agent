"""竞赛数据统计服务。

所有统计口径均为"参赛项目（Team）"级别：
- 参赛项目数 = Team 记录数
- 获奖数 = award_level 不为"无"的 Team 数
- 获奖率 = 获奖数 / 参赛项目数
- 专业维度按项目负责人专业归集（口径统一，避免成员重复计数）
数字全部来自数据库聚合，不经过大模型生成。
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, joinedload

from ..models import Competition, Edition, Student, Team, Teacher, TeamMember

GROUP_FIELDS = {
    "year": "年份",
    "competition": "赛事",
    "level": "赛事级别",
    "category": "赛事类别",
    "college": "学院",
    "major": "专业",
    "teacher": "指导教师",
    "award_grade": "获奖级别",
    "award_level": "获奖等级",
    "status": "参赛状态",
    "student": "学生",
}

METRICS = {
    "count": "参赛项目数",
    "award_count": "获奖数",
    "award_rate": "获奖率",
    "amount": "预算金额",
}

AWARD_LEVELS = ["特等奖", "一等奖", "二等奖", "三等奖", "优秀奖"]


class Filters:
    __slots__ = (
        "year",
        "year_from",
        "year_to",
        "competition",
        "level",
        "category",
        "award_grade",
        "award_level",
        "major",
        "teacher",
        "student",
        "status",
        "awarded_only",
    )

    def __init__(self, **kw: Any) -> None:
        self.year: int | None = _to_int(kw.get("year"))
        self.year_from: int | None = _to_int(kw.get("year_from"))
        self.year_to: int | None = _to_int(kw.get("year_to"))
        self.competition = (kw.get("competition") or "").strip() or None
        self.level = (kw.get("level") or "").strip() or None
        self.category = (kw.get("category") or "").strip() or None
        self.award_grade = (kw.get("award_grade") or "").strip() or None
        self.award_level = (kw.get("award_level") or "").strip() or None
        self.major = (kw.get("major") or "").strip() or None
        self.teacher = (kw.get("teacher") or "").strip() or None
        self.student = (kw.get("student") or "").strip() or None
        self.status = (kw.get("status") or "").strip() or None
        self.awarded_only = bool(kw.get("awarded_only"))

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__ if getattr(self, k) not in (None, False, "")}

    def describe(self) -> list[str]:
        labels: list[str] = []
        if self.year:
            labels.append(f"{self.year} 年")
        if self.year_from or self.year_to:
            labels.append(f"{self.year_from or '起始'}—{self.year_to or '至今'}")
        for attr, label in (
            ("competition", "赛事"),
            ("level", "级别"),
            ("category", "类别"),
            ("award_grade", "获奖级别"),
            ("award_level", "获奖等级"),
            ("major", "专业"),
            ("teacher", "指导教师"),
            ("student", "学生"),
            ("status", "状态"),
        ):
            v = getattr(self, attr)
            if v:
                labels.append(f"{label}={v}")
        if self.awarded_only:
            labels.append("仅获奖项目")
        return labels


def _to_int(v: Any) -> int | None:
    if v in (None, "", "null"):
        return None
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def base_query(db: Session, f: Filters):
    """构造带全部筛选条件的查询。

    不挂 eager-load 选项：统计时还要叠加 count / group_by / with_entities，
    预加载会产生多余 JOIN 并干扰计数。对象间关系按需懒加载即可。
    """
    q = (
        db.query(Team)
        .join(Edition, Team.edition_id == Edition.id)
        .join(Competition, Edition.competition_id == Competition.id)
        .outerjoin(Student, Team.leader_student_id == Student.id)
        .outerjoin(Teacher, Team.teacher_id == Teacher.id)
    )
    if f.year:
        q = q.filter(Edition.year == f.year)
    if f.year_from:
        q = q.filter(Edition.year >= f.year_from)
    if f.year_to:
        q = q.filter(Edition.year <= f.year_to)
    if f.competition:
        like = f"%{f.competition}%"
        q = q.filter((Competition.name.like(like)) | (Competition.short_name.like(like)) | (Competition.code.like(like)))
    if f.level:
        q = q.filter(Competition.level == f.level)
    if f.category:
        q = q.filter(Competition.category == f.category)
    if f.award_grade:
        q = q.filter(Team.award_grade == f.award_grade)
    if f.award_level:
        q = q.filter(Team.award_level == f.award_level)
    if f.major:
        q = q.filter(Student.major.like(f"%{f.major}%"))
    if f.teacher:
        q = q.filter(Teacher.name.like(f"%{f.teacher}%"))
    if f.student:
        sub = (
            db.query(TeamMember.team_id)
            .join(Student, TeamMember.student_id == Student.id)
            .filter(Student.name.like(f"%{f.student}%"))
            .subquery()
        )
        q = q.filter(
            (Student.name.like(f"%{f.student}%")) | (Team.id.in_(select(sub.c.team_id)))
        )
    if f.status:
        q = q.filter(Team.status == f.status)
    if f.awarded_only:
        q = q.filter(Team.award_level != "无")
    return q


def _group_expr(group_by: str):
    if group_by == "year":
        return Edition.year
    if group_by == "competition":
        return Competition.short_name
    if group_by == "level":
        return Competition.level
    if group_by == "category":
        return Competition.category
    if group_by == "college":
        return Student.college
    if group_by == "major":
        return Student.major
    if group_by == "teacher":
        return Teacher.name
    if group_by == "award_grade":
        return Team.award_grade
    if group_by == "award_level":
        return Team.award_level
    if group_by == "status":
        return Team.status
    if group_by == "student":
        return Student.name
    raise ValueError(f"不支持的分组维度：{group_by}")


def aggregate(db: Session, f: Filters, group_by: str = "year", limit: int = 200) -> dict:
    if group_by not in GROUP_FIELDS:
        raise ValueError(f"不支持的分组维度：{group_by}")

    q = base_query(db, f)
    g = _group_expr(group_by)
    award_expr = func.sum(case((Team.award_level != "无", 1), else_=0))
    rows = (
        q.with_entities(
            g.label("key"),
            func.count(Team.id).label("cnt"),
            award_expr.label("awards"),
            func.sum(Team.budget_total).label("amount"),
        )
        .group_by(g)
        .order_by(func.count(Team.id).desc())
        .limit(limit)
        .all()
    )

    items = []
    for key, cnt, awards, amount in rows:
        cnt = int(cnt or 0)
        awards = int(awards or 0)
        items.append(
            {
                "key": str(key) if key not in (None, "") else "未填写",
                "count": cnt,
                "award_count": awards,
                "award_rate": round(awards / cnt * 100, 1) if cnt else 0.0,
                "amount": round(float(amount or 0), 2),
            }
        )

    if group_by in {"year", "award_level", "award_grade"}:
        items.sort(key=lambda x: x["key"])

    totals = {
        "count": sum(i["count"] for i in items),
        "award_count": sum(i["award_count"] for i in items),
        "amount": round(sum(i["amount"] for i in items), 2),
    }
    totals["award_rate"] = round(totals["award_count"] / totals["count"] * 100, 1) if totals["count"] else 0.0

    return {
        "group_by": group_by,
        "group_label": GROUP_FIELDS[group_by],
        "filters": f.describe(),
        "items": items,
        "totals": totals,
    }


def detail_rows(db: Session, f: Filters, limit: int = 500) -> list[dict]:
    rows = (
        base_query(db, f)
        .options(
            joinedload(Team.edition).joinedload(Edition.competition),
            joinedload(Team.leader),
            joinedload(Team.teacher),
        )
        .order_by(Edition.year.desc(), Team.id.desc())
        .limit(limit)
        .all()
    )
    out = []
    for t in rows:
        ed = t.edition
        comp = ed.competition if ed else None
        out.append(
            {
                "id": t.id,
                "year": ed.year if ed else None,
                "competition": comp.short_name or comp.name if comp else "",
                "level": comp.level if comp else "",
                "project": t.project_name,
                "student": t.leader.name if t.leader else "",
                "college": t.leader.college if t.leader else "",
                "major": t.leader.major if t.leader else "",
                "grade": t.leader.grade if t.leader else None,
                "teacher": t.teacher.name if t.teacher else "",
                "award_grade": t.award_grade,
                "award_level": t.award_level,
                "status": t.status,
                "budget": t.budget_total,
            }
        )
    return out


def overview(db: Session) -> dict:
    total_teams = db.query(func.count(Team.id)).scalar() or 0
    total_awards = db.query(func.count(Team.id)).filter(Team.award_level != "无").scalar() or 0
    years = [r[0] for r in db.query(Edition.year).distinct().order_by(Edition.year).all()]
    comps = db.query(func.count(Competition.id)).scalar() or 0
    students = db.query(func.count(Student.id)).scalar() or 0
    teachers = db.query(func.count(Teacher.id)).scalar() or 0
    amount = db.query(func.sum(Team.budget_total)).scalar() or 0

    national = (
        db.query(func.count(Team.id)).filter(Team.award_grade == "国家级", Team.award_level != "无").scalar() or 0
    )
    provincial = (
        db.query(func.count(Team.id)).filter(Team.award_grade == "省级", Team.award_level != "无").scalar() or 0
    )

    return {
        "team_count": total_teams,
        "award_count": total_awards,
        "award_rate": round(total_awards / total_teams * 100, 1) if total_teams else 0.0,
        "national_award": national,
        "provincial_award": provincial,
        "competition_count": comps,
        "student_count": students,
        "teacher_count": teachers,
        "budget_total": round(float(amount or 0), 2),
        "years": years,
        "latest_year": years[-1] if years else dt.date.today().year,
    }


def teacher_ranking(db: Session, year: int | None = None, limit: int = 20) -> list[dict]:
    f = Filters(year=year)
    res = aggregate(db, f, "teacher", limit=limit)
    return res["items"]


def award_distribution(db: Session, year: int | None = None) -> list[dict]:
    f = Filters(year=year, awarded_only=True)
    res = aggregate(db, f, "award_level")
    items = {i["key"]: i for i in res["items"]}
    return [
        {"key": lv, "count": items.get(lv, {}).get("count", 0)}
        for lv in AWARD_LEVELS
    ]


def year_trend(db: Session) -> list[dict]:
    res = aggregate(db, Filters(), "year", limit=50)
    return res["items"]


def team_members(db: Session, team_id: int) -> list[dict]:
    rows = (
        db.query(TeamMember, Student)
        .join(Student, TeamMember.student_id == Student.id)
        .filter(TeamMember.team_id == team_id)
        .all()
    )
    return [
        {"name": s.name, "sno": s.sno, "major": s.major, "grade": s.grade, "role": m.role}
        for m, s in rows
    ]


def student_history(db: Session, sno: str | None = None, name: str | None = None) -> dict:
    if not sno and not name:
        return {"student": None, "teams": []}
    qs = db.query(Student)
    student = qs.filter(Student.sno == sno).first() if sno else None
    if student is None and name:
        student = qs.filter(Student.name == name).first()
    if student is None:
        return {"student": None, "teams": []}

    team_ids = [r[0] for r in db.query(TeamMember.team_id).filter(TeamMember.student_id == student.id).all()]
    if student.id:
        team_ids += [r[0] for r in db.query(Team.id).filter(Team.leader_student_id == student.id).all()]
    team_ids = sorted(set(team_ids))

    rows = (
        db.query(Team)
        .options(joinedload(Team.edition).joinedload(Edition.competition))
        .filter(Team.id.in_(team_ids))
        .all()
        if team_ids
        else []
    )
    teams = []
    for t in rows:
        ed = t.edition
        comp = ed.competition if ed else None
        teams.append(
            {
                "year": ed.year if ed else None,
                "competition": (comp.short_name or comp.name) if comp else "",
                "level": comp.level if comp else "",
                "project": t.project_name,
                "award_grade": t.award_grade,
                "award_level": t.award_level,
                "status": t.status,
            }
        )
    teams.sort(key=lambda x: (x["year"] or 0), reverse=True)
    return {
        "student": {
            "sno": student.sno,
            "name": student.name,
            "major": student.major,
            "grade": student.grade,
            "grade_label": student.grade_label,
        },
        "teams": teams,
        "award_count": sum(1 for t in teams if t["award_level"] != "无"),
    }
