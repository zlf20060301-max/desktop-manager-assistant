"""文档内容索引：把提取出来的正文存进 SQLite，供内容搜索使用。

为什么要缓存：
- 提取正文（尤其 PDF）是慢操作，不能每次敲键盘都重来一遍。
- 用 (修改时间, 大小) 判断文件有没有变过，没变就直接复用。
- 索引放在用户数据目录，和程序本身分开。

线程模型：索引在后台线程跑，搜索在主线程跑。SQLite 用 WAL + 一把锁，
写和读不会互相阻塞到卡界面。
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

from .extract import (
    STATUS_ERROR,
    STATUS_OK,
    STATUS_UNSUPPORTED,
    ExtractResult,
    extract,
    is_supported,
    is_legacy_office,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
    path    TEXT PRIMARY KEY,
    mtime   REAL NOT NULL,
    size    INTEGER NOT NULL,
    ext     TEXT NOT NULL,
    status  TEXT NOT NULL,
    note    TEXT DEFAULT '',
    text    TEXT DEFAULT '',
    indexed_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_docs_status ON docs(status);
"""

SNIPPET_BEFORE = 30
SNIPPET_AFTER = 70


@dataclass
class IndexStats:
    total: int = 0
    ok: int = 0
    empty: int = 0
    unsupported: int = 0
    error: int = 0


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def terms_of(query: str) -> list[str]:
    """把查询拆成词。多个词之间是「都要出现」，单个词就是普通子串匹配。"""
    return [t for t in re.split(r"\s+", (query or "").strip()) if t]


def make_snippet(text: str, query: str, radius_before: int = SNIPPET_BEFORE,
                 radius_after: int = SNIPPET_AFTER) -> str:
    """截出命中位置附近的一段，压掉换行方便在表格里显示。"""
    terms = terms_of(query)
    if not text or not terms:
        return ""
    low = text.lower()
    pos = -1
    for t in terms:
        pos = low.find(t.lower())
        if pos >= 0:
            break
    if pos < 0:
        return ""

    start = max(0, pos - radius_before)
    end = min(len(text), pos + len(terms[0]) + radius_after)
    frag = re.sub(r"\s+", " ", text[start:end]).strip()
    return ("…" if start > 0 else "") + frag + ("…" if end < len(text) else "")


