"""测试用文档样本生成器。

不依赖任何外部素材，现场造出 txt / docx / xlsx / pptx / rtf / pdf，
这样内容提取的测试可以完全离线、可重复地跑。
"""

from __future__ import annotations

import zipfile
from pathlib import Path

P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
X_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

PDF_ASCII_TEXT = "Project Acceptance Report 2026"


def make_txt(path: Path, text: str, encoding: str = "utf-8") -> Path:
    Path(path).write_bytes(text.encode(encoding))
    return Path(path)


def make_docx(path: Path, paragraphs: list[str]) -> Path:
    body = "".join(
        f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W_NS}"><w:body>{body}</w:body></w:document>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", xml)
    return Path(path)


def make_xlsx(path: Path, cells: list[str]) -> Path:
    items = "".join(f"<si><t>{c}</t></si>" for c in cells)
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<sst xmlns="{X_NS}" count="{len(cells)}" uniqueCount="{len(cells)}">'
        f"{items}</sst>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/sharedStrings.xml", xml)
    return Path(path)


def make_pptx(path: Path, lines: list[str]) -> Path:
    body = "".join(f"<a:p><a:r><a:t>{t}</a:t></a:r></a:p>" for t in lines)
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<p:sld xmlns:p="{P_NS}" xmlns:a="{A_NS}">'
        f"<p:cSld><p:spTree>{body}</p:spTree></p:cSld></p:sld>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("ppt/slides/slide1.xml", xml)
    return Path(path)


def make_rtf(path: Path, ascii_text: str = "MemoDraft") -> Path:
    """同时包含 \\uNNNN（Unicode 转义）和 \\'xx（GBK 字节转义）两种写法。

    ascii_text 特意取一个别的样本里不会出现的词，避免搜索测试互相干扰。
    """
    unicode_part = "".join(f"\\u{ord(c)}?" for c in "项目验收")
    gbk_part = "".join(f"\\'{b:02x}" for b in "报告".encode("gb18030"))
    rtf = (
        r"{\rtf1\ansi\ansicpg936\deff0"
        r"{\fonttbl{\f0\fnil\fcharset134 SimSun;}}"
        rf"\viewkind4\uc1\pard\f0\fs21 {ascii_text}\par"
        rf"{unicode_part}\par"
        rf"{gbk_part}\par}}"
    )
    Path(path).write_bytes(rtf.encode("latin-1"))
    return Path(path)


def make_pdf(path: Path, text: str = PDF_ASCII_TEXT) -> Path:
    """手搓一个最小但结构合法的 PDF（标准字体，无需嵌入）。"""
    content = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n"
        + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    buf = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(buf))
        buf += f"{i} 0 obj\n".encode("latin-1") + body + b"\nendobj\n"
    xref_pos = len(buf)
    buf += f"xref\n0 {len(objects) + 1}\n".encode("latin-1")
    buf += b"0000000000 65535 f \n"
    for off in offsets:
        buf += f"{off:010d} 00000 n \n".encode("latin-1")
    buf += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode("latin-1")
    Path(path).write_bytes(bytes(buf))
    return Path(path)


def make_corrupt_docx(path: Path) -> Path:
    """一个扩展名是 .docx 但其实是垃圾的文件，用来验证不会把索引搞崩。"""
    Path(path).write_bytes(b"\x00\x01\x02 this is not a zip file \xff\xfe")
    return Path(path)


def build_all(folder: Path) -> dict[str, Path]:
    """在 folder 下造一整套样本，返回 {名字: 路径}。"""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}

    out["docx"] = make_docx(
        folder / "年度总结.docx",
        ["2026 年度工作总结", "本年度完成了桌面管理助手的开发", "下一阶段重点是内容检索"],
    )
    out["xlsx"] = make_xlsx(
        folder / "预算表.xlsx",
        ["项目", "金额", "机械结构有限元分析预算", "128000", "差旅费", "5600"],
    )
    out["pptx"] = make_pptx(
        folder / "季度汇报.pptx",
        ["第三季度汇报", "营收同比增长 18%", "下季度计划拓展海外市场"],
    )
    out["pdf"] = make_pdf(folder / "验收报告.pdf")
    out["txt_utf8"] = make_txt(
        folder / "说明.txt", "这是 UTF-8 编码的说明文档，关键词：桌面整理"
    )
    out["txt_gbk"] = make_txt(
        folder / "老文件.txt", "这是 GBK 编码的老文件，关键词：发票归档", encoding="gb18030"
    )
    out["rtf"] = make_rtf(folder / "备忘.rtf")
    out["corrupt"] = make_corrupt_docx(folder / "损坏的.docx")
    out["legacy"] = make_txt(folder / "旧版文档.doc", "legacy", encoding="latin-1")
    return out
