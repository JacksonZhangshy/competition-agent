"""离线自测：不依赖 FastAPI / SQLAlchemy，仅验证核心算法与工作流引擎。

    python scripts/selftest.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL = 0, 0
FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [ok]   {name}")
    else:
        FAIL += 1
        FAILED.append(name)
        print(f"  [FAIL] {name}  {detail}")


def section(title: str) -> None:
    print(f"\n── {title}")


# ================================================================ 向量与分词
def test_embedding() -> None:
    from backend.llm import cosine, local_embed, parse_json_loose, tokenize

    section("向量与文本工具")
    toks = tokenize("国创赛报名截止时间")
    check("中文分词包含二元组", "报名" in toks and "截止" in toks, str(toks[:10]))
    check("英文数字成词", "abc123" in tokenize("abc123 测试"))

    v1 = local_embed("住宿费标准 380 元每人每天", 256)
    v2 = local_embed("住宿标准是每天 380 元", 256)
    v3 = local_embed("ACM 区域赛允许携带纸质资料", 256)
    check("向量维度正确", len(v1) == 256)
    check("向量已归一化", abs(sum(x * x for x in v1) - 1.0) < 1e-6)
    check("近义文本相似度高于无关文本", cosine(v1, v2) > cosine(v1, v3), f"{cosine(v1, v2):.3f} vs {cosine(v1, v3):.3f}")
    check("相同文本相似度为 1", abs(cosine(v1, v1) - 1.0) < 1e-9)

    check("解析纯 JSON", parse_json_loose('{"a": 1}') == {"a": 1})
    check("解析带围栏 JSON", parse_json_loose('```json\n{"a": 2}\n```') == {"a": 2})
    check("解析夹带文字的 JSON", parse_json_loose('好的，结果如下：{"a": 3} 以上') == {"a": 3})
    check("非法 JSON 返回 None", parse_json_loose("not json") is None)


# ================================================================ 切块
def test_chunker() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("_chunker", ROOT / "backend" / "rag" / "chunker.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    chunk_blocks = mod.chunk_blocks

    section("文本切块")
    blocks = [
        {"text": "第一章 总则", "page": None, "heading": "标题"},
        {"text": "第一条 " + "本办法适用于学院全体本科生参加学科竞赛的管理。" * 2, "page": None, "heading": ""},
        {"text": "第二条 " + "竞赛经费实行总额控制。" * 40, "page": None, "heading": ""},
    ]
    chunks = chunk_blocks(blocks, max_chars=300, overlap=50)
    check("切块数量大于 1", len(chunks) > 1, f"got {len(chunks)}")
    check("块内保留标题上下文", any("第一章" in c["heading"] or "总则" in c["heading"] for c in chunks))
    check("没有空块", all(c["content"].strip() for c in chunks))

    over = [c for c in chunks if len(c["content"]) > 300 + 60]
    check("超长块被拆分", not over, f"{len(over)} 块超长")

    short = chunk_blocks([{"text": "很短", "page": None, "heading": ""}], max_chars=300, overlap=0)
    check("极短文本保留为单块", len(short) == 1)


# ================================================================ 工作流引擎
def test_graph() -> None:
    from backend.agent.graph import RunContext, StateGraph

    section("工作流引擎")

    # 线性流
    g = StateGraph("线性")
    g.add_node("a", lambda s, c: {"x": s.get("x", 0) + 1}, "第一步")
    g.add_node("b", lambda s, c: {"x": s["x"] * 10}, "第二步")
    g.set_entry_point("a")
    g.add_edge("a", "b")
    g.set_finish_point("b")
    out = g.compile().invoke({"x": 1})
    check("线性流程正确传递状态", out["x"] == 20, str(out.get("x")))
    check("轨迹记录两个节点", len(out["_trace"]) == 2, str(len(out["_trace"])))
    check("轨迹含耗时字段", all("duration_ms" in t for t in out["_trace"]))

    # 条件分支
    h = StateGraph("分支")
    h.add_node("start", lambda s, c: {"n": s.get("n", 0)}, "入口")
    h.add_node("big", lambda s, c: {"result": "big"}, "大")
    h.add_node("small", lambda s, c: {"result": "small"}, "小")
    h.set_entry_point("start")
    h.add_conditional_edges("start", lambda s: "gt" if s["n"] > 5 else "le", {"gt": "big", "le": "small"})
    h.set_finish_point("big")
    compiled = h.compile()
    check("条件分支走 big", compiled.invoke({"n": 9})["result"] == "big")
    check("条件分支走 small", compiled.invoke({"n": 1})["result"] == "small")

    # 错误传播
    k = StateGraph("异常")
    k.add_node("boom", lambda s, c: 1 / 0, "抛错")
    k.set_entry_point("boom")
    try:
        k.compile().invoke({})
        check("节点异常被抛出", False)
    except ZeroDivisionError:
        check("节点异常被抛出", True)

    # 死循环保护
    m = StateGraph("循环")
    m.add_node("loop", lambda s, c: {"i": s.get("i", 0) + 1}, "自循环")
    m.set_entry_point("loop")
    m.add_edge("loop", "loop")
    out2 = m.compile(max_steps=5).invoke({})
    check("最大步数保护生效", out2["_steps"] == 5, str(out2.get("_steps")))

    # 描述与图
    desc = h.describe()
    check("describe 输出节点列表", len(desc["nodes"]) == 3)
    check("mermaid 含条件标签", "|gt|" in h.to_mermaid(), h.to_mermaid())


# ================================================================ 抽取式回答
def test_extractive() -> None:
    section("抽取式回答（无大模型降级）")

    class FakeChunk:
        def __init__(self, content):
            self.content = content
            self.doc_title = "测试文档"
            self.page = 1
            self.heading = "第一章"
            self.seq = 0
            self.id = 1
            self.doc_id = 1
            self.filename = "t.docx"
            self.category = "政策"
            self.year = 2026

    class FakeHit:
        def __init__(self, content, score):
            self.chunk = FakeChunk(content)
            self.score = score
            self.bm25 = score
            self.vector = score

        def citation(self):
            return {"title": "测试文档", "snippet": self.chunk.content[:50]}

    from backend.agent.compose import extractive_answer

    hits = [
        FakeHit("省外住宿费标准为每人每天 380 元。伙食补助每人每天 100 元。报销须在赛后 30 日内完成。", 0.8),
        FakeHit("校级赛事不收取报名费。省赛报名费由学院统一承担。", 0.4),
    ]
    ans = extractive_answer("省外住宿费标准是多少", hits)
    check("回答含结论段", "结论：" in ans)
    check("回答含引用编号", "[1]" in ans)
    check("回答命中关键数字", "380" in ans, ans[:120])
    check("空结果返回友好提示", extractive_answer("x", []) == "")


# ================================================================ 金额大写
def test_money() -> None:
    section("金额大写转换")
    src = (ROOT / "backend" / "services" / "budget.py").read_text(encoding="utf-8")
    start = src.index("_DIGITS = ")
    snippet = src[start:]
    ns: dict = {}
    exec(compile(snippet, "budget_money", "exec"), ns)  # noqa: S102
    f = ns["money_to_chinese"]

    cases = [
        (0, "人民币零元整"),
        (1, "人民币壹元整"),
        (10, "人民币壹拾元整"),
        (100, "人民币壹佰元整"),
        (1005, "人民币壹仟零伍元整"),
        (3880, "人民币叁仟捌佰捌拾元整"),
        (10000, "人民币壹万元整"),
        (12345.67, "人民币壹万贰仟叁佰肆拾伍元陆角柒分"),
        (100.5, "人民币壹佰元伍角"),
        (0.05, "人民币零元零伍分"),
        (1000000, "人民币壹佰万元整"),
    ]
    for amount, expect in cases:
        got = f(amount)
        check(f"{amount} → {expect}", got == expect, f"实际 {got}")


# ================================================================ 排期与查询解析
def test_plan_rules() -> None:
    """回归：曾出现「2026-11-15 → 2026-06-09 共 -158 天」的负天数排期。"""
    try:
        import datetime as dt

        from backend.agent.workflows import _pick_deadline, _rule_plan, _split_days
    except ModuleNotFoundError as e:  # 纯离线环境可能没有 sqlalchemy
        print(f"\n── 排期规则\n  [skip] 依赖缺失（{e.name}），跳过")
        return

    section("排期规则")
    today = dt.date.today()

    spans = _split_days(27, [0.15, 0.25, 0.35, 0.15, 0.10])
    check("阶段天数之和等于总天数", sum(spans) == 27, str(spans))
    check("每阶段至少 1 天", min(spans) >= 1, str(spans))
    tight = _split_days(3, [0.15, 0.25, 0.35, 0.15, 0.10])
    check("天数不足时每阶段仍至少 1 天", min(tight) >= 1 and sum(tight) == 5, str(tight))

    future = (today + dt.timedelta(days=30)).isoformat()
    past = (today - dt.timedelta(days=30)).isoformat()
    picked = _pick_deadline([{"signup_end": past, "year": 2025}, {"signup_end": future, "year": 2026}], today)
    check("选出的是未来节点", picked["date"].isoformat() == future and not picked["expired"], str(picked))
    expired = _pick_deadline([{"signup_end": past, "year": 2025}], today)
    check("全部过期时标记 expired", expired["expired"] is True and expired["date"] is not None, str(expired))
    check("无赛季时返回空", _pick_deadline([], today)["date"] is None)

    plan = _rule_plan("测试赛事", {}, 27, None)
    check("排期天数全为正", all(p["days"] >= 1 for p in plan["schedule"]), str([p["days"] for p in plan["schedule"]]))
    starts = [dt.date.fromisoformat(p["start"]) for p in plan["schedule"]]
    check("排期时间单调递增", starts == sorted(starts), str(starts[:3]))
    check("排期累计天数与总天数一致", sum(p["days"] for p in plan["schedule"]) == 27)

    late = _rule_plan("测试赛事", {}, 40, today + dt.timedelta(days=12))
    check("截止日前的排期不越界",
          max(dt.date.fromisoformat(p["end"]) for p in late["schedule"]) <= today + dt.timedelta(days=12))


def test_query_parse() -> None:
    """回归：曾把「参赛项目」误判成赛事维度、把「仅获奖」当成默认口径。"""
    try:
        from backend.agent.workflows import _DIM_WORDS
    except ModuleNotFoundError as e:
        print(f"\n── 统计维度词表\n  [skip] 依赖缺失（{e.name}），跳过")
        return

    section("统计维度词表")

    def pick(q: str) -> str:
        used: set = set()
        cands = []
        for dim, words in _DIM_WORDS.items():
            if dim in used:
                continue
            hits = [w for w in words if w in q]
            if hits:
                cands.append((max(len(w) for w in hits), dim))
        cands.sort(key=lambda x: -x[0])
        return cands[0][1] if cands else "year"

    check("「各学院」→ 学院", pick("各学院获奖数量对比") == "college")
    check("「各专业」→ 专业", pick("各专业参赛数量") == "major")
    check("「2025年各赛事」→ 赛事（不被“年”抢走）", pick("2025年各赛事获奖情况") == "competition")
    check("「参赛项目」不误判为赛事", pick("有多少个参赛项目") == "year", pick("有多少个参赛项目"))
    check("「指导教师」→ 教师", pick("各指导教师的获奖数量") == "teacher")


# ================================================================ 主流程
def main() -> int:
    print("=" * 64)
    print("  竞赛辅助服务智能体 · 离线自测")
    print("=" * 64)

    for fn in (
        test_embedding,
        test_chunker,
        test_graph,
        test_extractive,
        test_money,
        test_plan_rules,
        test_query_parse,
    ):
        try:
            fn()
        except Exception as e:
            global FAIL
            FAIL += 1
            FAILED.append(fn.__name__)
            import traceback

            print(f"  [FAIL] {fn.__name__} 抛异常: {e}")
            traceback.print_exc()

    print("\n" + "=" * 64)
    total = PASS + FAIL
    print(f"  通过 {PASS}/{total}" + (f"，失败 {FAIL}" if FAIL else "，全部通过"))
    if FAILED:
        print("  失败项：" + "、".join(FAILED))
    print("=" * 64)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
