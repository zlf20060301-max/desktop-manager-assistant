"""文件操作层：归档规划、批量重命名规划、执行、撤销、回收站删除。

设计原则：
1. 只做"规划 -> 预览 -> 执行"三步，任何破坏性动作前都有预览。
2. 所有落盘操作都进 Journal，可整批撤销。
3. 所有路径必须落在指定根目录内，越界直接拒绝。
"""

from __future__ import annotations

import ctypes
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from .journal import Journal
from .scanner import Entry

# 冲突策略
POLICY_RENAME = "rename"
POLICY_SKIP = "skip"
POLICY_OVERWRITE = "overwrite"

POLICY_LABELS = {
    POLICY_RENAME: "自动重命名（推荐）",
    POLICY_SKIP: "跳过已存在的",
    POLICY_OVERWRITE: "覆盖同名文件",
}

STATUS_OK = "ok"
STATUS_SKIP = "skip"
STATUS_CONFLICT = "conflict"


@dataclass
class PlanItem:
    """一条待执行的移动/重命名。"""

    src: Path
    dst: Path
    status: str = STATUS_OK
    message: str = ""

    @property
    def runnable(self) -> bool:
        return self.status == STATUS_OK


@dataclass
class ExecResult:
    ok: int = 0
    skipped: int = 0
    failed: int = 0
    cleaned: int = 0
    errors: list[str] = field(default_factory=list)
    moves: list[tuple[str, str]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.ok + self.skipped + self.failed

    def summary(self) -> str:
        parts = [f"成功 {self.ok}"]
        if self.skipped:
            parts.append(f"跳过 {self.skipped}")
        if self.failed:
            parts.append(f"失败 {self.failed}")
        if self.cleaned:
            parts.append(f"清理空文件夹 {self.cleaned}")
        return "，".join(parts)


# --------------------------------------------------------------------------
# 路径工具
# --------------------------------------------------------------------------

def is_within(root: Path, path: Path) -> bool:
    """path 是否在 root 之内（含 root 本身）。"""
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except (ValueError, OSError):
        return False


def _key(p: Path) -> str:
    return str(p).lower()


def unique_path(dst: Path, taken: set[str] | None = None) -> Path:
    """若目标已存在（或已被本批次占用），在名字后面直接接数字：报告.docx -> 报告1.docx。

    数字从 1 开始递增，直到既不撞磁盘上的文件、也不撞本批次其它条目。
    """
    taken = taken if taken is not None else set()
    if not dst.exists() and _key(dst) not in taken:
        return dst
    stem = dst.stem
    suffix = dst.suffix
    parent = dst.parent
    i = 1
    while True:
        cand = parent / f"{stem}{i}{suffix}"
        if not cand.exists() and _key(cand) not in taken:
            return cand
        i += 1
        if i > 9999:
            raise RuntimeError(f"无法为 {dst} 生成不冲突的文件名")


# --------------------------------------------------------------------------
# 归档规划
# --------------------------------------------------------------------------

def plan_archive(
    entries: Sequence[Entry],
    targets: dict[str, str],
    root: Path,
    policy: str = POLICY_RENAME,
    *,
    only_direct_children: bool = True,
) -> list[PlanItem]:
    """按 分类->目标文件夹 规则，规划把文件移动到桌面下的二级文件夹。

    只处理文件，不处理文件夹；已经在目标文件夹里的不再重复移动。
    """
    root = Path(root)
    plan: list[PlanItem] = []
    taken: set[str] = set()

    for e in entries:
        if e.is_dir:
            continue
        target_name = targets.get(e.category)
        if not target_name:
            continue
        if only_direct_children and _key(e.path.parent) != _key(root):
            continue

        dest_dir = root / target_name
        dst = dest_dir / e.name

        if _key(e.path) == _key(dst):
            plan.append(PlanItem(e.path, dst, STATUS_SKIP, "已在目标位置"))
            continue
        if not is_within(root, e.path):
            plan.append(PlanItem(e.path, dst, STATUS_SKIP, "源文件不在桌面内，已跳过"))
            continue
        if not is_within(root, dst):
            plan.append(PlanItem(e.path, dst, STATUS_SKIP, "目标路径越界，已跳过"))
            continue

        if dst.exists() or _key(dst) in taken:
            if policy == POLICY_SKIP:
                plan.append(PlanItem(e.path, dst, STATUS_SKIP, "目标已存在，跳过"))
                continue
            if policy == POLICY_OVERWRITE and dst.is_file():
                plan.append(PlanItem(e.path, dst, STATUS_OK, "将覆盖同名文件"))
                taken.add(_key(dst))
                continue
            new_dst = unique_path(dst, taken)
            plan.append(PlanItem(e.path, new_dst, STATUS_OK, "重名，已自动加数字"))
            taken.add(_key(new_dst))
            continue

        plan.append(PlanItem(e.path, dst, STATUS_OK))
        taken.add(_key(dst))

    return plan


# --------------------------------------------------------------------------
# 重命名规划
# --------------------------------------------------------------------------

@dataclass
class RenameOptions:
    mode: str = "replace"  # replace | prefix | suffix | number | case
    find: str = ""
    replace: str = ""
    use_regex: bool = False
    case_sensitive: bool = False
    prefix: str = ""
    suffix: str = ""
    number_base: str = "文件"
    number_start: int = 1
    number_step: int = 1
    number_digits: int = 2
    number_keep_name: bool = False
    case_mode: str = "lower"  # lower | upper | title


def _new_name(name: str, opts: RenameOptions, index: int) -> str:
    p = Path(name)
    stem, ext = p.stem, p.suffix
    mode = opts.mode

    if mode == "replace":
        if not opts.find:
            return name
        if opts.use_regex:
            flags = 0 if opts.case_sensitive else re.IGNORECASE
            try:
                new_stem = re.sub(opts.find, opts.replace, stem, flags=flags)
            except re.error:
                return name
        else:
            if opts.case_sensitive:
                new_stem = stem.replace(opts.find, opts.replace)
            else:
                new_stem = re.sub(
                    re.escape(opts.find), opts.replace.replace("\\", "\\\\"), stem,
                    flags=re.IGNORECASE,
                )
        return f"{new_stem}{ext}"

    if mode == "prefix":
        return f"{opts.prefix}{stem}{ext}"

    if mode == "suffix":
        return f"{stem}{opts.suffix}{ext}"

    if mode == "number":
        num = opts.number_start + index * opts.number_step
        digits = max(1, min(8, opts.number_digits))
        tag = f"{num:0{digits}d}"
        if opts.number_keep_name:
            return f"{opts.number_base}{tag}_{stem}{ext}"
        return f"{opts.number_base}{tag}{ext}"

    if mode == "case":
        if opts.case_mode == "upper":
            new_stem = stem.upper()
        elif opts.case_mode == "title":
            new_stem = stem.title()
        else:
            new_stem = stem.lower()
        return f"{new_stem}{ext}"

    return name


def _name_error(new_name: str, old_name: str) -> str | None:
    """检查新名字是否可用。名称没变化不算错误。"""
    if new_name == old_name:
        return None
    if not new_name.strip() or new_name in (".", ".."):
        return "新名称为空，已跳过"
    if any(ch in new_name for ch in '\\/:*?"<>|'):
        return "新名称含非法字符，已跳过"
    return None


def plan_rename(entries: Sequence[Entry], opts: RenameOptions) -> list[PlanItem]:
    """规划批量重命名。

    重名不再跳过，而是在名字后面直接加数字：报告.docx -> 报告1.docx。
    两种情况都算重名：本批次内别的条目已经占了这个名字，或者磁盘上
    本来就有这个文件（且它不会被本批次改走）。
    """
    # 先按目录 + 名称排序，保证编号稳定且符合直觉
    ordered = sorted(entries, key=lambda e: (_key(e.path.parent), e.name.lower()))
    raw = [(e, _new_name(e.name, opts, idx)) for idx, e in enumerate(ordered)]

    # 只有"真的会被改走、且新名字合法"的条目才会腾出位置。
    # 名称未变的条目不会动，所以别的条目不能指望它让位。
    vacating = {
        _key(e.path)
        for e, n in raw
        if n != e.name and _name_error(n, e.name) is None
    }

    plan: list[PlanItem] = []
    used: dict[str, set[str]] = {}

    for e, new_name in raw:
        dst = e.path.parent / new_name
        bucket = used.setdefault(_key(e.path.parent), set())

        if new_name == e.name:
            plan.append(PlanItem(e.path, dst, STATUS_SKIP, "名称未变化"))
            bucket.add(_key(dst))
            continue

        err = _name_error(new_name, e.name)
        if err is not None:
            plan.append(PlanItem(e.path, dst, STATUS_CONFLICT, err))
            continue

        blocked = _key(dst) in bucket or (dst.exists() and _key(dst) not in vacating)
        if blocked:
            dst = unique_path(dst, bucket)
            plan.append(PlanItem(e.path, dst, STATUS_OK, "重名，已自动加数字"))
        else:
            plan.append(PlanItem(e.path, dst, STATUS_OK))
        bucket.add(_key(dst))

    return _order_renames(plan)


def _order_renames(plan: list[PlanItem]) -> list[PlanItem]:
    """消除先后依赖：若 A 的目标正好是 B 现在的名字，必须先把 B 改走。

    没有依赖的保持原顺序；万一出现环（比如两个文件互换名字），保持原顺序，
    由 execute() 的同名保护兜底——最坏情况是跳过，不会丢文件。
    """
    by_src = {_key(p.src): p for p in plan}
    remaining = list(plan)
    out: list[PlanItem] = []
    done: set[str] = set()

    changed = True
    while remaining and changed:
        changed = False
        for p in list(remaining):
            blocker = by_src.get(_key(p.dst))
            if blocker is None or blocker is p or _key(blocker.src) in done:
                out.append(p)
                done.add(_key(p.src))
                remaining.remove(p)
                changed = True
    out.extend(remaining)
    return out


# --------------------------------------------------------------------------
# 执行
# --------------------------------------------------------------------------

def execute(
    plan: Sequence[PlanItem],
    *,
    policy: str = POLICY_RENAME,
    journal: Journal | None = None,
    action: str = "archive",
    note: str = "",
) -> ExecResult:
    """执行规划。逐条容错，任何一条失败都不影响其它条目。"""
    res = ExecResult()

    for item in plan:
        if item.status == STATUS_SKIP:
            res.skipped += 1
            continue
        if item.status == STATUS_CONFLICT:
            res.failed += 1
            res.errors.append(f"{item.src.name}：{item.message}")
            continue

        src, dst = item.src, item.dst
        try:
            if not src.exists():
                raise FileNotFoundError("源文件已不存在")
            if _key(src) == _key(dst):
                res.skipped += 1
                continue

            dst.parent.mkdir(parents=True, exist_ok=True)

            if dst.exists():
                if policy == POLICY_SKIP:
                    res.skipped += 1
                    continue
                if policy == POLICY_OVERWRITE and dst.is_file() and src.is_file():
                    os.replace(src, dst)
                    res.ok += 1
                    res.moves.append((str(src), str(dst)))
                    continue
                dst = unique_path(dst)
                item.dst = dst

            if src.is_dir():
                shutil.move(str(src), str(dst))
            else:
                shutil.move(str(src), str(dst))

            res.ok += 1
            res.moves.append((str(src), str(dst)))
        except Exception as exc:  # noqa: BLE001 - 单条失败不阻断
            res.failed += 1
            res.errors.append(f"{src.name}：{exc}")

    if journal is not None and res.moves:
        journal.record(action, res.moves, note)

    return res


def undo_batch(
    journal: Journal,
    batch_id: str | None = None,
    *,
    cleanup_dirs: Path | None = None,
) -> ExecResult:
    """回滚一个批次（默认最近一个未撤销的批次）。

    cleanup_dirs 传入根目录时，回滚后会把因此变空的分类文件夹一起删掉。
    """
    res = ExecResult()
    batch = None
    if batch_id:
        batch = next((b for b in journal.batches if b.id == batch_id), None)
    else:
        batch = journal.last_undoable()

    if batch is None:
        res.errors.append("没有可撤销的操作")
        return res

    candidates: set[Path] = set()
    for mv in reversed(batch.moves):
        src, dst = Path(mv.dst), Path(mv.src)  # 反向
        try:
            if not src.exists():
                res.skipped += 1
                continue
            if dst.exists():
                dst = unique_path(dst)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            res.ok += 1
            candidates.add(src.parent)
        except Exception as exc:  # noqa: BLE001
            res.failed += 1
            res.errors.append(f"{src.name}：{exc}")

    if res.ok:
        journal.mark_undone(batch.id)
        if cleanup_dirs is not None:
            res.cleaned = _remove_empty_dirs(candidates, Path(cleanup_dirs))
    return res


def _remove_empty_dirs(candidates: set[Path], root: Path) -> int:
    """删除因此变空的文件夹（只删根目录之内、且不是根本身的空目录）。"""
    removed = 0
    for d in sorted(candidates, key=lambda p: len(p.parts), reverse=True):
        try:
            if _key(d) == _key(root) or not is_within(root, d):
                continue
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
                removed += 1
        except OSError:
            continue
    return removed


# --------------------------------------------------------------------------
# 回收站
# --------------------------------------------------------------------------

class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("wFunc", ctypes.c_uint),
        ("pFrom", ctypes.c_wchar_p),
        ("pTo", ctypes.c_wchar_p),
        ("fFlags", ctypes.c_uint16),
        ("fAnyOperationsAborted", ctypes.c_int),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.c_wchar_p),
    ]


def recycle(paths: Iterable[Path]) -> tuple[bool, str]:
    """把文件/文件夹丢进回收站（可还原）。返回 (是否成功, 说明)。"""
    items = [str(p) for p in paths]
    if not items:
        return True, "没有选中条目"
    missing = [p for p in items if not Path(p).exists()]
    items = [p for p in items if Path(p).exists()]
    if not items:
        return False, "选中的条目都已不存在"

    FO_DELETE = 3
    FOF_ALLOWUNDO = 0x40
    FOF_NOCONFIRMATION = 0x10
    FOF_SILENT = 0x04
    FOF_NOERRORUI = 0x400

    op = _SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = "\0".join(items) + "\0\0"
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI

    try:
        code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    except Exception as exc:  # noqa: BLE001
        return False, f"调用系统接口失败：{exc}"

    if code != 0:
        return False, f"系统返回错误码 {code}"
    msg = f"已移入回收站 {len(items)} 项"
    if missing:
        msg += f"（{len(missing)} 项已不存在，忽略）"
    return True, msg
