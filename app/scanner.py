"""桌面扫描：把目录内容读成 Entry 列表。"""

from __future__ import annotations

import os
import stat as _stat
from dataclasses import dataclass, field
from pathlib import Path

from .categorizer import categorize, ext_of

# 系统噪声文件，永远不显示
EXCLUDE_NAMES = {
    "desktop.ini",
    "thumbs.db",
    ".ds_store",
    "iconcache.db",
    "$recycle.bin",
    "system volume information",
}

FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4


@dataclass(slots=True)
class Entry:
    """一条桌面条目（文件或文件夹）。"""

    path: Path
    name: str
    is_dir: bool
    ext: str
    size: int
    mtime: float
    category: str
    hidden: bool = False
    is_shortcut: bool = False

    @property
    def suffix(self) -> str:
        return self.ext if self.ext else "—"

    @property
    def parent(self) -> Path:
        return self.path.parent


def _is_hidden(st: os.stat_result, name: str) -> bool:
    attrs = getattr(st, "st_file_attributes", 0)
    if attrs and (attrs & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM)):
        return True
    return name.startswith(".")


def scan(
    root: Path | str,
    *,
    recursive: bool = False,
    show_hidden: bool = False,
    include_dirs: bool = True,
) -> list[Entry]:
    """扫描 root 目录，返回 Entry 列表（不递归时只扫第一层）。"""
    root = Path(root)
    out: list[Entry] = []
    if not root.is_dir():
        return out

    try:
        if recursive:
            iterator = (
                Path(dirpath) / name
                for dirpath, _dirnames, filenames in os.walk(root)
                for name in filenames
            )
            only_files = list(iterator)
            if include_dirs:
                for dirpath, dirnames, _f in os.walk(root):
                    for dn in dirnames:
                        only_files.append(Path(dirpath) / dn)
            candidates = only_files
        else:
            candidates = list(root.iterdir())
    except OSError:
        return out

    for p in candidates:
        name = p.name
        if name.lower() in EXCLUDE_NAMES:
            continue
        try:
            st = p.stat()
        except OSError:
            continue

        hidden = _is_hidden(st, name)
        if hidden and not show_hidden:
            continue

        try:
            is_dir = p.is_dir()
        except OSError:
            is_dir = False
        if is_dir and not include_dirs:
            continue

        ext = "" if is_dir else ext_of(name)
        out.append(
            Entry(
                path=p,
                name=name,
                is_dir=is_dir,
                ext=ext,
                size=0 if is_dir else st.st_size,
                mtime=st.st_mtime,
                category=categorize(name, is_dir),
                hidden=hidden,
                is_shortcut=ext in (".lnk", ".url"),
            )
        )
    out.sort(key=lambda e: (e.is_dir is False, e.name.lower()))
    return out


def category_counts(entries: list[Entry]) -> dict[str, int]:
    """统计各分类条目数。"""
    counts: dict[str, int] = {}
    for e in entries:
        counts[e.category] = counts.get(e.category, 0) + 1
    return counts


def human_size(n: int) -> str:
    """字节数转可读字符串。"""
    if n < 1024:
        return f"{n} B"
    units = ["KB", "MB", "GB", "TB", "PB"]
    val = float(n)
    for u in units:
        val /= 1024.0
        if val < 1024.0:
            return f"{val:.1f} {u}"
    return f"{val:.1f} EB"
