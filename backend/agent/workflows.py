"""智能体工作流定义（10 项业务能力）。

每个工作流都是一张 StateGraph：
    节点 = 确定性处理步骤（检索、查询、计算、校验）
    条件边 = 依据"是否有可用大模型 / 检索是否命中"分流
大模型只出现在"组织语言"和"重排序"节点，所有事实性内容来自工具返回值。
"""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any

from ..config import settings
from ..llm import llm
from ..models import Competition, Student, Teacher
from ..rag.index import get_index
from ..services import budget as budget_svc
from ..services import stats as stats_svc
from . import prompts
from .compose import (
    build_citations as _citations,
    core_coverage,
    extractive_answer,
    hits_to_context as _hits_to_context,
    llm_or_none,
)
from .graph import CompiledGraph, RunContext, StateGraph
from .tools import call_tool


# ================================================================ 1. 知识问答
def _qa_analyze(state: dict, ctx: RunContext) -> dict:
    question = (state.get("question") or "").strip()
    if not question:
        raise ValueError("问题不能为空")
    kind = "通用"
    for k, words in {
        "时间节点": ["截止", "时间", "什么时候", "几月", "日程", "报名期"],
        "材料要求": ["材料", "提交", "申报书", "格式", "字数", "附件"],
        "奖项设置": ["奖项", "奖金", "名额", "一等奖", "比例"],
        "报名条件": ["条件", "资格", "能不能", "要求", "限制"],
        "经费政策": ["报销", "经费", "预算", "借款", "费用"],
    }.items():
        if any(w in question for w in words):
            kind = k
            break
    return {"kind": kind, "retrieve_query": question}


def _qa_retrieve(state: dict, ctx: RunContext) -> dict:
    q = state.get("retrieve_query") or state.get("question")
    index = get_index(ctx.db)
    hits = index.search(q, top_k=settings.RETRIEVE_TOP_K)
    return {
        "hits": hits,
        "hit_count": len(hits),
        "max_score": round(hits[0].score, 4) if hits else 0.0,
    }


def _qa_grade(state: dict) -> str:
    """决定"能不能答"。

    三道闸门：没有检索结果 / 相关度太低 / 问题核心词覆盖不足。

    第三道是关键。检索分数本身分不开"问了个知识库没提的东西"和"问了个有的东西"——
    因为"报名""赛事"这类泛词在语料里到处都是，分数照样不低。而核心词覆盖率
    （问题里的实词有多少能在片段中找到）区分度明显：样例知识库实测，可答问题
    ≥0.62，不可答问题 ≤0.55。

    有模型时放宽阈值，因为模型有能力处理同义表述；无模型时收紧，宁可拒答也不硬答。
    """
    hits = state.get("hits") or []
    if not hits:
        return "no_hit"
    if state.get("max_score", 0) < settings.RETRIEVE_MIN_SCORE:
        return "weak"

    min_cov = 0.30 if llm.available else 0.60
    if core_coverage(state.get("question", ""), hits) < min_cov:
        return "weak"
    return "answer"


def _qa_answer(state: dict, ctx: RunContext) -> dict:
    hits = state.get("hits") or []
    context = _hits_to_context(hits)
    text = llm_or_none(
        [
            {"role": "system", "content": prompts.SYSTEM_QA},
            {"role": "user", "content": prompts.QA_USER.format(context=context, question=state["question"])},
        ]
    )
    if text:
        return {"answer": text, "mode": "llm", "citations": _citations(hits)}
    return {"answer": extractive_answer(state["question"], hits), "mode": "extractive", "citations": _citations(hits)}


def _qa_no_hit(state: dict, ctx: RunContext) -> dict:
    doc_count = call_tool("knowledge_stats", ctx)["doc_count"]
    reasons = ["问题中的赛事名称或文件名与知识库中的记录不一致"]
    if doc_count == 0:
        reasons = ["知识库尚未导入任何文件"]
    text = prompts.NO_HIT_ANSWER.format(question=state["question"], reasons="\n".join(f"- {r}" for r in reasons), doc_count=doc_count)
    return {"answer": text, "mode": "no_hit", "citations": _citations(state.get("hits") or [])}


def build_qa() -> StateGraph:
    g = StateGraph("知识问答")
    g.add_node("analyze", _qa_analyze, "识别问题类型，构造检索语句")
    g.add_node("retrieve", _qa_retrieve, "知识库混合检索（BM25 + 向量）")
    g.add_node("answer", _qa_answer, "依据片段生成带引用的回答")
    g.add_node("no_hit", _qa_no_hit, "未命中时如实告知并给出改进建议")
    g.set_entry_point("analyze")
    g.add_edge("analyze", "retrieve")
    g.add_conditional_edges("retrieve", _qa_grade, {"answer": "answer", "no_hit": "no_hit", "weak": "no_hit"})
    g.set_finish_point("answer")
    return g


# ================================================================ 2. 竞赛推荐
def _rec_profile(state: dict, ctx: RunContext) -> dict:
    payload = state.get("input") or {}
    sno = payload.get("sno") or state.get("sno") or ""
    interests = payload.get("interests") or state.get("interests") or ""
    prof = call_tool("student_profile", ctx, sno=sno)
    if not prof.get("student"):
        raise ValueError(f"未找到学号为 {sno} 的学生")
    return {"student": prof["student"], "history": prof["teams"], "interests": interests}


