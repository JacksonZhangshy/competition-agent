"""Agent 工具集。

每个工具都是"确定的程序逻辑"，大模型只负责决定调用哪个工具、如何组织语言。
这样保证：数字、日期、金额、名单一律来自数据库与规则计算，不由模型臆造。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Callable

from sqlalchemy import case, func
from sqlalchemy.orm import Session, joinedload

from ..models import Competition, Edition, Student, Team, Teacher
from ..rag.index import get_index
from ..services import budget as budget_svc
from ..services import stats as stats_svc
from .graph import RunContext

TOOLS: dict[str, dict] = {}


def tool(name: str, description: str, params: dict | None = None):
    def deco(fn: Callable[..., Any]):
        TOOLS[name] = {"name": name, "description": description, "params": params or {}, "fn": fn}
        return fn

    return deco


def call_tool(name: str, ctx: RunContext, **kwargs) -> dict:
    spec = TOOLS.get(name)
    if not spec:
        raise KeyError(f"未注册的工具：{name}")
    return spec["fn"](ctx, **kwargs)


def tool_list() -> list[dict]:
    return [{"name": k, "description": v["description"], "params": v["params"]} for k, v in TOOLS.items()]


def _db(ctx: RunContext) -> Session:
    if ctx.db is None:
        raise RuntimeError("运行上下文缺少数据库会话")
    return ctx.db


# ---------------------------------------------------------------- 知识库
@tool(
    "search_knowledge",
    "在竞赛知识库（政策、规程、通知、模板）中做关键词+语义混合检索，返回片段与出处",
    {"query": "检索语句", "top_k": "返回条数，默认 6", "category": "可选，限定文档类别"},
)
def search_knowledge(ctx: RunContext, query: str, top_k: int = 6, category: str | None = None) -> dict:
    db = _db(ctx)
    index = get_index(db)
    hits = index.search(query, top_k=top_k, category=category)
    return {
        "count": len(hits),
        "items": [h.citation() for h in hits],
        "max_score": round(hits[0].score, 4) if hits else 0.0,
    }


@tool("knowledge_stats", "查看知识库收录情况", {})
def knowledge_stats(ctx: RunContext) -> dict:
    from ..rag.ingest import stats as kb_stats

    return kb_stats(_db(ctx))


# ---------------------------------------------------------------- 赛事
@tool("list_competitions", "按级别、类别、关键词查询赛事清单", {"level": "", "category": "", "keyword": ""})
def list_competitions(ctx: RunContext, level: str = "", category: str = "", keyword: str = "") -> dict:
    db = _db(ctx)
    q = db.query(Competition).filter(Competition.is_active.is_(True))
    if level:
        q = q.filter(Competition.level == level)
    if category:
        q = q.filter(Competition.category == category)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter((Competition.name.like(like)) | (Competition.short_name.like(like)) | (Competition.tags.like(like)))
    comps = q.all()
    out = []
    for c in comps:
        latest = (
            db.query(Edition).filter(Edition.competition_id == c.id).order_by(Edition.year.desc()).first()
        )
        out.append(
            {
                "code": c.code,
                "name": c.name,
                "short_name": c.short_name,
                "level": c.level,
                "category": c.category,
                "majors": c.majors,
                "grades": c.grades,
                "difficulty": c.difficulty,
                "latest_year": latest.year if latest else None,
                "latest_status": latest.status if latest else "未开始",
                "signup_end": latest.signup_end.isoformat() if latest and latest.signup_end else None,
                "fee": latest.fee if latest else 0,
            }
        )
    return {"count": len(out), "items": out}


@tool("get_competition_info", "查询单个赛事的详细信息、报名条件、时间节点、材料清单、奖项设置", {"name_or_code": ""})
def get_competition_info(ctx: RunContext, name_or_code: str) -> dict:
    db = _db(ctx)
    key = (name_or_code or "").strip()
    comp = (
        db.query(Competition)
        .filter((Competition.code == key) | (Competition.name.like(f"%{key}%")) | (Competition.short_name.like(f"%{key}%")))
        .first()
    )
    if not comp:
        return {"found": False, "message": f"未找到赛事「{key}」"}
    editions = (
        db.query(Edition).filter(Edition.competition_id == comp.id).order_by(Edition.year.desc()).all()
    )
    current = editions[0] if editions else None
    return {
        "found": True,
        "code": comp.code,
        "name": comp.name,
        "level": comp.level,
        "category": comp.category,
        "organizer": comp.organizer,
        "official_url": comp.official_url,
        "majors": comp.majors,
        "grades": comp.grades,
        "difficulty": comp.difficulty,
        "workload": comp.workload,
        "description": comp.description,
        "editions": [
            {
                "year": e.year,
                "seq": e.seq,
                "status": e.status,
                "signup_start": e.signup_start.isoformat() if e.signup_start else None,
                "signup_end": e.signup_end.isoformat() if e.signup_end else None,
                "contest_start": e.contest_start.isoformat() if e.contest_start else None,
                "contest_end": e.contest_end.isoformat() if e.contest_end else None,
                "fee": e.fee,
                "venue": e.venue,
                "notice_title": e.notice_title,
                "rules": e.rules_json or {},
            }
            for e in editions
        ],
        "current": {
            "year": current.year if current else None,
            "rules": current.rules_json if current else {},
        },
    }


# ---------------------------------------------------------------- 学生画像
@tool("student_profile", "按学号或姓名查询学生画像与参赛历史", {"sno": "", "name": ""})
def student_profile(ctx: RunContext, sno: str = "", name: str = "") -> dict:
    return stats_svc.student_history(_db(ctx), sno=sno or None, name=name or None)


@tool(
    "recommend_candidates",
    "根据学生专业、年级、技术方向，用结构化规则从赛事库中筛出候选并打分（供后续重排序）",
    {"sno": "学号", "interests": "技术方向关键词，逗号分隔", "limit": "候选数量"},
)
def recommend_candidates(ctx: RunContext, sno: str = "", interests: str = "", limit: int = 12) -> dict:
    db = _db(ctx)
    student = db.query(Student).filter(Student.sno == sno).first() if sno else None
    if not student:
        return {"error": "未找到该学生", "items": []}

    current_year = dt.date.today().year
    grade_now = min(5, max(1, current_year - student.grade + 1))
    keywords = [k.strip() for k in (interests or "").replace("，", ",").split(",") if k.strip()]

    participated = {
        r[0]
        for r in db.query(Edition.competition_id)
        .join(Team, Team.edition_id == Edition.id)
        .filter((Team.leader_student_id == student.id))
        .all()
    }

    comps = db.query(Competition).filter(Competition.is_active.is_(True)).all()

    # 一次性取回最近届次与历史战绩，避免在循环里逐赛事查询
    latest_map: dict[int, Edition] = {}
    for ed in db.query(Edition).order_by(Edition.year.desc()).all():
        latest_map.setdefault(ed.competition_id, ed)

    agg_rows = (
        db.query(
            Edition.competition_id,
            func.count(Team.id),
            func.sum(case((Team.award_level != "无", 1), else_=0)),
        )
        .join(Team, Team.edition_id == Edition.id)
        .group_by(Edition.competition_id)
        .all()
    )
    agg_map = {cid: (int(cnt or 0), int(aw or 0)) for cid, cnt, aw in agg_rows}

    scored = []
    for c in comps:
        # 基准分 + 各项加减，理论满分 95（30+25+12+12+8+8）。
        # 基准分不能太高，否则“专业对口 + 年级合适 + 临近截止”会一起撞上 100 分封顶，
        # 列表里全是同一个分数，排序看起来就像没排。
        score = 30.0
        reasons: list[str] = []

        majors = [m for m in (c.majors or "").split(",") if m.strip()]
        if majors:
            if any(m in student.major or student.major in m for m in majors):
                score += 25
                reasons.append(f"专业对口（{c.majors}）")
            else:
                score -= 18
                reasons.append("专业匹配度低")
        else:
            reasons.append("不限专业")

        grades = [g.strip() for g in (c.grades or "").split(",") if g.strip()]
        if grades:
            if str(grade_now) in grades:
                score += 12
                reasons.append(f"适合{student.grade_label}参加")
            else:
                score -= 20
                reasons.append(f"该赛事面向 {'/'.join(grades)} 年级")
        else:
            reasons.append("年级不限")

        if c.id in participated:
            score -= 8
            reasons.append("已有参赛经历，可作为冲奖选择")

        if keywords:
            tag_text = f"{c.tags},{c.category},{c.description}"
            hit = [k for k in keywords if k in tag_text]
            if hit:
                score += 6 * min(2, len(hit))
                reasons.append(f"方向契合：{'、'.join(hit)}")

        latest = latest_map.get(c.id)
        days_left = None
        if latest and latest.signup_end:
            days_left = (latest.signup_end - dt.date.today()).days
            if days_left < 0:
                score -= 25
                reasons.append(f"{latest.year} 年报名已截止")
            elif days_left <= 14:
                score += 8
                reasons.append(f"距报名截止 {days_left} 天，需尽快启动")
            elif days_left <= 30:
                score += 6
                reasons.append(f"距报名截止 {days_left} 天")
            elif days_left <= 60:
                score += 3
                reasons.append(f"距报名截止 {days_left} 天")
        else:
            score -= 5
            reasons.append("本年通知未发布")

        total_teams, total_awards = agg_map.get(c.id, (0, 0))
        rate = (total_awards / total_teams) if total_teams else 0

        if c.difficulty >= 5 and grade_now <= 2:
            score -= 12
            reasons.append("难度较高，低年级参赛压力大")

        # 获奖率按连续值计入（原先只做 rate>=0.5 的固定 +6，
        # 会让“专业对口+年级合适+临近截止”的赛事全部落在 95 分，排名失去区分度）
        if total_teams:
            score += min(8.0, rate * 16.0)
            if rate >= 0.5:
                reasons.append(f"往年获奖率 {rate * 100:.0f}%")
        else:
            reasons.append("暂无往年数据，可参考性有限")

        scored.append(
            {
                "code": c.code,
                "name": c.name,
                "short_name": c.short_name,
                "level": c.level,
                "category": c.category,
                "difficulty": c.difficulty,
                "workload": c.workload,
                "majors": c.majors,
                "grades": c.grades,
                "latest_year": latest.year if latest else None,
                "signup_end": latest.signup_end.isoformat() if latest and latest.signup_end else None,
                "days_left": days_left,
                "history_teams": total_teams,
                "history_awards": total_awards,
                "award_rate": round(rate * 100, 1),
                "score": round(max(0.0, min(100.0, score)), 1),
                "reasons": reasons,
            }
        )

    scored.sort(key=lambda x: x["score"], reverse=True)
    return {
        "student": {
            "sno": student.sno,
            "name": student.name,
            "major": student.major,
            "grade": student.grade,
            "grade_label": student.grade_label,
            "interests": keywords,
        },
        "count": len(scored),
        "items": scored[: max(1, limit)],
    }


# ---------------------------------------------------------------- 数据查询
@tool(
    "query_teams",
    "按年份、赛事、级别、获奖等条件查询参赛项目明细",
    {"year": "", "competition": "", "level": "", "award_level": "", "teacher": "", "student": "", "limit": ""},
)
def query_teams(ctx: RunContext, **kwargs) -> dict:
    db = _db(ctx)
    f = stats_svc.Filters(**kwargs)
    limit = int(kwargs.get("limit") or 200)
    rows = stats_svc.detail_rows(db, f, limit=limit)
    return {"count": len(rows), "filters": f.describe(), "items": rows}


@tool(
    "aggregate_stats",
    "按维度聚合统计参赛与获奖数据（分组维度：year/competition/level/category/major/teacher/award_grade/award_level）",
    {"group_by": "分组维度", "year": "", "level": "", "award_grade": "", "major": "", "teacher": ""},
)
def aggregate_stats(ctx: RunContext, group_by: str = "year", **kwargs) -> dict:
    db = _db(ctx)
    f = stats_svc.Filters(**kwargs)
    return stats_svc.aggregate(db, f, group_by)


@tool("overview_stats", "竞赛工作总览：参赛项目数、获奖数、获奖率、经费总额等", {})
def overview_stats(ctx: RunContext) -> dict:
    return stats_svc.overview(_db(ctx))


@tool("teacher_ranking", "教师指导工作量排行", {"year": "", "limit": "20"})
def teacher_ranking(ctx: RunContext, year: str = "", limit: int = 20) -> dict:
    y = int(year) if str(year).isdigit() else None
    items = stats_svc.teacher_ranking(_db(ctx), year=y, limit=int(limit))
    return {"year": y, "items": items}


# ---------------------------------------------------------------- 经费
@tool(
    "compute_budget",
    "按赛项、人数、地点、报名费、天数测算预算明细",
    {"competition": "", "level": "", "people": "人数", "days": "天数", "fee": "报名费", "is_local": "是否本地"},
)
def compute_budget(ctx: RunContext, **kwargs) -> dict:
    return budget_svc.compute_budget(_db(ctx), kwargs)


@tool("get_budget_rules", "读取当前生效的经费开支标准", {})
def get_budget_rules(ctx: RunContext) -> dict:
    return budget_svc.get_rules(_db(ctx))


@tool("check_reimbursement", "校验报销单的票据完整性与预算符合性", {"items": "报销明细", "budget_amount": "批复金额"})
def check_reimbursement(ctx: RunContext, items: list | None = None, budget_amount: float = 0, **kwargs) -> dict:
    payload = {"items": items or [], "budget_amount": budget_amount}
    return budget_svc.check_reimbursement(_db(ctx), payload)


# ---------------------------------------------------------------- 队伍
@tool("list_teams_of_teacher", "查询某教师指导的全部项目", {"teacher": "姓名", "year": ""})
def list_teams_of_teacher(ctx: RunContext, teacher: str, year: str = "") -> dict:
    db = _db(ctx)
    q = (
        db.query(Team)
        .join(Teacher, Team.teacher_id == Teacher.id)
        .options(joinedload(Team.edition).joinedload(Edition.competition))
        .filter(Teacher.name.like(f"%{teacher}%"))
    )
    if str(year).isdigit():
        q = q.join(Edition, Team.edition_id == Edition.id).filter(Edition.year == int(year))
    rows = q.all()
    items = []
    for t in rows:
        ed = t.edition
        comp = ed.competition if ed else None
        items.append(
            {
                "year": ed.year if ed else None,
                "competition": (comp.short_name or comp.name) if comp else "",
                "project": t.project_name,
                "award_grade": t.award_grade,
                "award_level": t.award_level,
                "status": t.status,
            }
        )
    return {"teacher": teacher, "count": len(items), "items": items}


@tool("team_detail", "查询单个参赛项目的完整信息（含成员）", {"team_id": ""})
def team_detail(ctx: RunContext, team_id: int) -> dict:
    db = _db(ctx)
    t = (
        db.query(Team)
        .options(
            joinedload(Team.edition).joinedload(Edition.competition),
            joinedload(Team.leader),
            joinedload(Team.teacher),
        )
        .filter(Team.id == int(team_id))
        .first()
    )
    if not t:
        return {"found": False}
    ed = t.edition
    comp = ed.competition if ed else None
    return {
        "found": True,
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
        "members": stats_svc.team_members(db, t.id),
    }


@tool("search_teams_by_name", "按项目名称关键词搜索参赛项目，用于报销/借款时定位队伍", {"keyword": ""})
def search_teams_by_name(ctx: RunContext, keyword: str) -> dict:
    db = _db(ctx)
    rows = (
        db.query(Team)
        .options(joinedload(Team.edition).joinedload(Edition.competition))
        .filter(Team.project_name.like(f"%{keyword}%"))
        .limit(20)
        .all()
    )
    items = []
    for t in rows:
        ed = t.edition
        comp = ed.competition if ed else None
        items.append(
            {
                "team_id": t.id,
                "project": t.project_name,
                "year": ed.year if ed else None,
                "competition": (comp.short_name or comp.name) if comp else "",
                "level": comp.level if comp else "",
                "members": len(t.members),
            }
        )
    return {"count": len(items), "items": items}