class ContentIndex:
    """文档正文索引。线程安全。"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 读
    # ------------------------------------------------------------------

    def _meta(self, path: Path) -> tuple[float, int, str] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT mtime, size, status FROM docs WHERE path = ?", (str(path),)
            ).fetchone()
        return (row[0], row[1], row[2]) if row else None

    def is_fresh(self, path: Path, mtime: float, size: int) -> bool:
        """这个文件是否已经索引过、而且之后没被改过。"""
        meta = self._meta(path)
        if meta is None:
            return False
        return abs(meta[0] - mtime) < 1e-6 and meta[1] == size

    def stats(self) -> IndexStats:
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) FROM docs GROUP BY status"
            ).fetchall()
        s = IndexStats()
        for status, n in rows:
            s.total += n
            if status == STATUS_OK:
                s.ok = n
            elif status == "empty":
                s.empty = n
            elif status == STATUS_UNSUPPORTED:
                s.unsupported = n
            elif status == STATUS_ERROR:
                s.error = n
        return s

    def known_extensions(self) -> set[str]:
        with self._lock:
            return {r[0] for r in self._conn.execute("SELECT DISTINCT ext FROM docs")}

    # ------------------------------------------------------------------
    # 写
    # ------------------------------------------------------------------

    def put(self, path: Path, mtime: float, size: int, ext: str,
            result: ExtractResult) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO docs "
                "(path, mtime, size, ext, status, note, text, indexed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (str(path), mtime, size, ext, result.status,
                 result.note[:300], result.text, time.time()),
            )
            self._conn.commit()

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM docs")
            self._conn.commit()

    def prune(self, root: Path, keep: Sequence[Path]) -> int:
        """删掉 root 之下、但已经不在本次扫描结果里的记录。"""
        root_s = str(Path(root)).lower()
        keep_set = {str(p).lower() for p in keep}
        with self._lock:
            rows = self._conn.execute("SELECT path FROM docs").fetchall()
            stale = [
                (r[0],) for r in rows
                if r[0].lower().startswith(root_s) and r[0].lower() not in keep_set
            ]
            if stale:
                self._conn.executemany("DELETE FROM docs WHERE path = ?", stale)
                self._conn.commit()
        return len(stale)

    # ------------------------------------------------------------------
    # 批量索引
    # ------------------------------------------------------------------

    def ensure(
        self,
        entries: Iterable,
        *,
        progress: Callable[[int, int], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> tuple[int, int, int]:
        """把还没索引 / 已过期的文档补上。

        返回 (新索引数, 已是最新跳过数, 失败数)。
        """
        targets = []
        for e in entries:
            if getattr(e, "is_dir", False):
                continue
            ext = (getattr(e, "ext", "") or "").lower()
            if not is_supported(ext):
                continue
            targets.append(e)

        total = len(targets)
        added = skipped = failed = 0

        for i, e in enumerate(targets):
            if should_cancel is not None and should_cancel():
                break
            if progress is not None:
                progress(i, total)
            try:
                if self.is_fresh(e.path, e.mtime, e.size):
                    skipped += 1
                    continue
                result = extract(e.path, e.ext)
                self.put(e.path, e.mtime, e.size, e.ext, result)
                if result.status == STATUS_ERROR:
                    failed += 1
                else:
                    added += 1
            except Exception:  # noqa: BLE001 - 单个文件失败不影响整轮
                failed += 1

        if progress is not None:
            progress(total, total)
        return added, skipped, failed

    # ------------------------------------------------------------------
    # 搜索
    # ------------------------------------------------------------------

    def search(self, query: str) -> dict[str, tuple[str, int]]:
        """按内容搜。返回 {路径小写: (命中片段, 命中次数)}。

        多个词要全部出现（AND）；单个词就是普通子串匹配。

        注意键是**小写**的：Windows 路径大小写不敏感，界面查表用的也是小写键，
        这里不统一的话 C:\\Users\\... 这种带大写的路径永远查不中。
        """
        terms = terms_of(query)
        if not terms:
            return {}

        sql = "SELECT path, text FROM docs WHERE status = ?"
        params: list = [STATUS_OK]
        for t in terms:
            sql += " AND text LIKE ? ESCAPE '\\'"
            params.append(f"%{_escape_like(t)}%")

        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()

        out: dict[str, tuple[str, int]] = {}
        q = " ".join(terms)
        for path, text in rows:
            text = text or ""
            low = text.lower()
            if not all(t.lower() in low for t in terms):
                continue          # LIKE 对非 ASCII 不区分大小写，这里再兜一次
            hits = min(low.count(terms[0].lower()), 999)
            out[path.lower()] = (make_snippet(text, q), hits)
        return out

    def note_for(self, path: Path) -> tuple[str, str]:
        """取某个文件的索引状态，用于告诉用户「为什么搜不到」。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT status, note FROM docs WHERE path = ?", (str(path),)
            ).fetchone()
        return (row[0], row[1]) if row else ("", "")


def index_path_for(data_dir: Path) -> Path:
    return Path(data_dir) / "content_index.db"


def describe_status(status: str, note: str, ext: str) -> str:
    """把索引状态翻译成用户看得懂的一句话。"""
    if status == STATUS_OK:
        return "已索引"
    if status == "empty":
        return note or "没有可提取的文字"
    if status == STATUS_ERROR:
        return note or "读取失败"
    if is_legacy_office(ext):
        return note or "老版 Office 二进制格式，暂不支持内容搜索"
    if status == STATUS_UNSUPPORTED:
        return note or "该格式不支持内容搜索"
    if not is_supported(ext):
        return "该格式不支持内容搜索"
    return "尚未索引（还在建立索引，稍等）"