def _rec_candidates(state: dict, ctx: RunContext) -> dict:
    sno = state["student"]["sno"]
    res = call_tool("recommend_candidates", ctx, sno=sno, interests=state.get("interests", ""), limit=10)
    return {"candidates": res.get("items", [])}


def _rec_route(state: dict) -> str:
    return "llm" if llm.available and (state.get("candidates") or []) else "rule"


def _rec_llm(state: dict, ctx: RunContext) -> dict:
    cands = state["candidates"]
    compact = [
        {
            "code": c["code"],
            "name": c["name"],
            "level": c["level"],
            "difficulty": c["difficulty"],
            "majors": c["majors"],
            "history_awards": c["history_awards"],
            "award_rate": c["award_rate"],
            "days_left": c["days_left"],
            "score": c["score"],
        }
        for c in cands
    ]
    data = llm.chat_json(
        [
            {"role": "system", "content": "你是竞赛匹配专家，只输出 JSON。"},
            {
                "role": "user",
                "content": prompts.RECOMMEND_RERANK.format(
                    profile=json.dumps(state["student"], ensure_ascii=False),
                    candidates=json.dumps(compact, ensure_ascii=False),
                ),
            },
        ]
    )
    items = (data or {}).get("items") or []
    by_code = {c["code"]: c for c in cands}
    merged = []
    for it in items[:6]:
        base = by_code.get(it.get("code"))
        if not base:
            continue
        merged.append({**base, "tier": it.get("tier", ""), "llm_reason": it.get("reason", ""), "prepare_weeks": it.get("prepare_weeks")})
    if not merged:
        return _rec_rule(state, ctx)
    return {"recommendations": merged, "mode": "llm"}


def _rec_rule(state: dict, ctx: RunContext) -> dict:
    cands = state.get("candidates") or []
    out = []
    for c in cands[:6]:
        tier = "冲刺" if c["difficulty"] >= 4 else ("稳妥" if c["score"] >= 60 else "保底")
        out.append({**c, "tier": tier, "llm_reason": "", "prepare_weeks": 4 + c["difficulty"]})
    return {"recommendations": out, "mode": "rule"}


def _rec_format(state: dict, ctx: RunContext) -> dict:
    stu = state["student"]
    recs = state.get("recommendations") or []
    if not recs:
        return {"answer": "当前没有可推荐的赛事，请先在赛事库中维护赛事信息。", "data": {"recommendations": []}}
    lines = [
        f"{stu['name']}（{stu['major']}，{stu['grade_label']}）适合参加的竞赛，按匹配度排序：",
        "",
    ]
    for i, r in enumerate(recs, start=1):
        reason = r.get("llm_reason") or "；".join(r.get("reasons", [])[:3])
        lines.append(f"{i}. {r['name']}（{r['level']}｜{r['tier']}｜匹配度 {r['score']}）")
        lines.append(f"   {reason}")
        if r.get("signup_end"):
            lines.append(f"   最近报名截止：{r['signup_end']}")
        lines.append("")
    lines.append("说明：匹配度由专业对口度、年级适配、报名时间、往年获奖率、备赛难度等规则加权计算，可解释、可复核。")
    return {
        "answer": "\n".join(lines).strip(),
        "data": {"student": stu, "recommendations": recs, "history": state.get("history", [])},
    }


def build_recommend() -> StateGraph:
    g = StateGraph("竞赛推荐")
    g.add_node("profile", _rec_profile, "读取学生画像与参赛历史")
    g.add_node("candidates", _rec_candidates, "规则引擎筛选候选并打分")
    g.add_node("rerank_llm", _rec_llm, "大模型重排序并生成理由")
    g.add_node("rerank_rule", _rec_rule, "无模型时按规则分层")
    g.add_node("format", _rec_format, "组织推荐结论")
    g.set_entry_point("profile")
    g.add_edge("profile", "candidates")
    g.add_conditional_edges("candidates", _rec_route, {"llm": "rerank_llm", "rule": "rerank_rule"})
    g.add_edge("rerank_llm", "format")
    g.add_edge("rerank_rule", "format")
    g.set_finish_point("format")
    return g


# ================================================================ 3. 备赛辅助
def _prep_resolve(state: dict, ctx: RunContext) -> dict:
    payload = state.get("input") or {}
    name = (payload.get("competition") or state.get("competition") or "").strip()
    team_id = payload.get("team_id")
    info = {}
    if team_id:
        d = call_tool("team_detail", ctx, team_id=int(team_id))
        if d.get("found"):
            info = d
            name = name or d.get("competition", "")
    if name:
        comp = call_tool("get_competition_info", ctx, name_or_code=name)
        if comp.get("found"):
            info.update({"competition_info": comp})
    if not info:
        raise ValueError(f"未找到赛事「{name}」，请检查名称")
    return {"competition": name, "info": info}


def _prep_retrieve(state: dict, ctx: RunContext) -> dict:
    name = state["competition"]
    queries = [f"{name} 报名条件 参赛要求", f"{name} 提交材料 格式要求", f"{name} 时间安排 赛程", f"{name} 评审标准 奖项"]
    index = get_index(ctx.db)
    hits = index.search_multi(queries, top_k=8)
    return {"hits": hits}


