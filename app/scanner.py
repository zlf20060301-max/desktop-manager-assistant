"""桌面扫描：把目录内容读成 Entry 列表。"""

from __future__ import annotations

import os
import stat as _stat
from dataclasses import dataclass, field
from pathlib import Path

from .categorizer import CategoryMap, categorize as default_categorize, ext_of

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


def _walk_breadth_first(root: Path, max_items: int | None = None):
    """广度优先遍历：先给浅层的文件，再给深层的。

    桌面上往往有上万项（比如一整棵代码仓库），必须保证"离桌面最近的"
    文件优先进入结果，否则截断后剩下的全是某个深层目录里的东西。
    max_items 为 None 表示不限量。
    """
    remaining = max_items if max_items else None
    queue: list[tuple[Path, int]] = [(root, 0)]
    while queue:
        current, depth = queue.pop(0)
        try:
            children = list(current.iterdir())
        except OSError:
            continue
        subdirs: list[Path] = []
        for child in children:
            try:
                is_dir = child.is_dir()
            except OSError:
                is_dir = False
            if is_dir:
                subdirs.append(child)
            else:
                yield child, depth
                if remaining is not None:
                    remaining -= 1
                    if remaining <= 0:
                        return
        for d in subdirs:
            queue.append((d, depth + 1))


def scan(
    root: Path | str,
    *,
    recursive: bool = False,
    show_hidden: bool = False,
    include_dirs: bool = True,
    categorizer: CategoryMap | None = None,
    max_items: int | None = None,
) -> list[Entry]:
    """扫描 root 目录，返回 Entry 列表（不递归时只扫第一层）。

    categorizer 传 CategoryMap 时会带上用户自定义的后缀映射，
    不传就用内置分类表。

    recursive 时会广度优先遍历并受 max_items 限制，返回的列表可能被截断；
    需要知道是否截断请用 scan_with_meta()。
    """
    return scan_with_meta(
        root,
        recursive=recursive,
        show_hidden=show_hidden,
        include_dirs=include_dirs,
        categorizer=categorizer,
        max_items=max_items,
    ).entries


@dataclass
class ScanResult:
    entries: list[Entry] = field(default_factory=list)
    truncated: bool = False
    visited: int = 0


def scan_with_meta(
    root: Path | str,
    *,
    recursive: bool = False,
    show_hidden: bool = False,
    include_dirs: bool = True,
    categorizer: CategoryMap | None = None,
    max_items: int | None = None,
) -> ScanResult:
    """带元信息的扫描：能告诉你结果是不是被上限截断了。"""
    root = Path(root)
    classify = categorizer.categorize if categorizer is not None else default_categorize
    result = ScanResult()
    if not root.is_dir():
        return result

    # 收集候选（文件 + 文件夹）
    files: list[Path] = []
    dirs: list[Path] = []
    truncated = False

    if recursive:
        budget = max_items if max_items else 0
        for p, _depth in _walk_breadth_first(root, max_items):
            files.append(p)
            if max_items and len(files) >= max_items:
                truncated = True
                break
        if include_dirs:
            remaining = max(0, (max_items or 10**9) - len(files))
            for d in _collect_dirs(root, remaining):
                dirs.append(d)
    else:
        try:
            for p in root.iterdir():
                try:
                    if p.is_dir():
                        dirs.append(p)
                    else:
                        files.append(p)
                except OSError:
                    continue
        except OSError:
            return result

    def build(paths: list[Path], is_dir: bool) -> None:
        for p in paths:
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
            ext = "" if is_dir else ext_of(name)
            result.entries.append(
                Entry(
                    path=p,
                    name=name,
                    is_dir=is_dir,
                    ext=ext,
                    size=0 if is_dir else st.st_size,
                    mtime=st.st_mtime,
                    category=classify(name, is_dir),
                    hidden=hidden,
                    is_shortcut=ext in (".lnk", ".url"),
                )
            )

    build(dirs if include_dirs else [], True)
    build(files, False)

    result.truncated = truncated
    result.visited = len(result.entries)
    result.entries.sort(key=lambda e: (e.is_dir is False, e.name.lower()))
    return result


def _collect_dirs(root: Path, limit: int):
    if limit <= 0:
        return
    count = 0
    for dirpath, dirnames, _files in os.walk(root):
        for dn in dirnames:
            yield Path(dirpath) / dn
            count += 1
            if count >= limit:
                return


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
