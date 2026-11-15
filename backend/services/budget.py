"""经费业务：预算测算、借款单、报销单与合规校验。

开支标准、科目、单据字段全部来自 system_config 表（key = budget_rules），
修改标准只需改数据，不需要改代码。
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy.orm import Session

from ..models import BudgetRequest, Student, SystemConfig, Team

DEFAULT_RULES: dict = {
    "version": "2024",
    "title": "学科竞赛经费开支标准（默认，可在系统配置中修改）",
    "categories": ["报名费", "差旅费", "住宿费", "材料费", "保险费", "其他"],
    "standards": {
        "报名费": {"unit": "队", "price": 0, "note": "按赛事通知据实，上限 1500 元/队"},
        "交通费": {
            "unit": "人·次",
            "price": {"本地": 60, "省内": 220, "省外": 700},
            "note": "按实际票价据实，省外原则上不超高铁二等座标准",
        },
        "住宿费": {
            "unit": "人·天",
            "price": {"本地": 0, "省内": 280, "省外": 380},
            "note": "原则上两人一间，超标部分自理",
        },
        "伙食补助": {"unit": "人·天", "price": {"本地": 0, "省内": 80, "省外": 100}, "note": "凭出差审批单发放"},
        "材料费": {"unit": "队", "price": 600, "note": "元器件、耗材、打印装订，单队上限 1000 元"},
        "保险费": {"unit": "人", "price": 30, "note": "竞赛期间人身意外险"},
    },
    "limits": {"单队总额": 12000, "材料费占比": 0.25},
    "required_attachments": ["竞赛通知", "参赛审批表", "发票原件", "行程单或签到表"],
}

NO_DIGIT = ("报名费", "材料费", "保险费")


# ---------------------------------------------------------------- 规则
def get_rules(db: Session) -> dict:
    row = db.query(SystemConfig).filter(SystemConfig.key == "budget_rules").first()
    if row and isinstance(row.value, dict) and row.value.get("standards"):
        return row.value
    return DEFAULT_RULES


def save_rules(db: Session, rules: dict) -> dict:
    row = db.query(SystemConfig).filter(SystemConfig.key == "budget_rules").first()
    if row:
        row.value = rules
    else:
        db.add(SystemConfig(key="budget_rules", value=rules, remark="经费开支标准"))
    db.commit()
    return rules


def _price_of(rule: dict, scope: str) -> float:
    price = rule.get("price", 0)
    if isinstance(price, dict):
        return float(price.get(scope, price.get("省外", 0)))
    return float(price or 0)


def _scope_of(level: str, is_local: bool, distance: str | None) -> str:
    if distance in {"本地", "省内", "省外"}:
        return distance
    if is_local:
        return "本地"
    if level == "国家级":
        return "省外"
    if level in {"省级", "行业级"}:
        return "省内"
    return "本地"


# ---------------------------------------------------------------- 预算
_PEOPLE_KEYS = ("people", "team_size", "size", "member_count", "人数", "members")
_DAY_KEYS = ("days", "duration", "天数")
_SCOPE_KEYS = ("distance", "location", "scope", "地点", "place")
_COMP_KEYS = ("competition", "competition_name", "赛事", "contest")
_TEAM_KEYS = ("team_name", "project_name", "project", "队伍名称")


def _alias(payload: dict, keys: tuple[str, ...]):
    """按别名顺序取第一个有值的字段，兼容前端/Agent 不同的入参命名。"""
    for k in keys:
        v = payload.get(k)
        if v not in (None, "", 0):
            return v
    return None


def normalize_payload(payload: dict) -> dict:
    p = dict(payload or {})
    if p.get("people") in (None, "", 0):
        v = _alias(p, _PEOPLE_KEYS)
        if v is not None:
            p["people"] = v
    if p.get("days") in (None, "", 0):
        v = _alias(p, _DAY_KEYS)
        if v is not None:
            p["days"] = v
    if not p.get("distance"):
        v = _alias(p, _SCOPE_KEYS)
        if v in {"本地", "省内", "省外"}:
            p["distance"] = v
    if not p.get("competition"):
        v = _alias(p, _COMP_KEYS)
        if v:
            p["competition"] = str(v)
    if not p.get("team_name"):
        v = _alias(p, _TEAM_KEYS)
        if v:
            p["team_name"] = str(v)
    return p


def compute_budget(db: Session, payload: dict) -> dict:
    """根据赛项、人数、地点、报名费、天数测算预算明细。"""
    payload = normalize_payload(payload)
    rules = get_rules(db)
    std = rules.get("standards", {})
    level = (payload.get("level") or "省级").strip()
    people = max(1, int(payload.get("people") or 1))
    days = max(1, int(payload.get("days") or 1))
    scope = _scope_of(level, bool(payload.get("is_local")), payload.get("distance"))
    fee = float(payload.get("fee") or 0)
    team_name = (payload.get("team_name") or "").strip()
    competition = (payload.get("competition") or "").strip()

    items: list[dict] = []

    fee_rule = std.get("报名费", {})
    fee_cap = 1500.0
    if fee > 0:
        items.append(
            {
                "name": "报名费",
                "spec": f"{competition} 参赛报名费" if competition else "参赛报名费",
                "unit": str(fee_rule.get("unit", "队")),
                "qty": 1,
                "price": round(min(fee, fee_cap), 2),
                "amount": round(min(fee, fee_cap), 2),
                "note": "超出标准部分不予报销" if fee > fee_cap else "",
                "category": "报名费",
            }
        )

    if scope != "本地":
        t_price = _price_of(std.get("交通费", {}), scope)
        if t_price > 0:
            items.append(
                {
                    "name": "交通费",
                    "spec": f"{scope}往返，{people} 人",
                    "unit": str(std.get("交通费", {}).get("unit", "人·次")),
                    "qty": people,
                    "price": t_price,
                    "amount": round(t_price * people, 2),
                    "note": "按实际票价据实报销",
                    "category": "差旅费",
                }
            )
        h_price = _price_of(std.get("住宿费", {}), scope)
        if h_price > 0:
            nights = max(1, days - 1)
            items.append(
                {
                    "name": "住宿费",
                    "spec": f"{scope}，{people} 人 × {nights} 晚",
                    "unit": str(std.get("住宿费", {}).get("unit", "人·天")),
                    "qty": people * nights,
                    "price": h_price,
                    "amount": round(h_price * people * nights, 2),
                    "note": "两人一间，超标部分自理",
                    "category": "住宿费",
                }
            )
        m_price = _price_of(std.get("伙食补助", {}), scope)
        if m_price > 0:
            items.append(
                {
                    "name": "伙食补助",
                    "spec": f"{people} 人 × {days} 天",
                    "unit": "人·天",
                    "qty": people * days,
                    "price": m_price,
                    "amount": round(m_price * people * days, 2),
                    "note": "凭出差审批单发放",
                    "category": "差旅费",
                }
            )

    mat_price = _price_of(std.get("材料费", {}), scope)
    if mat_price > 0:
        items.append(
            {
                "name": "材料费",
                "spec": "元器件、耗材及打印装订",
                "unit": "队",
                "qty": 1,
                "price": mat_price,
                "amount": round(mat_price, 2),
                "note": "",
                "category": "材料费",
            }
        )

    ins_price = _price_of(std.get("保险费", {}), scope)
    if ins_price > 0:
        items.append(
            {
                "name": "保险费",
                "spec": f"竞赛期间人身意外险，{people} 人",
                "unit": "人",
                "qty": people,
                "price": ins_price,
                "amount": round(ins_price * people, 2),
                "note": "",
                "category": "保险费",
            }
        )

    for extra in payload.get("extras") or []:
        qty = float(extra.get("qty") or 1)
        price = float(extra.get("price") or 0)
        if price <= 0:
            continue
        items.append(
            {
                "name": (extra.get("name") or "其他支出").strip(),
                "spec": (extra.get("spec") or "").strip(),
                "unit": (extra.get("unit") or "项").strip(),
                "qty": qty,
                "price": price,
                "amount": round(qty * price, 2),
                "note": (extra.get("note") or "").strip(),
                "category": "其他",
            }
        )

    total = round(sum(i["amount"] for i in items), 2)
    warnings = check_budget_rules(rules, items, total)

    return {
        "items": items,
        "total": total,
        "scope": scope,
        "people": people,
        "days": days,
        "team_name": team_name,
        "competition": competition,
        "level": level,
        "warnings": warnings,
        "rules_version": rules.get("version"),
        "rules_title": rules.get("title"),
        "statement": budget_statement(
            competition, team_name, people, days, scope, total,
            item_names=[i["name"] for i in items],
        ),
    }


def check_budget_rules(rules: dict, items: list[dict], total: float) -> list[dict]:
    warnings: list[dict] = []
    limits = rules.get("limits", {})
    cap = float(limits.get("单队总额", 0) or 0)
    if cap and total > cap:
        warnings.append(
            {"level": "高", "item": "总额", "problem": f"预算总额 {total:.2f} 元超过单队上限 {cap:.0f} 元", "advice": "压缩住宿天数或材料费"}
        )
    ratio_cap = float(limits.get("材料费占比", 0) or 0)
    if ratio_cap and total > 0:
        mat = sum(i["amount"] for i in items if i.get("category") == "材料费")
        if mat / total > ratio_cap:
            warnings.append(
                {
                    "level": "中",
                    "item": "材料费",
                    "problem": f"材料费占比 {mat / total * 100:.0f}%，超过 {ratio_cap * 100:.0f}% 的限制",
                    "advice": "调整科目结构或分年度申请",
                }
            )
    for it in items:
        if it["qty"] <= 0 or it["price"] <= 0:
            warnings.append({"level": "低", "item": it["name"], "problem": "数量或单价为 0", "advice": "核实后填写"})
    return warnings


def budget_statement(
    competition: str,
    team_name: str,
    people: int,
    days: int,
    scope: str,
    total: float,
    item_names: list[str] | None = None,
) -> str:
    """生成可粘贴进申请书的预算说明。

    item_names 传入实际明细科目，避免出现“说明里写了报名费、明细里却没有”的口径不一致。
    """
    comp = competition or "该项竞赛"
    team = f"（{team_name}）" if team_name else ""
    if item_names:
        names = [n for n in item_names if n]
        if len(names) == 1:
            scope_text = names[0]
        else:
            scope_text = "、".join(names[:-1]) + "及" + names[-1]
    else:
        scope_text = "报名费、往返交通费、住宿费、伙食补助、参赛材料费及保险费"
    return (
        f"本次{comp}{team}拟选派 {people} 名学生参加，赛程 {days} 天，参赛地点属{scope}范围。"
        f"依据学院学科竞赛经费开支标准，预算内容包括{scope_text}，合计 {total:.2f} 元。各项均按标准据实测算，"
        f"比赛结束后凭正式发票及相关审批材料据实报销，节余部分不予保留。"
        f"妥否，请审批。"
    )


# ---------------------------------------------------------------- 单号
NO_FIELD = {"BUD": "budget_no", "LOA": "loan_no", "REI": "reimb_no"}


def next_no(db: Session, prefix: str, model) -> str:  # noqa: ANN001
    """生成单号：前缀 + 日期 + 当日序号，如 BUD20261115001。"""
    col = getattr(model, NO_FIELD[prefix])
    today = dt.date.today().strftime("%Y%m%d")
    like = f"{prefix}{today}%"
    count = db.query(col).filter(col.like(like)).count()
    return f"{prefix}{today}{count + 1:03d}"


# ---------------------------------------------------------------- 借款
def build_loan(db: Session, payload: dict) -> dict:
    budget_id = payload.get("budget_id")
    budget = db.get(BudgetRequest, int(budget_id)) if budget_id else None

    if budget:
        approved = budget.approved_amount or budget.total
        items = budget.items or []
        title = budget.title
        team_id = budget.team_id
    else:
        approved = float(payload.get("amount") or 0)
        items = payload.get("items") or []
        title = payload.get("title") or ""
        team_id = payload.get("team_id")

    team = db.get(Team, int(team_id)) if team_id else None
    team_name = team.project_name if team else (payload.get("team_name") or "")
    competition = ""
    if team and team.edition and team.edition.competition:
        competition = team.edition.competition.short_name or team.edition.competition.name

    people = int(payload.get("people") or 0) or 3
    scope = payload.get("distance") or payload.get("location") or "省内"
    if scope not in {"本地", "省内", "省外"}:
        scope = "省内"
    purpose = payload.get("purpose") or (
        f"用于{competition or '学科竞赛'}{team_name}参赛期间的报名、交通、住宿及材料支出"
        if (competition or team_name)
        else "用于学科竞赛参赛支出"
    )

    borrower = payload.get("borrower") or (team.leader.name if team and team.leader else "")
    if not borrower and payload.get("sno"):
        stu = db.query(Student).filter(Student.sno == str(payload["sno"])).first()
        borrower = stu.name if stu else ""

    warnings: list[dict] = []
    if approved <= 0:
        warnings.append({"level": "高", "item": "借款金额", "problem": "金额为 0，无法生成借款单", "advice": "先完成预算审批"})
    if budget and budget.status not in {"已批准", "已提交"}:
        warnings.append(
            {"level": "中", "item": "预算状态", "problem": f"关联预算当前状态为「{budget.status}」", "advice": "建议预算批准后再办理借款"}
        )

    return {
        "budget_no": budget.budget_no if budget else "",
        "title": title,
        "amount": round(approved, 2),
        "amount_cn": money_to_chinese(approved),
        "borrower": borrower,
        "payee": payload.get("payee") or "",
        "bank_account": payload.get("bank_account") or "",
        "purpose": purpose,
        "team_name": team_name,
        "competition": competition,
        "people": people,
        "scope": scope,
        "items": items,
        "warnings": warnings,
        "attachments": ["竞赛通知", "参赛审批表", "预算批复单"],
    }


# ---------------------------------------------------------------- 报销
_REIMB_ITEM_ALIASES = (
    ("name", ("item", "category", "科目")),
    ("amount", ("money", "金额")),
    ("invoice_no", ("invoice_code", "发票号", "ticket_no")),
    ("invoice_date", ("date", "开票日期", "ticket_date")),
)


def _norm_reimb_item(it: dict) -> dict:
    """兼容前端与 Agent 的字段命名差异（item/name、date/invoice_date 等）。"""
    out = dict(it)
    for key, aliases in _REIMB_ITEM_ALIASES:
        if out.get(key) in (None, ""):
            for a in aliases:
                v = out.get(a)
                if v not in (None, "", 0):
                    out[key] = v
                    break
    return out


def check_reimbursement(db: Session, payload: dict) -> dict:
    items = [_norm_reimb_item(i) for i in (payload.get("items") or [])]
    total = round(sum(float(i.get("amount") or 0) for i in items), 2)
    budget_id = payload.get("budget_id")
    budget = db.get(BudgetRequest, int(budget_id)) if budget_id else None
    approved = (budget.approved_amount or budget.total) if budget else float(payload.get("budget_amount") or 0)

    issues: list[dict] = []
    for idx, it in enumerate(items, start=1):
        name = it.get("name") or f"第 {idx} 项"
        amount = float(it.get("amount") or 0)
        if amount <= 0:
            issues.append({"level": "高", "item": name, "problem": "金额为空或为 0", "fix": "按票据实际金额填写"})
        if not it.get("invoice_no"):
            issues.append({"level": "高", "item": name, "problem": "缺少发票号", "fix": "补充发票号或说明无票原因"})
        if not it.get("invoice_date"):
            issues.append({"level": "中", "item": name, "problem": "缺少开票日期", "fix": "补充开票日期"})
        note = f"{name} {it.get('note') or ''} {it.get('invoice_type') or ''}"
        if any(k in note for k in ("餐饮", "餐费", "聚餐")) and "伙食" not in name:
            issues.append(
                {"level": "中", "item": name, "problem": "餐饮类支出一般不在竞赛经费列支范围", "fix": "改为伙食补助科目或自行承担"}
            )

    over = round(total - approved, 2) if approved else 0.0
    if approved and total > approved + 0.01:
        issues.append(
            {
                "level": "高",
                "item": "总额",
                "problem": f"实际支出 {total:.2f} 元超出批复预算 {approved:.2f} 元，超支 {over:.2f} 元",
                "fix": "补充超支说明并履行审批，或核减不予报销部分",
            }
        )

    rules = get_rules(db)
    required = rules.get("required_attachments", [])
    provided = set(payload.get("attachments") or [])
    missing = [a for a in required if a not in provided]

    high = sum(1 for i in issues if i["level"] == "高")
    passed = high == 0 and not missing

    conclusion = (
        "材料齐全，金额在批复预算内，可提交报销。"
        if passed
        else f"存在 {high} 项高风险问题" + (f"、缺 {len(missing)} 项附件" if missing else "") + "，建议修正后再提交。"
    )

    return {
        "pass": passed,
        "total": total,
        "approved": round(float(approved or 0), 2),
        "over_budget": max(0.0, over),
        "issues": issues,
        "missing_attachments": missing,
        "provided_attachments": sorted(provided),
        "conclusion": conclusion,
    }


# ---------------------------------------------------------------- 金额大写
_DIGITS = "零壹贰叁肆伍陆柒捌玖"
_UNITS = ["", "拾", "佰", "仟"]
_BIG = ["", "万", "亿"]


def money_to_chinese(amount: float) -> str:
    """人民币金额转大写，用于借款单/报销单。"""
    if amount is None:
        return "零元整"
    amount = round(float(amount) + 1e-9, 2)
    negative = amount < 0
    amount = abs(amount)
    yuan = int(amount)
    jiao = int(round((amount - yuan) * 100)) // 10
    fen = int(round((amount - yuan) * 100)) % 10

    if yuan == 0:
        head = "零"
    else:
        groups: list[str] = []
        n = yuan
        gi = 0
        while n > 0:
            seg = n % 10000
            if seg:
                groups.append(_seg_to_cn(seg) + _BIG[gi])
            else:
                if groups and not groups[-1].startswith("零"):
                    groups.append("零")
            n //= 10000
            gi += 1
        head = "".join(reversed(groups)).rstrip("零")

    out = f"{head}元" if head else "零元"
    if jiao == 0 and fen == 0:
        out += "整"
    else:
        out += (_DIGITS[jiao] + "角") if jiao else "零"
        if fen:
            out += _DIGITS[fen] + "分"
    return ("人民币" if not negative else "负") + out


def _seg_to_cn(seg: int) -> str:
    s = ""
    zero = False
    for i in range(3, -1, -1):
        d = (seg // (10**i)) % 10
        if d == 0:
            zero = True
        else:
            if zero and s:
                s += "零"
            s += _DIGITS[d] + _UNITS[i]
            zero = False
    return s
