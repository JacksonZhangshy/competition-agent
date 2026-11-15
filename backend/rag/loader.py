"""多格式文档解析：PDF / Word / Excel / TXT / Markdown / CSV。

统一输出结构：
    [{"text": str, "page": int | None, "heading": str}]
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path

SUPPORTED = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".csv", ".txt", ".md", ".markdown"}


def _clean(text: str) -> str:
    text = text.replace("\u3000", " ").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_pdf(path: Path) -> list[dict]:
    try:
        from pypdf import PdfReader
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("缺少 pypdf，请执行 pip install pypdf") from e

    reader = PdfReader(str(path))
    blocks: list[dict] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            txt = page.extract_text() or ""
        except Exception:
            txt = ""
        txt = _clean(txt)
        if txt:
            blocks.append({"text": txt, "page": i, "heading": ""})
    return blocks


def load_docx(path: Path) -> list[dict]:
    try:
        import docx  # python-docx
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("缺少 python-docx，请执行 pip install python-docx") from e

    document = docx.Document(str(path))
    blocks: list[dict] = []
    current_heading = ""
    buf: list[str] = []

    def flush() -> None:
        if buf:
            text = _clean("\n".join(buf))
            if text:
                blocks.append({"text": text, "page": None, "heading": current_heading})
            buf.clear()

    for para in document.paragraphs:
        text = (para.text or "").strip()
        if not text:
            continue
        style = (para.style.name or "").lower() if para.style is not None else ""
        if "heading" in style or "标题" in style:
            flush()
            current_heading = text
            blocks.append({"text": text, "page": None, "heading": "标题"})
        else:
            buf.append(text)
    flush()

    # 表格转成结构化文本，保留表头语义
    for t_idx, table in enumerate(document.tables, start=1):
        rows: list[list[str]] = []
        for row in table.rows:
            cells = [(c.text or "").strip().replace("\n", " ") for c in row.cells]
            if any(cells):
                rows.append(cells)
        if len(rows) >= 1:
            header = rows[0]
            lines = [f"表格{t_idx}："]
            for r in rows[1:] if len(rows) > 1 else rows:
                parts = []
                for h, v in zip(header, r):
                    if v:
                        parts.append(f"{h}：{v}")
                if parts:
                    lines.append("；".join(parts))
            if len(lines) > 1:
                blocks.append({"text": _clean("\n".join(lines)), "page": None, "heading": "表格"})
    return blocks


def load_xlsx(path: Path) -> list[dict]:
    try:
        from openpyxl import load_workbook
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("缺少 openpyxl，请执行 pip install openpyxl") from e

    wb = load_workbook(str(path), data_only=True, read_only=True)
    blocks: list[dict] = []
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        header = [str(c).strip() if c is not None else f"列{i + 1}" for i, c in enumerate(rows[0])]
        lines = [f"工作表「{ws.title}」共 {len(rows) - 1} 条记录。"]
        for row in rows[1:]:
            parts = []
            for h, v in zip(header, row):
                if v is None or str(v).strip() == "":
                    continue
                parts.append(f"{h}={v}")
            if parts:
                lines.append("；".join(parts))
        blocks.append({"text": _clean("\n".join(lines)), "page": None, "heading": ws.title})
    wb.close()
    return blocks


def load_csv(path: Path) -> list[dict]:
    raw = None
    for enc in ("utf-8-sig", "gbk", "utf-16"):
        try:
            raw = path.read_text(encoding=enc)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    if raw is None:
        raw = path.read_text(encoding="utf-8", errors="ignore")

    reader = csv.reader(io.StringIO(raw))
    rows = [r for r in reader if any((c or "").strip() for c in r)]
    if not rows:
        return []
    header = [h.strip() or f"列{i + 1}" for i, h in enumerate(rows[0])]
    lines = [f"共 {len(rows) - 1} 条记录。"]
    for row in rows[1:]:
        parts = [f"{h}={v.strip()}" for h, v in zip(header, row) if (v or "").strip()]
        if parts:
            lines.append("；".join(parts))
    return [{"text": _clean("\n".join(lines)), "page": None, "heading": path.stem}]


def load_txt(path: Path) -> list[dict]:
    text = ""
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            text = path.read_text(encoding=enc)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    if not text:
        text = path.read_text(encoding="utf-8", errors="ignore")

    blocks: list[dict] = []
    current_heading = ""
    buf: list[str] = []

    def flush() -> None:
        if buf:
            t = _clean("\n".join(buf))
            if t:
                blocks.append({"text": t, "page": None, "heading": current_heading})
            buf.clear()

    for line in text.splitlines():
        stripped = line.strip()
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            flush()
            current_heading = m.group(2).strip()
            blocks.append({"text": current_heading, "page": None, "heading": "标题"})
        elif re.match(r"^第[一二三四五六七八九十百]+[章条节]", stripped) or re.match(
            r"^[一二三四五六七八九十]+、", stripped
        ):
            flush()
            current_heading = stripped
            buf.append(stripped)
        else:
            buf.append(line)
    flush()
    return blocks


def load_any(path: Path) -> list[dict]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return load_pdf(path)
    if suffix in {".docx", ".doc"}:
        if suffix == ".doc":
            raise RuntimeError("不支持旧版 .doc，请另存为 .docx 后导入")
        return load_docx(path)
    if suffix in {".xlsx", ".xls"}:
        if suffix == ".xls":
            raise RuntimeError("不支持旧版 .xls，请另存为 .xlsx 后导入")
        return load_xlsx(path)
    if suffix == ".csv":
        return load_csv(path)
    if suffix in {".txt", ".md", ".markdown"}:
        return load_txt(path)
    raise RuntimeError(f"不支持的文件类型：{suffix}")


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED


def guess_title(path: Path, first_block: str = "") -> str:
    """文档标题：优先取首个标题块，其次用文件名。"""
    name = path.stem
    m = re.sub(r"^[\d\.\-\s_]+", "", name).strip()
    return m or name


def extract_docx_text_bytes(data: bytes) -> str:
    """直接从字节流读 docx（用于在线提交的材料评审）。"""
    import docx

    doc = docx.Document(io.BytesIO(data))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    return _clean("\n".join(parts))


def is_zip(path: Path) -> bool:
    try:
        return zipfile.is_zipfile(path)
    except OSError:
        return False