def _pick_deadline(editions: list[dict], today: dt.date) -> dict:
    """在多个赛季中选出真正的“下一个关键时间点”。

    原先直接取 editions[0] 的 signup_end，一旦该赛季已结束就会算出负数天数，
    排期表出现「2026-11-15 → 2026-06-09 共 -158 天」这类明显错误的输出。
    这里改为：优先选尚未到来的最早节点；全部过期时退回默认备赛窗口，不编造截止日。
    """
    cands: list[tuple[dt.date, str, int | None]] = []
    for e in editions:
        for key, label in (("signup_end", "报名截止"), ("contest_start", "开赛")):
            v = e.get(key)
            if not v:
                continue
            try:
                d = dt.date.fromisoformat(v)
            except (ValueError, TypeError):
                continue
            cands.append((d, label, e.get("year")))
    future = [c for c in cands if c[0] >= today]
    if future:
        d, label, year = min(future, key=lambda x: x[0])
        return {"date": d, "label": label, "year": year, "expired": False}
    if cands:
        d, label, year = max(cands, key=lambda x: x[0])
        return {"date": d, "label": label, "year": year, "expired": True}
    return {"date": None, "label": "", "year": None, "expired": False}


def _prep_plan(state: dict, ctx: RunContext) -> dict:
    payload = state.get("input") or {}
    info = state.get("info", {})
    comp_info = info.get("competition_info") or {}
    editions = comp_info.get("editions") or []
    today = dt.date.today()

    picked = _pick_deadline(editions, today)
    deadline = None if picked["expired"] else picked["date"]
    if deadline:
        days = max(3, (deadline - today).days)
    else:
        # 本赛季已结束或赛程未定：按给定/默认备赛窗口排期，不假装有截止日
        try:
            days = max(3, int(payload.get("days") or 30))
        except (TypeError, ValueError):
            days = 30

    # 规程取对应赛季，找不到就用最新赛季
    target = picked.get("year")
    edition = next((e for e in editions if e.get("year") == target), editions[0] if editions else {})
    rules = edition.get("rules") or (comp_info.get("current") or {}).get("rules") or {}

    expired_note = ""
    if picked["expired"] and picked["date"]:
        expired_note = (
            f"该赛事最近一次{picked['label']}为 {picked['date'].isoformat()}"
            f"（{picked['year']} 赛季），已结束。以下按 {days} 天备赛窗口排期，"
            f"新赛季通知发布后请重新生成以对齐真实截止日。"
        )

    text = llm_or_none(
        [
            {"role": "system", "content": "你是备赛规划助手。"},
            {
                "role": "user",
                "content": prompts.PREP_PLAN.format(
                    competition=json.dumps(comp_info or {"name": state["competition"]}, ensure_ascii=False)[:1500],
                    team=json.dumps(info.get("project") or info.get("team", {}) or {}, ensure_ascii=False)[:500],
                    days=days,
                    context=_hits_to_context(state.get("hits") or [], 6),
                ),
            },
        ]
    )

    plan = _rule_plan(state["competition"], rules, days, deadline)
    plan["deadline_label"] = picked["label"]
    plan["expired"] = picked["expired"]
    if expired_note:
        plan["note"] = expired_note

    if text:
        if expired_note:
            text = f"> {expired_note}\n\n{text}"
        return {"plan_markdown": text, "plan_rule": plan, "mode": "llm", "days": days, "deadline": deadline}
    return {"plan_markdown": _rule_plan_markdown(plan), "plan_rule": plan, "mode": "rule", "days": days, "deadline": deadline}


def _split_days(total: int, weights: list[float]) -> list[int]:
    """把总天数按权重拆成整数天，保证各阶段之和恰好等于 total 且每段至少 1 天。"""
    n = len(weights)
    total = max(int(total), n)
    s = sum(weights) or 1.0
    exact = [total * w / s for w in weights]
    ints = [int(x) for x in exact]
    order = sorted(range(n), key=lambda i: exact[i] - ints[i], reverse=True)
    for i in order[: total - sum(ints)]:
        ints[i] += 1
    while min(ints) < 1:
        j = ints.index(min(ints))
        k = max(range(n), key=lambda i: ints[i])
        if ints[k] <= 1:
            break
        ints[k] -= 1
        ints[j] += 1
    return ints


