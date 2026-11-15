"""导出：Excel 台账/统计表，Word 预算申请、借款单、报销单、分析报告。"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from ..config import settings

# ---------------------------------------------------------------- 工具
def _out(name: str) -> Path:
    settings.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(ch for ch in name if ch not in '\\/:*?"<>|').strip() or "export"
    return settings.OUTPUT_DIR / f"{safe}_{stamp}"


def _set_cn_font(run, size: float = 10.5, bold: bool = False, font: str = "宋体") -> None:
    from docx.oxml.ns import qn
    from docx.shared import Pt

    run.font.name = font
    run.font.size = Pt(size)
    run.bold = bold
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), font)
    rfonts.set(qn("w:ascii"), font)
    rfonts.set(qn("w:hAnsi"), font)


def _doc_title(doc, text: str, size: float = 18) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_cn_font(p.add_run(text), size=size, bold=True, font="黑体")


def _para(doc, text: str, size: float = 10.5, align: str = "left", bold: bool = False, space_after: float = 6):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    p = doc.add_paragraph()
    p.alignment = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER,
                   "right": WD_ALIGN_PARAGRAPH.RIGHT, "justify": WD_ALIGN_PARAGRAPH.JUSTIFY}[align]
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = 1.4
    _set_cn_font(p.add_run(text), size=size, bold=bold)
    return p


def _table(doc, headers: list[str], rows: list[list], widths: list[float] | None = None, size: float = 9.5):
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = table.rows[0].cells
    for i, h in enumerate(headers):
        hdr[i].text = ""
        p = hdr[i].paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _set_cn_font(p.add_run(str(h)), size=size, bold=True, font="黑体")
    for row in rows:
        cells = table.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            p = cells[i].paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER if i > 0 else WD_ALIGN_PARAGRAPH.LEFT
            _set_cn_font(p.add_run("" if v is None else str(v)), size=size)
    if widths:
        from docx.shared import Cm

        for i, w in enumerate(widths):
            for row in table.rows:
                row.cells[i].width = Cm(w)
    return table


# ---------------------------------------------------------------- Excel
def export_table(headers: list[str], rows: list[list], filename: str, sheet: str = "数据", title: str = "") -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = sheet[:31]

    thin = Side(style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="F2F4F7")
    head_font = Font(name="微软雅黑", size=10, bold=True)
    body_font = Font(name="微软雅黑", size=10)

    offset = 0
    if title:
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(1, len(headers)))
        cell = ws.cell(row=1, column=1, value=title)
        cell.font = Font(name="微软雅黑", size=13, bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[1].height = 28
        ws.cell(row=2, column=1, value=f"导出时间：{dt.datetime.now().strftime('%Y-%m-%d %H:%M')}").font = Font(
            name="微软雅黑", size=9, color="888888"
        )
        offset = 3

    header_row = offset + 1
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=header_row, column=i, value=h)
        c.font = head_font
        c.fill = head_fill
        c.border = border
        c.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[header_row].height = 22

    for r, row in enumerate(rows, start=header_row + 1):
        for i, v in enumerate(row, start=1):
            c = ws.cell(row=r, column=i, value=v)
            c.font = body_font
            c.border = border
            c.alignment = Alignment(horizontal="center" if i > 1 else "left", vertical="center", wrap_text=False)

    for i, h in enumerate(headers, start=1):
        width = max(10, min(34, len(str(h)) * 2.4 + 6))
        for row in rows[:200]:
            if i - 1 < len(row):
                width = max(width, min(34, len(str(row[i - 1] or "")) * 1.9 + 4))
        ws.column_dimensions[get_column_letter(i)].width = width

    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    path = _out(filename).with_suffix(".xlsx")
    wb.save(path)
    return path


def export_stats_workbook(result: dict, detail: list[dict] | None = None, filename: str = "竞赛统计") -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    wb = Workbook()
    ws = wb.active
    ws.title = "统计汇总"
    thin = Side(style="thin", color="D9D9D9")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    hf = PatternFill("solid", fgColor="F2F4F7")

    ws.merge_cells("A1:E1")
    ws["A1"] = f"学科竞赛统计表 · 按{result.get('group_label', '')}统计"
    ws["A1"].font = Font(name="微软雅黑", size=14, bold=True)
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 30

    filters = result.get("filters") or []
    ws["A2"] = "统计条件：" + ("、".join(filters) if filters else "全部数据")
    ws["A2"].font = Font(name="微软雅黑", size=9, color="666666")

    headers = [result.get("group_label", "分组"), "参赛项目数", "获奖数", "获奖率(%)", "预算金额(元)"]
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=4, column=i, value=h)
        c.font = Font(name="微软雅黑", size=10, bold=True)
        c.fill = hf
        c.border = border
        c.alignment = Alignment(horizontal="center", vertical="center")

    for r, item in enumerate(result.get("items", []), start=5):
        for i, v in enumerate(
            [item["key"], item["count"], item["award_count"], item["award_rate"], item["amount"]], start=1
        ):
            c = ws.cell(row=r, column=i, value=v)
            c.font = Font(name="微软雅黑", size=10)
            c.border = border
            c.alignment = Alignment(horizontal="center" if i > 1 else "left")

    t = result.get("totals", {})
    total_row = 5 + len(result.get("items", []))
    for i, v in enumerate(["合计", t.get("count"), t.get("award_count"), t.get("award_rate"), t.get("amount")], start=1):
        c = ws.cell(row=total_row, column=i, value=v)
        c.font = Font(name="微软雅黑", size=10, bold=True)
        c.fill = hf
        c.border = border
        c.alignment = Alignment(horizontal="center" if i > 1 else "left")

    for col, w in zip("ABCDE", [26, 14, 12, 12, 16]):
        ws.column_dimensions[col].width = w

    if detail:
        ws2 = wb.create_sheet("明细")
        d_headers = ["年份", "赛事", "级别", "项目名称", "负责人", "专业", "指导教师", "获奖级别", "获奖等级", "状态", "预算(元)"]
        for i, h in enumerate(d_headers, start=1):
            c = ws2.cell(row=1, column=i, value=h)
            c.font = Font(name="微软雅黑", size=10, bold=True)
            c.fill = hf
            c.border = border
            c.alignment = Alignment(horizontal="center", vertical="center")
        for r, d in enumerate(detail, start=2):
            vals = [d.get("year"), d.get("competition"), d.get("level"), d.get("project"), d.get("student"),
                    d.get("major"), d.get("teacher"), d.get("award_grade"), d.get("award_level"), d.get("status"), d.get("budget")]
            for i, v in enumerate(vals, start=1):
                c = ws2.cell(row=r, column=i, value=v)
                c.font = Font(name="微软雅黑", size=9.5)
                c.border = border
                c.alignment = Alignment(horizontal="center" if i != 4 else "left")
        for col, w in zip("ABCDEFGHIJK", [8, 22, 8, 34, 10, 18, 10, 10, 10, 10, 12]):
            ws2.column_dimensions[col].width = w
        ws2.freeze_panes = "A2"

    path = _out(filename).with_suffix(".xlsx")
    wb.save(path)
    return path


# ---------------------------------------------------------------- Word 单据
def _new_doc():
    from docx import Document
    from docx.shared import Cm, Pt

    doc = Document()
    section = doc.sections[0]
    section.left_margin = Cm(2.6)
    section.right_margin = Cm(2.6)
    section.top_margin = Cm(2.2)
    section.bottom_margin = Cm(2.2)
    style = doc.styles["Normal"]
    style.font.name = "宋体"
    style.font.size = Pt(10.5)
    return doc


def export_budget_docx(budget: dict, filename: str = "竞赛经费预算申请表") -> Path:
    doc = _new_doc()
    _doc_title(doc, "学科竞赛经费预算申请表")
    _para(doc, f"申请日期：{dt.date.today().strftime('%Y 年 %m 月 %d 日')}", size=9.5, align="right")

    info = [
        ["竞赛名称", budget.get("competition") or "—", "赛事级别", budget.get("level") or "—"],
        ["参赛队伍", budget.get("team_name") or "—", "参赛人数", f"{budget.get('people')} 人"],
        ["参赛地点", f"{budget.get('scope')}", "赛程天数", f"{budget.get('days')} 天"],
    ]
    t = doc.add_table(rows=0, cols=4)
    t.style = "Table Grid"
    for row in info:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            p = cells[i].paragraphs[0]
            _set_cn_font(p.add_run(str(v)), size=9.5, bold=(i % 2 == 0), font="宋体" if i % 2 else "黑体")

    _para(doc, "一、预算明细", size=11, bold=True, space_after=2)
    headers = ["序号", "支出科目", "规格说明", "单位", "数量", "单价(元)", "金额(元)"]
    rows = []
    for i, it in enumerate(budget.get("items", []), start=1):
        rows.append([i, it["name"], it.get("spec", ""), it.get("unit", ""), it.get("qty", ""),
                     f"{it['price']:.2f}", f"{it['amount']:.2f}"])
    rows.append(["", "合计", "", "", "", "", f"{budget.get('total', 0):.2f}"])
    _table(doc, headers, rows, widths=[1.2, 3.2, 6.0, 1.8, 1.6, 2.4, 2.6], size=9)

    _para(doc, "二、预算说明", size=11, bold=True, space_after=2)
    _para(doc, budget.get("statement", ""), align="justify")

    if budget.get("warnings"):
        _para(doc, "三、系统提示", size=11, bold=True, space_after=2)
        for w in budget["warnings"]:
            _para(doc, f"· [{w.get('level')}] {w.get('item')}：{w.get('problem')}（建议：{w.get('advice')}）", size=9.5)

    _para(doc, "", space_after=10)
    _table(
        doc,
        ["项目负责人", "指导教师", "系（教研室）意见", "学院意见"],
        [["\n\n\n签字：", "\n\n\n签字：", "\n\n\n签字：", "\n\n\n签字："]],
        widths=[3.6, 3.6, 4.6, 4.6],
        size=9,
    )
    path = _out(filename)
    doc.save(path.with_suffix(".docx"))
    return path.with_suffix(".docx")


def export_loan_docx(loan: dict, filename: str = "借款单") -> Path:
    doc = _new_doc()
    _doc_title(doc, "暂 付 款（借 款）凭 证")
    _para(doc, f"编号：{loan.get('loan_no') or '—'}　　　　日期：{dt.date.today().strftime('%Y 年 %m 月 %d 日')}", size=9.5)

    _table(
        doc,
        ["借款单位（项目）", loan.get("team_name") or loan.get("title") or "—", "借款经办人", loan.get("borrower") or "—"],
        [[
            _blank(),
            "",
            _blank(),
            "",
        ]],
        widths=[3.4, 5.4, 3.0, 4.6],
        size=10,
    )

    _para(doc, f"借款金额（大写）：{loan.get('amount_cn', '')}", size=11, bold=True, space_after=2)
    _para(doc, f"借款金额（小写）：￥{loan.get('amount', 0):,.2f} 元", size=11, bold=True)

    _para(doc, "借款用途：", size=10.5, bold=True, space_after=2)
    _para(doc, loan.get("purpose", ""), align="justify")

    if loan.get("items"):
        _para(doc, "费用构成：", size=10.5, bold=True, space_after=2)
        rows = []
        for i, it in enumerate(loan["items"], start=1):
            rows.append([i, it.get("name", ""), it.get("spec", ""), it.get("qty", ""), f"{float(it.get('amount') or 0):.2f}"])
        _table(doc, ["序号", "科目", "说明", "数量", "金额(元)"], rows, widths=[1.2, 3.2, 7.0, 2.0, 3.0], size=9)

    _para(doc, f"收款单位：{loan.get('payee') or '—'}", size=10)
    _para(doc, f"收款账号：{loan.get('bank_account') or '—'}", size=10)
    _para(doc, "附单据：", size=10, bold=True, space_after=2)
    for a in loan.get("attachments", []):
        _para(doc, f"□ {a}", size=9.5, space_after=2)

    if loan.get("warnings"):
        _para(doc, "系统校验提示：", size=10, bold=True, space_after=2)
        for w in loan["warnings"]:
            _para(doc, f"· {w.get('problem')}（{w.get('advice')}）", size=9.5)

    _para(doc, "", space_after=8)
    _table(
        doc,
        ["经办人", "项目负责人", "学院负责人", "财务审核"],
        [[_blank(), _blank(), _blank(), _blank()]],
        widths=[3.6, 4.0, 4.2, 4.6],
        size=9,
    )
    path = _out(filename)
    doc.save(path.with_suffix(".docx"))
    return path.with_suffix(".docx")


def export_reimburse_docx(reimb: dict, filename: str = "报销单") -> Path:
    doc = _new_doc()
    _doc_title(doc, "学科竞赛经费报 销 单")
    _para(doc, f"编号：{reimb.get('reimb_no') or '—'}　　　　填报日期：{dt.date.today().strftime('%Y 年 %m 月 %d 日')}", size=9.5)

    rows = []
    for i, it in enumerate(reimb.get("items", []), start=1):
        rows.append([
            i, it.get("name", ""), it.get("invoice_no", "") or "—", it.get("invoice_date", "") or "—",
            it.get("invoice_type", "") or "—", f"{float(it.get('amount') or 0):.2f}",
        ])
    rows.append(["", "合计", "", "", "", f"{reimb.get('total', 0):.2f}"])
    _table(doc, ["序号", "支出事项", "发票号", "开票日期", "票据类型", "金额(元)"], rows,
           widths=[1.2, 4.4, 4.4, 2.8, 2.6, 2.6], size=9)

    _para(doc, f"实报金额（大写）：{reimb.get('total_cn', '')}", size=11, bold=True)
    _para(doc, f"批复预算：￥{float(reimb.get('approved') or 0):,.2f} 元　　实际支出：￥{float(reimb.get('total') or 0):,.2f} 元"
              + (f"　　超支：￥{float(reimb.get('over_budget') or 0):,.2f} 元" if reimb.get("over_budget") else ""), size=10)

    _para(doc, "系统审核结论：", size=10.5, bold=True, space_after=2)
    _para(doc, reimb.get("conclusion", ""), align="justify")

    if reimb.get("issues"):
        _para(doc, "问题明细：", size=10, bold=True, space_after=2)
        for it in reimb["issues"]:
            _para(doc, f"· [{it.get('level')}] {it.get('item')}：{it.get('problem')} → {it.get('fix')}", size=9.5, space_after=2)

    if reimb.get("missing_attachments"):
        _para(doc, "缺失附件：" + "、".join(reimb["missing_attachments"]), size=10)

    _para(doc, "", space_after=8)
    _table(
        doc,
        ["报销人", "指导教师", "学院审核", "财务复核"],
        [[_blank(), _blank(), _blank(), _blank()]],
        widths=[3.6, 4.0, 4.2, 4.6],
        size=9,
    )
    path = _out(filename)
    doc.save(path.with_suffix(".docx"))
    return path.with_suffix(".docx")


def _blank() -> str:
    return ""


def export_report_docx(sections: list[dict], filename: str = "竞赛分析报告") -> Path:
    """sections: [{"heading": str, "text": str, "table": {"headers": [], "rows": []} | None}]"""
    doc = _new_doc()
    _doc_title(doc, "学科竞赛情况分析报告")
    _para(doc, f"生成时间：{dt.datetime.now().strftime('%Y-%m-%d %H:%M')}", size=9.5, align="right")
    for sec in sections:
        _para(doc, sec.get("heading", ""), size=12, bold=True, space_after=4)
        if sec.get("text"):
            _para(doc, sec["text"], align="justify")
        tbl = sec.get("table")
        if tbl:
            _table(doc, tbl.get("headers", []), tbl.get("rows", []), size=9)
        _para(doc, "", space_after=4)
    path = _out(filename)
    doc.save(path.with_suffix(".docx"))
    return path.with_suffix(".docx")
