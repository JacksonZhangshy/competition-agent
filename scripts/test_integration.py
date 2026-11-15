"""集成测试：连数据库，跑通 8 条工作流与全部导出，验证交付验收项。

    python scripts/test_integration.py

与 selftest.py 的区别：selftest 只测不依赖数据库的纯算法，
本脚本验证“真实数据 + 完整链路”，是测试报告的依据。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL = 0, 0
FAILED: list[str] = []
USED_MS: list[tuple[str, int]] = []


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


def run(wf: str, payload: dict, db):  # noqa: ANN001, ANN201
    from backend.agent import workflows

    res = workflows.run(wf, payload, db)
    USED_MS.append((wf, res["duration_ms"]))
    return res


def main() -> int:
    from backend.agent import workflows
    from backend.database import db_session
    from backend.models import Competition, Student, Team
    from backend.services import budget as budget_svc
    from backend.services import export as export_svc
    from backend.services import stats as stats_svc

    print("=" * 68)
    print("  竞赛辅助服务智能体 · 集成测试")
    print("=" * 68)

    with db_session() as db:
        stu = db.query(Student).filter(Student.major.like("%软件工程%")).first()
        team = db.query(Team).first()
        comp = db.query(Competition).filter(Competition.name.like("%创新%")).first()

        # ---------------------------------------------------- 1 知识问答
        section("1 知识问答（RAG + 拒答）")
        answerable = [
            "学科竞赛的报名时间一般是什么时候？",
            "住宿费的开支标准是多少？",
            "报销需要提交哪些材料？",
        ]
        for q in answerable:
            r = run("qa", {"question": q}, db)
            check(f"可答问题有答案：{q[:12]}…",
                  len(r["answer"]) > 30 and r["mode"] != "no_hit",
                  f"mode={r['mode']} len={len(r['answer'])}")
            check(f"可答问题带引用：{q[:12]}…", len(r["citations"]) > 0, f"{len(r['citations'])} 条")

        unanswerable = ["某某不存在的赛事什么时候报名？", "学院院长的手机号是多少？", "如何申请发明专利？"]
        for q in unanswerable:
            r = run("qa", {"question": q}, db)
            check(f"无据问题如实拒答：{q[:12]}…", r["mode"] == "no_hit", f"mode={r['mode']}")

        # ---------------------------------------------------- 2 竞赛推荐
        section("2 竞赛推荐")
        r = run("recommend", {"sno": stu.sno, "interests": "算法,大模型"}, db)
        recs = r["data"]["recommendations"]
        check("返回候选清单", len(recs) >= 3, f"{len(recs)} 条")
        scores = [x["score"] for x in recs]
        check("按匹配度降序", scores == sorted(scores, reverse=True), str(scores[:5]))
        check("每条都有分档与理由", all(x["tier"] and x["reasons"] for x in recs))
        check("理由可追溯（含专业或年级）",
              all(any(("专业" in s or "年级" in s) for s in x["reasons"]) for x in recs))

        # ---------------------------------------------------- 3 备赛
        section("3 备赛辅助")
        r = run("prep", {"competition": comp.name}, db)
        plan = r["data"]["plan"]
        sched = plan["schedule"]
        check("生成 5 个阶段", len(sched) == 5, str(len(sched)))
        check("阶段天数为正", all(p["days"] >= 1 for p in sched), str([p["days"] for p in sched]))
        check("阶段天数合计等于总天数", sum(p["days"] for p in sched) == plan["total_days"],
              f"{sum(p['days'] for p in sched)} vs {plan['total_days']}")
        check("阶段日期不倒挂", all(p["end"] >= p["start"] for p in sched))
        check("含材料清单", len(plan["materials"]) >= 3, str(plan["materials"]))

        # 已截止赛事的兜底（不能出现负天数）
        old = db.query(Competition).filter(Competition.code == "LADDER").first() or comp
        r2 = run("prep", {"competition": old.name}, db)
        check("已截止赛事不产生负天数",
              all(p["days"] >= 1 for p in r2["data"]["plan"]["schedule"]),
              str([p["days"] for p in r2["data"]["plan"]["schedule"]]))

        # ---------------------------------------------------- 4 材料评审
        section("4 项目材料评审")
        weak = "本项目具有重要意义，采用先进技术，效果良好。" * 3
        r = run("review", {"content": weak, "competition": comp.name}, db)
        rev = r["data"]["review"]
        check("得分在 0-100", 0 <= rev["score"] <= 100, str(rev["score"]))
        check("空泛材料能判出问题", len(rev["issues"]) >= 3, f"{len(rev['issues'])} 项")
        check("给出答辩预判问题", len(rev["defense_questions"]) >= 5)

        good = (
            "一、项目背景与意义。当前高校竞赛材料整理依赖人工，平均每份耗时 40 分钟。\n"
            "二、创新点。提出基于规则与大模型融合的评审方法，相比人工评审准确率提升 18%。\n"
            "三、技术路线。采用 FastAPI + Vue 前后端分离，检索层使用 BM25 与向量混合召回。\n"
            "四、可行性与进度。团队 5 人，已完成原型开发，11 月完成试点，12 月提交。\n"
            "五、预期成果。形成软件 1 套、论文 1 篇，覆盖 200 名学生使用。\n"
        ) * 2
        r = run("review", {"content": good, "competition": comp.name}, db)
        check("规范材料得分更高", r["data"]["review"]["score"] > rev["score"],
              f"{r['data']['review']['score']} vs {rev['score']}")

        # ---------------------------------------------------- 5 预算
        section("5 预算申请")
        r = run("budget", {
            "competition": comp.name, "level": "国家级", "team_size": 5,
            "location": "省外", "days": 3, "sno": stu.sno,
        }, db)
        b = r["data"]["budget"]
        check("人数按入参生效", b["people"] == 5, str(b["people"]))
        check("地点按入参生效", b["scope"] == "省外", b["scope"])
        check("总额等于明细之和",
              abs(b["total"] - sum(i["amount"] for i in b["items"])) < 0.01,
              f"{b['total']} vs {sum(i['amount'] for i in b['items'])}")
        names = [i["name"] for i in b["items"]]
        check("预算说明与明细科目一致",
              all(n in b["statement"] for n in names), f"{names}")
        check("说明中含总额数字", f"{b['total']:.2f}" in b["statement"])
        check("省外包含交通与住宿", "交通费" in names and "住宿费" in names, str(names))

        # ---------------------------------------------------- 6 借款
        section("6 借款辅助")
        r = run("loan", {"amount": 9550, "purpose": "参赛差旅", "sno": stu.sno}, db)
        loan = r["data"]["loan"]
        check("金额大写已生成", loan["amount_cn"].startswith("人民币"), loan["amount_cn"])
        check("经办人自动带出", bool(loan["borrower"]), loan["borrower"])
        check("金额大写与金额对应", "玖仟伍佰伍拾" in loan["amount_cn"], loan["amount_cn"])

        # ---------------------------------------------------- 7 报销
        section("7 报销辅助")
        bad_items = [{"item": "交通费", "amount": 1800, "invoice": "有"}]
        r = run("reimburse", {"items": bad_items, "sno": stu.sno}, db)
        check("缺发票号判为高风险", not r["data"]["reimburse"]["pass"])
        check("指出缺发票号",
              any("发票号" in i["problem"] for i in r["data"]["reimburse"]["issues"]))

        ok_items = [
            {"item": "交通费", "amount": 1800, "invoice_no": "02812345", "invoice_date": "2026-11-10"},
            {"item": "住宿费", "amount": 760, "invoice_no": "02812346", "invoice_date": "2026-11-11"},
        ]
        r = run("reimburse", {
            "items": ok_items, "budget_amount": 9550, "sno": stu.sno,
            "attachments": ["竞赛通知", "参赛审批表", "发票原件", "行程单或签到表"],
        }, db)
        rv = r["data"]["reimburse"]
        check("材料齐全时通过", rv["pass"] is True, rv["conclusion"])
        check("未超预算", rv["over_budget"] == 0, str(rv["over_budget"]))

        # ---------------------------------------------------- 8 统计
        section("8 数据统计")
        r = run("stats", {"question": "各学院获奖数量对比"}, db)
        st = r["data"]["stats"]
        check("维度识别为学院", st["group_by"] == "college", st["group_by"])
        check("分组数大于 1", len(st["items"]) > 1, str(len(st["items"])))
        check("总项目数等于各分组之和",
              st["totals"]["count"] == sum(i["count"] for i in st["items"]))
        check("获奖数等于各分组之和",
              st["totals"]["award_count"] == sum(i["award_count"] for i in st["items"]))
        rate = round(st["totals"]["award_count"] / st["totals"]["count"] * 100, 1)
        check("获奖率计算正确", abs(st["totals"]["award_rate"] - rate) < 0.11,
              f"{st['totals']['award_rate']} vs {rate}")
        check("获奖率小于 100%（未误过滤）", st["totals"]["award_rate"] < 99,
              str(st["totals"]["award_rate"]))

        r = run("stats", {"question": "2025年各赛事获奖情况"}, db)
        check("年限与维度组合正确",
              r["data"]["stats"]["group_by"] == "competition" and "2025" in " ".join(r["data"]["stats"]["filters"]),
              f"{r['data']['stats']['group_by']} {r['data']['stats']['filters']}")

        # 直接调用统计服务，验证与工作流一致
        f = stats_svc.Filters(year=2025)
        agg = stats_svc.aggregate(db, f, "competition")
        check("服务层聚合可用", agg["totals"]["count"] > 0, str(agg["totals"]))

        # ---------------------------------------------------- 9 工作流元信息
        section("9 工作流元信息")
        desc = workflows.describe_all()
        check("共 8 条工作流", len(desc) == 8, str(len(desc)))
        check("每条都有 mermaid 图", all(d["mermaid"].startswith(("flowchart", "graph")) for d in desc))
        check("mermaid 标出条件分支", all("-->" in d["mermaid"] for d in desc))
        check("每条都有节点说明", all(len(d["graph"]["nodes"]) >= 2 for d in desc))

        # ---------------------------------------------------- 10 导出
        section("10 导出（Excel / Word）")
        p = export_svc.export_table(["学号", "姓名"], [["20230101", "张三"]], "集成测试导出")
        check("表格导出为 xlsx", p.exists() and p.suffix == ".xlsx", str(p))
        check("xlsx 非空", p.stat().st_size > 2000, f"{p.stat().st_size} B")

        p = export_svc.export_stats_workbook(agg)
        check("统计工作簿导出", p.exists() and p.suffix == ".xlsx", str(p))

        p = export_svc.export_budget_docx(b)
        check("预算单导出为 docx", p.exists() and p.suffix == ".docx", str(p))
        check("docx 非空", p.stat().st_size > 3000, f"{p.stat().st_size} B")

        p = export_svc.export_loan_docx(loan)
        check("借款单导出", p.exists() and p.suffix == ".docx", str(p))

        p = export_svc.export_reimburse_docx(rv)
        check("报销单导出", p.exists() and p.suffix == ".docx", str(p))

        p = export_svc.export_report_docx([{"title": "统计概览", "text": r["answer"]}])
        check("分析报告导出", p.exists() and p.suffix == ".docx", str(p))

        # ---------------------------------------------------- 11 经费规则
        section("11 经费规则与校验")
        rules = budget_svc.get_rules(db)
        check("开支标准可读", "standards" in rules and "住宿费" in rules["standards"])
        over = budget_svc.check_budget_rules(
            rules, [{"name": "住宿费", "amount": 99999, "qty": 1, "price": 99999}], 99999
        )
        check("超标能触发预警", len(over) > 0, str(over))
        check("金额大写边界", budget_svc.money_to_chinese(0) == "人民币零元整")

    print("\n" + "=" * 68)
    total = PASS + FAIL
    print(f"  通过 {PASS}/{total}" + (f"，失败 {FAIL}" if FAIL else "，全部通过"))
    if USED_MS:
        avg = sum(ms for _, ms in USED_MS) / len(USED_MS)
        slow = sorted(USED_MS, key=lambda x: -x[1])[:3]
        print(f"  工作流调用 {len(USED_MS)} 次，平均 {avg:.0f} ms")
        print("  最慢三条：" + "、".join(f"{k} {ms}ms" for k, ms in slow))
    if FAILED:
        print("  失败项：" + "、".join(FAILED))
    print("=" * 68)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
