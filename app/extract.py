"""文本提取：把各种文档里的可搜索文本抠出来。

设计原则：
1. 能不依赖第三方库就不依赖。docx / xlsx / pptx / odt 本质都是 zip + XML，
   用标准库解就够了。
2. 只有 PDF 需要 pypdf（纯 Python）。装了就用，没装就跳过 PDF，不影响其它格式。
3. 所有提取都要能失败而不崩：单个文件读不了只返回 error 状态，不能让整轮索引挂掉。
4. 有上限：超大文件、超多页的 PDF 会被截断，避免索引卡死。
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

# ---------- 上限 ----------
MAX_SOURCE_BYTES = 8 * 1024 * 1024      # 超过这个大小的文件不读
MAX_TEXT_CHARS = 500_000                # 每个文件最多保留这么多字符
MAX_PDF_PAGES = 300

# ---------- 纯文本类：直接按编码读 ----------
TEXT_EXTS: set[str] = {
    ".txt", ".md", ".markdown", ".log", ".csv", ".tsv", ".json", ".xml",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".properties",
    ".py", ".pyw", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".html", ".htm", ".css", ".scss", ".less", ".java", ".kt", ".c", ".cpp",
    ".cc", ".h", ".hpp", ".cs", ".go", ".rs", ".php", ".rb", ".swift",
    ".sql", ".sh", ".bash", ".bat", ".cmd", ".ps1", ".vue", ".svelte",
    ".lua", ".pl", ".r", ".m", ".gradle", ".srt", ".vtt", ".tex", ".bib",
}

# ---------- 压缩包式文档：zip + XML ----------
ZIP_XML_EXTS: set[str] = {".docx", ".docm", ".xlsx", ".xlsm", ".pptx", ".pptm", ".odt", ".ods", ".odp"}

# ---------- 其它单独处理 ----------
RTF_EXTS: set[str] = {".rtf"}
PDF_EXTS: set[str] = {".pdf"}

# ---------- 明确不支持的（老版二进制 Office） ----------
LEGACY_EXTS: set[str] = {".doc", ".xls", ".ppt", ".wps", ".et", ".dps"}

SUPPORTED_EXTS: set[str] = TEXT_EXTS | ZIP_XML_EXTS | RTF_EXTS | PDF_EXTS

STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_UNSUPPORTED = "unsupported"
STATUS_ERROR = "error"
STATUS_TOO_BIG = "too_big"


@dataclass
class ExtractResult:
    status: str
    text: str = ""
    note: str = ""

    @property
    def searchable(self) -> bool:
        return self.status == STATUS_OK and bool(self.text)


def is_supported(ext: str) -> bool:
    return (ext or "").lower() in SUPPORTED_EXTS


def is_legacy_office(ext: str) -> bool:
    return (ext or "").lower() in LEGACY_EXTS


# --------------------------------------------------------------------------
# 纯文本
# --------------------------------------------------------------------------

def _decode(data: bytes) -> str:
    """按常见编码依次尝试。中文环境里 GBK 非常常见，不能只试 utf-8。"""
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig", errors="replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    for enc in ("utf-8", "gb18030", "big5", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _read_text_file(path: Path) -> ExtractResult:
    try:
        size = path.stat().st_size
    except OSError as exc:
        return ExtractResult(STATUS_ERROR, note=str(exc))
    if size > MAX_SOURCE_BYTES:
        return ExtractResult(STATUS_TOO_BIG, note=f"文件过大（{size / 1048576:.1f} MB）")
    try:
        data = path.read_bytes()
    except OSError as exc:
        return ExtractResult(STATUS_ERROR, note=str(exc))
    text = _decode(data)[:MAX_TEXT_CHARS]
    if not text.strip():
        return ExtractResult(STATUS_EMPTY)
    return ExtractResult(STATUS_OK, text)


# --------------------------------------------------------------------------
# docx / xlsx / pptx / odt：zip + XML
# --------------------------------------------------------------------------

_NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "t": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
}

# (成员名正则, 取文本的标签集合, 断行标签集合)
_ZIP_PLANS: dict[str, tuple[list[str], set[str], set[str]]] = {
    ".docx": (
        [r"^word/document\.xml$", r"^word/header\d*\.xml$", r"^word/footer\d*\.xml$",
         r"^word/footnotes\.xml$", r"^word/endnotes\.xml$", r"^word/comments\.xml$"],
        {f"{{{_NS['w']}}}t"},
        {f"{{{_NS['w']}}}p", f"{{{_NS['w']}}}br", f"{{{_NS['w']}}}tab"},
    ),
    ".docm": ([r"^word/document\.xml$"], {f"{{{_NS['w']}}}t"}, {f"{{{_NS['w']}}}p"}),
    ".xlsx": (
        [r"^xl/sharedStrings\.xml$", r"^xl/worksheets/sheet\d*\.xml$"],
        {f"{{{_NS['x']}}}t"},
        {f"{{{_NS['x']}}}row"},
    ),
    ".xlsm": ([r"^xl/sharedStrings\.xml$"], {f"{{{_NS['x']}}}t"}, set()),
    ".pptx": (
        [r"^ppt/slides/slide\d+\.xml$", r"^ppt/notesSlides/notesSlide\d+\.xml$"],
        {f"{{{_NS['a']}}}t"},
        {f"{{{_NS['a']}}}p"},
    ),
    ".pptm": ([r"^ppt/slides/slide\d+\.xml$"], {f"{{{_NS['a']}}}t"}, set()),
    ".odt": ([r"^content\.xml$"], {f"{{{_NS['t']}}}p", f"{{{_NS['t']}}}h"}, set()),
    ".ods": ([r"^content\.xml$"], {f"{{{_NS['t']}}}p"}, set()),
    ".odp": ([r"^content\.xml$"], {f"{{{_NS['t']}}}p"}, set()),
}


def _extract_stream(fileobj, text_tags: set[str], break_tags: set[str]) -> str:
    """流式解析 XML，只挑出需要的文本节点，避免整棵树进内存。"""
    parts: list[str] = []
    try:
        for _event, elem in ET.iterparse(fileobj, events=("end",)):
            if elem.tag in text_tags:
                if elem.text:
                    parts.append(elem.text)
            elif elem.tag in break_tags:
                parts.append("\n")
            elem.clear()
    except ET.ParseError:
        pass
    return "".join(parts)


def _read_zip_xml(path: Path, ext: str) -> ExtractResult:
    plan = _ZIP_PLANS.get(ext)
    if plan is None:
        return ExtractResult(STATUS_UNSUPPORTED)
    patterns, text_tags, break_tags = plan
    regexes = [re.compile(p) for p in patterns]

    try:
        with zipfile.ZipFile(path) as zf:
            members = sorted(
                n for n in zf.namelist()
                if not n.endswith("/") and any(r.match(n) for r in regexes)
            )
            if not members:
                return ExtractResult(STATUS_EMPTY, note="文档里没有找到正文")
            chunks: list[str] = []
            total = 0
            for name in members:
                with zf.open(name) as fh:
                    piece = _extract_stream(fh, text_tags, break_tags)
                if piece:
                    chunks.append(piece)
                    total += len(piece)
                if total > MAX_TEXT_CHARS:
                    break
    except zipfile.BadZipFile:
        return ExtractResult(STATUS_ERROR, note="文件损坏或不是有效的 Office 文档")
    except OSError as exc:
        return ExtractResult(STATUS_ERROR, note=str(exc))

    text = "\n".join(chunks)[:MAX_TEXT_CHARS]
    if not text.strip():
        return ExtractResult(STATUS_EMPTY)
    return ExtractResult(STATUS_OK, text)


# --------------------------------------------------------------------------
# RTF
# --------------------------------------------------------------------------

_RTF_CTRL = re.compile(r"\\[a-zA-Z]+-?\d*\s?")
_RTF_HEX = re.compile(r"\\'([0-9a-fA-F]{2})")
_RTF_UNICODE = re.compile(r"\\u(-?\d+)\s?\??")
_RTF_BRACES = re.compile(r"[{}]")

# 这些组里的内容不是正文，要整组丢掉
# （字体表、颜色表、图片、样式表……）
_RTF_DROP_GROUPS = {
    "fonttbl", "colortbl", "stylesheet", "info", "pict", "object",
    "themedata", "datastore", "latentstyles", "rsidtbl", "generator",
    "listtable", "listoverridetable", "xmlnstbl", "filetbl",
}
# \uNNNN 先换成哨兵，等整段按 GBK 解完码再还原，
# 否则 Unicode 字符会被跟着当成 GBK 字节解坏。
# 哨兵不能带空格填充：那会把连续的汉字拆开（"项目" 变 "项 目"），
# 直接导致按内容搜不到。\x01 不是合法的 GBK 尾字节，足够安全。
_UNI_SENTINEL = "\x01{:05X}\x01"
_UNI_SENTINEL_RE = re.compile(r"\x01([0-9A-F]{5})\x01")
# 控制字留下的空格夹在汉字之间时要去掉，否则同样会把词切断
_CJK_GAP = re.compile(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])")


def _stash_unicode(match: re.Match) -> str:
    value = int(match.group(1))
    if value < 0:
        value += 65536
    return _UNI_SENTINEL.format(value & 0xFFFF)


def _drop_rtf_groups(s: str, names: set[str]) -> str:
    """按花括号配对丢掉整组内容。

    不能用正则 [^{}]* —— 字体表里还有嵌套的 {\f0 ...}，
    正则匹配不到就会把内容漏进正文（实测会漏出 "SimSun;"）。
    """
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        if s[i] == "{" and i + 1 < n and s[i + 1] == "\\":
            j = i + 2
            if j < n and s[j] == "*":          # {\*\generator ...}
                j += 1
            k = j
            while k < n and s[k].isalpha():
                k += 1
            if s[j:k] in names:
                depth, p = 1, i + 1
                while p < n and depth:
                    if s[p] == "{" and s[p - 1] != "\\":
                        depth += 1
                    elif s[p] == "}" and s[p - 1] != "\\":
                        depth -= 1
                    p += 1
                out.append(" ")
                i = p
                continue
        out.append(s[i])
        i += 1
    return "".join(out)


def _read_rtf(path: Path) -> ExtractResult:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return ExtractResult(STATUS_ERROR, note=str(exc))
    if len(raw) > MAX_SOURCE_BYTES:
        return ExtractResult(STATUS_TOO_BIG)

    # 先用 latin-1 保证字节不丢，再逐段还原转义
    s = raw.decode("latin-1")
    s = _drop_rtf_groups(s, _RTF_DROP_GROUPS)
    s = _RTF_UNICODE.sub(_stash_unicode, s)
    s = _RTF_HEX.sub(lambda m: chr(int(m.group(1), 16)), s)
    s = _RTF_CTRL.sub(
        lambda m: "\n" if m.group(0).rstrip().endswith(("par", "line")) else " ", s
    )
    s = _RTF_BRACES.sub(" ", s)

    # \'xx 是文档代码页里的字节，中文 RTF 通常是 GBK
    try:
        s = s.encode("latin-1", errors="ignore").decode("gb18030", errors="replace")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    s = _UNI_SENTINEL_RE.sub(lambda m: chr(int(m.group(1), 16)), s)

    s = _CJK_GAP.sub("", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    text = s[:MAX_TEXT_CHARS]
    if not text.strip():
        return ExtractResult(STATUS_EMPTY)
    return ExtractResult(STATUS_OK, text)


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------

_pypdf_checked = False
_pypdf_reader = None


def _get_pdf_reader():
    global _pypdf_checked, _pypdf_reader
    if not _pypdf_checked:
        _pypdf_checked = True
        try:
            from pypdf import PdfReader  # noqa: PLC0415
            _pypdf_reader = PdfReader
        except Exception:
            _pypdf_reader = None
    return _pypdf_reader


def pdf_available() -> bool:
    return _get_pdf_reader() is not None


def _read_pdf(path: Path) -> ExtractResult:
    reader_cls = _get_pdf_reader()
    if reader_cls is None:
        return ExtractResult(STATUS_UNSUPPORTED, note="没有安装 pypdf，无法读取 PDF")

    try:
        if path.stat().st_size > MAX_SOURCE_BYTES * 4:
            return ExtractResult(STATUS_TOO_BIG, note="PDF 文件过大")
        reader = reader_cls(str(path))
        if getattr(reader, "is_encrypted", False):
            try:
                reader.decrypt("")   # 空密码的加密 PDF 很常见
            except Exception:
                return ExtractResult(STATUS_ERROR, note="PDF 已加密，无法读取")
        chunks: list[str] = []
        total = 0
        for page in reader.pages[:MAX_PDF_PAGES]:
            try:
                chunk = page.extract_text() or ""
            except Exception:
                continue
            if chunk:
                chunks.append(chunk)
                total += len(chunk)
            if total > MAX_TEXT_CHARS:
                break
    except Exception as exc:  # noqa: BLE001 - 各种 PDF 异常都归到 error
        return ExtractResult(STATUS_ERROR, note=f"PDF 解析失败：{exc}")

    text = "\n".join(chunks)[:MAX_TEXT_CHARS]
    if not text.strip():
        return ExtractResult(STATUS_EMPTY, note="PDF 里没有可提取的文字（可能是扫描件）")
    return ExtractResult(STATUS_OK, text)


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------

def extract(path: Path | str, ext: str | None = None) -> ExtractResult:
    """提取一个文件的正文文本。任何异常都会被兜住并转成 error 状态。"""
    p = Path(path)
    e = (ext if ext is not None else p.suffix).lower()

    try:
        if e in TEXT_EXTS:
            return _read_text_file(p)
        if e in ZIP_XML_EXTS:
            return _read_zip_xml(p, e)
        if e in RTF_EXTS:
            return _read_rtf(p)
        if e in PDF_EXTS:
            return _read_pdf(p)
        if e in LEGACY_EXTS:
            return ExtractResult(STATUS_UNSUPPORTED, note="老版 Office 二进制格式，暂不支持提取正文")
        return ExtractResult(STATUS_UNSUPPORTED)
    except Exception as exc:  # noqa: BLE001 - 绝不因为一个文件搞挂整轮索引
        return ExtractResult(STATUS_ERROR, note=f"{type(exc).__name__}: {exc}")