def _rule_plan(name: str, rules: dict, days: int, deadline: dt.date | None) -> dict:
    today = dt.date.today()
    # 有截止日时不能排出超过窗口的计划，否则后面的阶段会全部挤在截止日之后
    if deadline:
        window = (deadline - today).days
        if window >= 1:
            days = min(days, window)
    materials = rules.get("materials") or ["报名表", "参赛作品", "承诺书"]
    phases = [
        ("选题与组队", 0.15, ["确定选题方向", "组建 3-5 人队伍", "联系指导教师"]),
        ("方案设计", 0.25, ["完成技术方案；明确分工与排期", "准备开题材料"]),
        ("开发与实验", 0.35, ["主体工作推进", "中期自查", "指导教师评审"]),
        ("材料撰写", 0.15, ["撰写申报书/作品说明", "整理支撑材料", "内部预审"]),
        ("提交与答辩准备", 0.10, ["完成线上提交", "准备答辩 PPT", "模拟答辩"]),
    ]
    spans = _split_days(days, [r for _, r, _ in phases])
    schedule = []
    cursor = today
    for (pname, _ratio, tasks), span in zip(phases, spans):
        start = cursor
        end = start + dt.timedelta(days=span - 1)
        if deadline and end > deadline:
            end = deadline
        if end < start:
            end = start
        schedule.append(
            {
                "phase": pname,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "days": (end - start).days + 1,
                "tasks": tasks,
            }
        )
        cursor = end + dt.timedelta(days=1)
    return {
        "competition": name,
        "deadline": deadline.isoformat() if deadline else None,
        "total_days": days,
        "schedule": schedule,
        "materials": materials,
    }


def _rule_plan_markdown(plan: dict) -> str:
    lines = [f"## 时间计划（总 {plan['total_days']} 天）", ""]
    if plan.get("note"):
        lines += [f"> {plan['note']}", ""]
    if plan.get("deadline"):
        label = plan.get("deadline_label") or "关键节点"
        lines.append(f"{label}：{plan['deadline']}")
        lines.append("")
    lines.append("| 阶段 | 起 | 止 | 天数 | 主要任务 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for p in plan["schedule"]:
        lines.append(f"| {p['phase']} | {p['start']} | {p['end']} | {p['days']} | {'；'.join(p['tasks'])} |")
    lines += ["", "## 任务清单", ""]
    for p in plan["schedule"]:
        lines.append(f"**{p['phase']}**")
        for t in p["tasks"]:
            lines.append(f"- [ ] {t}")
        lines.append("")
    lines += ["## 材料准备清单", ""]
    for m in plan["materials"]:
        lines.append(f"- {m}")
    lines += ["", "> 本计划由规则引擎依据赛程倒排生成（未启用大模型时）。配置大模型后可获得结合规程原文的细化方案。"]
    return "\n".join(lines)


def _prep_format(state: dict, ctx: RunContext) -> dict:
    return {
        "answer": state.get("plan_markdown", ""),
        "data": {
            "competition": state.get("competition"),
            "days": state.get("days"),
            "deadline": state.get("deadline").isoformat() if state.get("deadline") else None,
            "plan": state.get("plan_rule"),
            "mode": state.get("mode"),
        },
        "citations": _citations(state.get("hits") or [], 5),
    }


def build_prep() -> StateGraph:
    g = StateGraph("备赛辅助")
    g.add_node("resolve", _prep_resolve, "定位赛事与队伍信息")
    g.add_node("retrieve", _prep_retrieve, "多角度检索规程要求")
    g.add_node("plan", _prep_plan, "倒排备赛计划与任务清单")
    g.add_node("format", _prep_format, "组织输出")
    g.set_entry_point("resolve")
    g.add_edge("resolve", "retrieve")
    g.add_edge("retrieve", "plan")
    g.add_edge("plan", "format")
    g.set_finish_point("format")
    return g


# ================================================================ 4. 材料评审
def _rev_extract(state: dict, ctx: RunContext) -> dict:
    payload = state.get("input") or {}
    content = payload.get("content") or ""
    filename = payload.get("filename") or ""
    if not content and payload.get("file_path"):
        from ..rag.loader import load_any
        from pathlib import Path

        blocks = load_any(Path(payload["file_path"]))
        content = "\n".join(b["text"] for b in blocks)
    if not content.strip():
        raise ValueError("未获取到材料内容，请上传文件或粘贴正文")
    return {
        "content": content[:12000],
        "char_count": len(content),
        "competition": payload.get("competition", ""),
        "filename": filename,
    }


def _rev_retrieve(state: dict, ctx: RunContext) -> dict:
    comp = state.get("competition") or ""
    queries = [f"{comp} 申报书 评审标准" if comp else "申报书 评审标准 要求", "参赛作品 评分细则", "申报材料 格式 字数 要求"]
    index = get_index(ctx.db)
    return {"hits": index.search_multi(queries, top_k=6)}


def _rev_review(state: dict, ctx: RunContext) -> dict:
    content = state["content"]
    hits = state.get("hits") or []
    data = llm.chat_json(
        [
            {"role": "system", "content": "你是竞赛材料评审专家，只输出 JSON。"},
            {
                "role": "user",
                "content": prompts.MATERIAL_REVIEW.format(
                    requirements=_hits_to_context(hits, 5) or "（知识库未检索到具体评审要求，按通用标准评估）",
                    content=content[:8000],
                ),
            },
        ]
    )
    if data and isinstance(data.get("issues"), list):
        return {"review": data, "mode": "llm"}
    return {"review": _rule_review(content), "mode": "rule"}


def _rule_review(content: str) -> dict:
    issues: list[dict] = []
    dims = []
    checks = {
        "创新点": ("创新点是否清晰", 15),
        "技术路线": ("技术路线是否说明", 15),
        "可行性": ("可行性分析", 10),
        "预期成果": ("预期成果", 10),
        "进度": ("进度安排", 8),
        "团队": ("团队分工", 8),
    }
    present = 0
    for kw, (desc, weight) in checks.items():
        if kw in content:
            present += weight
        else:
            issues.append(
                {
                    "severity": "中",
                    "location": "全文",
                    "problem": f"未找到「{kw}」相关表述",
                    "suggestion": f"补充一节明确说明{desc}，建议 150-300 字，配合图示。",
                }
            )
    dims.append({"name": "结构完整性", "score": min(100, 40 + present), "comment": f"识别到 {present} 项关键要素"})

    chars = len(content)
    if chars < 800:
        issues.append({"severity": "高", "location": "全文", "problem": f"正文仅 {chars} 字，篇幅明显不足", "suggestion": "多数竞赛要求申报书正文 1500 字以上，建议扩充技术细节与实验数据。"})
    dims.append({"name": "篇幅规范", "score": 90 if chars >= 1500 else (70 if chars >= 800 else 45), "comment": f"当前 {chars} 字"})

    vague = ["具有重要意义", "积极探索", "不断完善", "大大提升", "有效推动"]
    hits_vague = [v for v in vague if v in content]
    if hits_vague:
        issues.append(
            {
                "severity": "低",
                "location": "多处",
                "problem": f"存在空泛表述：{'、'.join(hits_vague)}",
                "suggestion": "替换为可量化描述，例如把「大大提升效率」改为「将处理时间从 X 分钟降至 Y 分钟」。",
            }
        )

    has_number = len(re.findall(r"\d+(?:\.\d+)?%|\d+\s*(?:人|项|次|天|小时|元)", content))
    if has_number < 3:
        issues.append({"severity": "中", "location": "全文", "problem": "量化数据偏少", "suggestion": "补充测试数据、对比指标或规模数据，评审通常关注可验证的结果。"})

    scores = [d["score"] for d in dims] + [75]
    total = int(sum(scores) / len(scores))
    questions = [
        "你的方案与已有工作相比，核心差异在哪一点？有没有量化对比？",
        "如果关键模块在比赛中出现故障，你的降级方案是什么？",
        "项目中最难的技术点是什么，你如何验证它已经解决？",
        "团队三名成员的具体分工如何体现，谁负责哪部分代码或实验？",
        "预期成果中的指标依据是什么，为什么是这个数值？",
        "项目周期内的时间安排是否留有缓冲，遇到延期如何调整？",
        "数据来源是否合规，涉及隐私信息如何处理？",
        "如果评委要求现场演示，你能在多长时间内完成？",
    ]
    return {
        "score": total,
        "dimensions": dims,
        "issues": issues,
        "defense_questions": questions,
        "note": "当前为规则校验结果（未启用大模型）。启用大模型后可获得逐句修改建议。",
    }


def _rev_format(state: dict, ctx: RunContext) -> dict:
    r = state["review"]
    lines = [f"材料初评得分：{r.get('score', 0)} 分（{state.get('char_count', 0)} 字）", ""]
    for d in r.get("dimensions", []):
        lines.append(f"· {d['name']}：{d['score']} 分 —— {d.get('comment', '')}")
    issues = r.get("issues", [])
    if issues:
        lines += ["", f"需要修改的问题（{len(issues)} 项）："]
        for i, it in enumerate(issues[:12], start=1):
            lines.append(f"{i}. [{it.get('severity')}] {it.get('problem')}")
            lines.append(f"   位置：{it.get('location')}")
            lines.append(f"   建议：{it.get('suggestion')}")
    lines += ["", "答辩预判问题："]
    for i, q in enumerate(r.get("defense_questions", [])[:8], start=1):
        lines.append(f"{i}. {q}")
    if r.get("note"):
        lines += ["", f"> {r['note']}"]
    return {
        "answer": "\n".join(lines),
        "data": {"review": r, "char_count": state.get("char_count"), "mode": state.get("mode")},
        "citations": _citations(state.get("hits") or [], 5),
    }


def build_review() -> StateGraph:
    g = StateGraph("材料评审")
    g.add_node("extract", _rev_extract, "抽取材料正文")
    g.add_node("retrieve", _rev_retrieve, "检索评审要求")
    g.add_node("review", _rev_review, "分维度检查并生成修改建议")
    g.add_node("format", _rev_format, "组织评审报告")
    g.set_entry_point("extract")
    g.add_edge("extract", "retrieve")
    g.add_edge("retrieve", "review")
    g.add_edge("review", "format")
    g.set_finish_point("format")
    return g


# ================================================================ 5. 预算申请
def _bud_parse(state: dict, ctx: RunContext) -> dict:
    # 先做别名归一，否则 team_size/人数 等写法会被下面的默认值覆盖成 3
    payload = budget_svc.normalize_payload(state.get("input") or {})
    if payload.get("team_id"):
        d = call_tool("team_detail", ctx, team_id=int(payload["team_id"]))
        if d.get("found"):
            payload.setdefault("competition", d.get("competition"))
            payload.setdefault("team_name", d.get("project"))
            payload.setdefault("level", d.get("level"))
    if not payload.get("people"):
        payload["people"] = 3
    if not payload.get("days"):
        payload["days"] = 3
    return {"budget_input": payload}


def _bud_compute(state: dict, ctx: RunContext) -> dict:
    res = budget_svc.compute_budget(ctx.db, state["budget_input"])
    return {"budget": res}


def _bud_check(state: dict, ctx: RunContext) -> dict:
    b = state["budget"]
    hits = get_index(ctx.db).search_multi(["经费开支标准 报销范围", "竞赛经费 管理办法"], top_k=4)
    data = llm.chat_json(
        [
            {"role": "system", "content": "你是经费预算审核助手，只输出 JSON。"},
            {
                "role": "user",
                "content": prompts.BUDGET_EXPLAIN.format(
                    context=_hits_to_context(hits, 4) or "（未检索到管理办法原文）",
                    items=json.dumps(b["items"], ensure_ascii=False),
                    total=b["total"],
                ),
            },
        ]
    )
    if data:
        return {"budget": {**b, "llm_check": data}, "check_mode": "llm", "hits": hits}
    return {"budget": b, "check_mode": "rule", "hits": hits}


def _bud_format(state: dict, ctx: RunContext) -> dict:
    b = state["budget"]
    warnings = b.get("warnings", [])
    llm_check = b.get("llm_check") or {}
    lines = [
        f"预算测算完成：{b.get('competition') or '赛事'}　{b.get('people')} 人 · {b.get('days')} 天 · {b.get('scope')}",
        f"预算总额：{b['total']:,.2f} 元",
        "",
        "明细：",
    ]
    for i, it in enumerate(b["items"], start=1):
        lines.append(f"{i}. {it['name']}　{it.get('spec', '')}　{it.get('qty')} × {it['price']:.2f} = {it['amount']:,.2f} 元")
    if warnings:
        lines += ["", "校验提示："]
        for w in warnings:
            lines.append(f"· [{w['level']}] {w['item']}：{w['problem']}（{w['advice']}）")
    for issue in llm_check.get("issues", [])[:5]:
        lines.append(f"· {issue.get('item')}：{issue.get('problem')}（{issue.get('advice')}）")
    if llm_check.get("missing_items"):
        lines.append("· 建议补充科目：" + "、".join(llm_check["missing_items"]))
    lines += ["", "预算说明（可直接粘贴进申请书）：", b.get("statement", "")]
    return {
        "answer": "\n".join(lines),
        "data": {"budget": b, "check_mode": state.get("check_mode")},
        "citations": _citations(state.get("hits") or [], 4),
    }


def build_budget() -> StateGraph:
    g = StateGraph("预算申请")
    g.add_node("parse", _bud_parse, "解析赛项、人数、地点、报名费")
    g.add_node("compute", _bud_compute, "按开支标准测算明细")
    g.add_node("check", _bud_check, "对照管理办法做合规校验")
    g.add_node("format", _bud_format, "输出明细与预算说明")
    g.set_entry_point("parse")
    g.add_edge("parse", "compute")
    g.add_edge("compute", "check")
    g.add_edge("check", "format")
    g.set_finish_point("format")
    return g


# ================================================================ 6. 借款
def _loan_build(state: dict, ctx: RunContext) -> dict:
    payload = state.get("input") or {}
    loan = budget_svc.build_loan(ctx.db, payload)
    return {"loan": loan}


def _loan_format(state: dict, ctx: RunContext) -> dict:
    loan = state["loan"]
    lines = [
        f"借款单要素已生成（金额 {loan['amount']:,.2f} 元，大写：{loan['amount_cn']}）",
        "",
        f"· 用途：{loan['purpose']}",
        f"· 经办人：{loan['borrower'] or '（待填）'}",
        f"· 关联预算：{loan['budget_no'] or '（未关联）'}",
        f"· 收款单位：{loan['payee'] or '（待填）'}",
        f"· 收款账号：{loan['bank_account'] or '（待填）'}",
        f"· 附单据：{'、'.join(loan['attachments'])}",
    ]
    if loan["warnings"]:
        lines += ["", "提示："] + [f"· [{w['level']}] {w['problem']}（{w['advice']}）" for w in loan["warnings"]]
    lines += ["", "可在「经费」页一键导出 Word 借款单。"]
    return {"answer": "\n".join(lines), "data": {"loan": loan}}


def build_loan() -> StateGraph:
    g = StateGraph("借款辅助")
    g.add_node("build", _loan_build, "依据批复预算与参赛信息填制借款单")
    g.add_node("format", _loan_format, "输出借款单要素与提示")
    g.set_entry_point("build")
    g.add_edge("build", "format")
    g.set_finish_point("format")
    return g


# ================================================================ 7. 报销
def _rei_check(state: dict, ctx: RunContext) -> dict:
    payload = state.get("input") or {}
    result = budget_svc.check_reimbursement(ctx.db, payload)
    hits = get_index(ctx.db).search_multi(["报销 票据 要求", "经费报销 材料"], top_k=4)
    data = llm.chat_json(
        [
            {"role": "system", "content": "你是报销审核助手，只输出 JSON。"},
            {
                "role": "user",
                "content": prompts.REIMBURSE_CHECK.format(
                    context=_hits_to_context(hits, 4) or "（未检索到报销规定原文）",
                    items=json.dumps(payload.get("items") or [], ensure_ascii=False),
                    budget=payload.get("budget_amount") or 0,
                    total=result["total"],
                ),
            },
        ]
    )
    if data:
        result["llm_check"] = data
    return {"reimburse": result, "hits": hits, "mode": "llm" if data else "rule"}


def _rei_format(state: dict, ctx: RunContext) -> dict:
    r = state["reimburse"]
    lines = [f"报销预审结论：{r['conclusion']}", f"实际支出 {r['total']:,.2f} 元，批复预算 {r['approved']:,.2f} 元"]
    if r.get("over_budget"):
        lines.append(f"超支 {r['over_budget']:,.2f} 元")
    if r["issues"]:
        lines += ["", f"问题清单（{len(r['issues'])} 项）："]
        for i, it in enumerate(r["issues"], start=1):
            lines.append(f"{i}. [{it['level']}] {it['item']}：{it['problem']}")
            lines.append(f"   处理：{it['fix']}")
    if r["missing_attachments"]:
        lines += ["", "缺失附件：" + "、".join(r["missing_attachments"])]
    llm_check = r.get("llm_check") or {}
    if llm_check.get("issues"):
        lines += ["", "制度比对补充意见："]
        for it in llm_check["issues"][:5]:
            lines.append(f"· [{it.get('level')}] {it.get('item')}：{it.get('problem')}")
    return {
        "answer": "\n".join(lines),
        "data": {"reimburse": r},
        "citations": _citations(state.get("hits") or [], 4),
    }


def build_reimburse() -> StateGraph:
    g = StateGraph("报销辅助")
    g.add_node("check", _rei_check, "校验票据要素与预算符合性")
    g.add_node("format", _rei_format, "输出审核结论")
    g.set_entry_point("check")
    g.add_edge("check", "format")
    g.set_finish_point("format")
    return g


# ================================================================ 8. 数据统计
_DIM_WORDS = {
    "year": ["年", "年度", "逐年", "每年"],
    # 注意不要收录“赛项”：它会被“参赛项目”误命中，导致随便问点什么都被按赛事分组
    "competition": ["赛事", "竞赛", "比赛"],
    "level": ["级别", "国家级", "省级", "校级"],
    "college": ["学院"],
    "major": ["专业"],
    "teacher": ["教师", "老师", "指导"],
    "award_grade": ["获奖级别"],
    "award_level": ["获奖等级", "奖项"],
}


def _st_parse(state: dict, ctx: RunContext) -> dict:
    payload = state.get("input") or {}
    question = (payload.get("question") or state.get("question") or "").strip()

    if payload.get("filters") or payload.get("group_by"):
        return {
            "filters": payload.get("filters") or {},
            "group_by": payload.get("group_by") or "year",
            "parsed_by": "explicit",
        }

    data = llm.chat_json(
        [
            {"role": "system", "content": "把自然语言查询转换为 JSON，只输出 JSON。"},
            {"role": "user", "content": prompts.QUERY_PARSE.format(question=question)},
        ]
    )
    if data:
        group_by = data.pop("group_by", None) or "year"
        data.pop("metric", None)
        return {"filters": {k: v for k, v in data.items() if v not in (None, "", "null")}, "group_by": group_by, "parsed_by": "llm"}

    # 规则解析兜底
    filters: dict[str, Any] = {}
    m = re.search(r"(20\d{2})\s*年", question)
    if m:
        filters["year"] = int(m.group(1))
    for lv in ("国家级", "省级", "校级"):
        if lv in question:
            filters["level"] = lv
            break
    for lv in ("特等奖", "一等奖", "二等奖", "三等奖", "优秀奖"):
        if lv in question:
            filters["award_level"] = lv
            break
    # 实体名匹配：问题里提到的专业 / 教师 / 赛事名直接转成过滤条件，
    # 否则“计算机科学与技术专业的参赛项目”会变成一张全专业榜单。
    if not filters.get("major"):
        majors = [m for (m,) in ctx.db.query(Student.major).distinct().all() if m]
        for m in sorted(majors, key=len, reverse=True):
            if m in question:
                filters["major"] = m
                break
    if not filters.get("teacher"):
        names = [n for (n,) in ctx.db.query(Teacher.name).distinct().all() if n and len(n) >= 2]
        for n in sorted(names, key=len, reverse=True):
            if n in question:
                filters["teacher"] = n
                break
    if not filters.get("competition"):
        cands: list[str] = []
        for full, short, code in ctx.db.query(Competition.name, Competition.short_name, Competition.code).all():
            for cand in (full, short, code):
                if cand and len(cand) >= 2:
                    cands.append(cand)
        for cand in sorted(cands, key=len, reverse=True):
            if cand in question:
                filters["competition"] = cand
                break
    # 只有明确说“只看获奖的/仅获奖项目”才过滤；
    # 原先是“出现获奖二字就过滤”，导致问“各学院获奖数量”时基数被裁成获奖项目，
    # 总数与获奖数相等、获奖率恒为 100%，属于用自己的分母算自己。
    if re.search(r"(只看|仅|只要)[^，。]{0,4}获奖", question) or "获奖项目" in question:
        filters["awarded_only"] = True
    # 选最“具体”的维度：命中的词越长越优先（“赛事”胜过“年”）；
    # 已作为过滤条件的维度不再拿来分组，否则会得到只有一行、100% 的空表。
    used = set(filters)
    candidates: list[tuple[int, str]] = []
    for dim, words in _DIM_WORDS.items():
        if dim in used:
            continue
        hits = [w for w in words if w in question]
        if hits:
            candidates.append((max(len(w) for w in hits), dim))
    if candidates:
        candidates.sort(key=lambda x: -x[0])
        group_by = candidates[0][1]
    else:
        group_by = "year"
    return {"filters": filters, "group_by": group_by, "parsed_by": "rule"}


def _st_aggregate(state: dict, ctx: RunContext) -> dict:
    f = stats_svc.Filters(**state.get("filters", {}))
    res = stats_svc.aggregate(ctx.db, f, state.get("group_by", "year"))
    detail = stats_svc.detail_rows(ctx.db, f, limit=300)
    return {"stats": res, "detail": detail}


def _st_format(state: dict, ctx: RunContext) -> dict:
    res = state["stats"]
    items = res["items"]
    t = res["totals"]
    filters = state.get("filters") or {}
    cond = "、".join(res["filters"]) if res["filters"] else "全部数据"
    lines = [
        f"统计口径：{cond}｜分组维度：{res['group_label']}",
        f"共 {t['count']} 个参赛项目，获奖 {t['award_count']} 项，获奖率 {t['award_rate']}%，预算合计 {t['amount']:,.2f} 元。",
        "",
    ]
    if filters.get("awarded_only"):
        lines += [
            "> 注：当前已按「仅获奖项目」过滤，基数本身只含获奖项目，"
            "因此获奖率会显示为 100%，不代表整体获奖水平；如需真实获奖率请去掉该条件。",
            "",
        ]
    if res.get("group_by") in {"award_level", "award_grade"}:
        lines += [
            "> 注：按获奖等级/级别分组时，每一行本身只含获奖项目，行内“获奖率”无参考意义，请以「参赛」列看规模。",
            "",
        ]
    if items:
        lines.append(f"{res['group_label']}　参赛　获奖　获奖率")
        for it in items[:25]:
            lines.append(f"{it['key']}　{it['count']}　{it['award_count']}　{it['award_rate']}%")
        if len(items) > 25:
            lines.append(f"……共 {len(items)} 个分组，完整明细见导出文件")
    else:
        lines.append("没有符合条件的记录。")
    lines += ["", "以上数字均由数据库聚合得出，未经过模型生成。"]
    return {"answer": "\n".join(lines), "data": {"stats": res, "detail": state.get("detail", [])[:300]}}


def build_stats() -> StateGraph:
    g = StateGraph("数据统计")
    g.add_node("parse", _st_parse, "解析自然语言统计条件")
    g.add_node("aggregate", _st_aggregate, "数据库聚合")
    g.add_node("format", _st_format, "输出统计结论")
    g.set_entry_point("parse")
    g.add_edge("parse", "aggregate")
    g.add_edge("aggregate", "format")
    g.set_finish_point("format")
    return g


# ================================================================ 注册
_BUILDERS = {
    "qa": build_qa,
    "recommend": build_recommend,
    "prep": build_prep,
    "review": build_review,
    "budget": build_budget,
    "loan": build_loan,
    "reimburse": build_reimburse,
    "stats": build_stats,
}

WORKFLOWS: dict[str, CompiledGraph] = {}
GRAPHS: dict[str, StateGraph] = {}


def _init() -> None:
    for key, builder in _BUILDERS.items():
        g = builder()
        GRAPHS[key] = g
        WORKFLOWS[key] = g.compile(max_steps=30)


_init()


WORKFLOW_LABELS = {
    "qa": "竞赛知识问答",
    "recommend": "竞赛推荐",
    "prep": "备赛辅助",
    "review": "项目材料评审",
    "budget": "预算申请",
    "loan": "借款辅助",
    "reimburse": "报销辅助",
    "stats": "竞赛数据统计",
}


def run(key: str, payload: dict, db) -> dict:  # noqa: ANN001
    graph = WORKFLOWS.get(key)
    if graph is None:
        raise KeyError(f"未知工作流：{key}")

    import time

    t0 = time.time()
    ctx = RunContext(db=db)
    state: dict = {"input": payload, **payload, "_trace": []}
    out = graph.invoke(state, ctx)

    return {
        "workflow": key,
        "label": WORKFLOW_LABELS.get(key, key),
        "answer": out.get("answer", ""),
        "data": out.get("data") or _extract_data(out),
        "citations": out.get("citations", []),
        "mode": out.get("mode") or out.get("check_mode") or out.get("parsed_by") or "rule",
        "trace": out.get("_trace", []),
        "steps": out.get("_steps", 0),
        "duration_ms": int((time.time() - t0) * 1000),
    }


def _extract_data(out: dict) -> dict:
    keep = (
        "stats", "budget", "loan", "reimburse", "review", "recommendations",
        "student", "competition", "plan_rule", "days", "detail", "history",
    )
    return {k: out[k] for k in keep if k in out and not isinstance(out[k], (bytes,))}


def describe_all() -> list[dict]:
    return [
        {
            "key": key,
            "label": WORKFLOW_LABELS[key],
            "graph": GRAPHS[key].describe(),
            "mermaid": GRAPHS[key].to_mermaid(),
        }
        for key in _BUILDERS
    ]
