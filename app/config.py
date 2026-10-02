"""配置读写：config.json 与 data 目录。"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .categorizer import CATEGORY_ORDER, DEFAULT_TARGETS

APP_DIR = Path(__file__).resolve().parent.parent

# 打包成 exe 之后，__file__ 指向的是 PyInstaller 的临时解包目录，
# 每次运行都不一样、而且只读，绝不能拿来存配置。
#   源码运行 -> 数据放项目目录（开发和测试都方便）
#   冻结运行 -> 数据放 %APPDATA%\桌面管理助手\
IS_FROZEN = bool(getattr(sys, "frozen", False))


def _data_root() -> Path:
    if not IS_FROZEN:
        return APP_DIR
    base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
    if base and Path(base).is_dir():
        return Path(base) / "桌面管理助手"
    return Path.home() / "桌面管理助手"


DATA_ROOT = _data_root()
CONFIG_PATH = DATA_ROOT / "config.json"
DATA_DIR = DATA_ROOT / "data"
JOURNAL_PATH = DATA_DIR / "undo_journal.json"

# 默认不参与归档的分类（交给用户按需打开）
DEFAULT_DISABLED = {"快捷方式", "文件夹", "其他"}


def known_desktop() -> Path:
    """取当前用户的桌面目录（先查注册表，兼容 OneDrive 重定向）。"""
    try:
        import winreg  # type: ignore

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        )
        with key:
            raw, _typ = winreg.QueryValueEx(key, "Desktop")
        expanded = os.path.expandvars(raw)
        p = Path(expanded)
        if p.is_dir():
            return p
    except Exception:
        pass

    for env in ("USERPROFILE", "HOME"):
        base = os.environ.get(env)
        if base:
            p = Path(base) / "Desktop"
            if p.is_dir():
                return p
    return Path(os.environ.get("USERPROFILE", "C:\\")) / "Desktop"


@dataclass
class ArchiveRule:
    """一条归档规则：把某分类的文件移动到桌面下的某个二级文件夹。"""

    category: str
    target: str
    enabled: bool = True

    def as_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "ArchiveRule":
        cat = str(d.get("category", "其他"))
        return ArchiveRule(
            category=cat,
            target=str(d.get("target") or DEFAULT_TARGETS.get(cat, cat)),
            enabled=bool(d.get("enabled", True)),
        )


def default_rules() -> list[ArchiveRule]:
    rules: list[ArchiveRule] = []
    for cat in CATEGORY_ORDER:
        if cat == "文件夹":
            continue
        rules.append(
            ArchiveRule(
                category=cat,
                target=DEFAULT_TARGETS.get(cat, cat),
                enabled=cat not in DEFAULT_DISABLED,
            )
        )
    return rules


@dataclass
class Config:
    desktop_dir: str = ""
    rules: list[ArchiveRule] = field(default_factory=default_rules)
    conflict_policy: str = "rename"  # rename | skip | overwrite
    show_hidden: bool = False
    recursive: bool = False
    content_search: bool = False     # 是否默认开启「搜索文件内容」
    # 这份配置是从哪个文件读出来的，保存时就写回哪里。
    # 不能写死全局路径：否则测试、多套配置会互相覆盖。
    path: Path = field(default_factory=lambda: CONFIG_PATH, repr=False, compare=False)

    # ---------- 读写 ----------

    @staticmethod
    def load(path: Path | str | None = None) -> "Config":
        cfg_path = Path(path) if path is not None else CONFIG_PATH
        cfg = Config(desktop_dir=str(known_desktop()), path=cfg_path)
        if cfg_path.is_file():
            try:
                # utf-8-sig：PowerShell / 记事本写出来的 JSON 常带 BOM，
                # 用 utf-8 读会把 BOM 留成 \ufeff 前缀导致解析失败，
                # 然后被下面的 except 吞掉 —— 用户会莫名其妙丢掉全部设置。
                raw = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
            except Exception:
                raw = {}
            desktop = raw.get("desktop_dir")
            if desktop and Path(desktop).is_dir():
                cfg.desktop_dir = str(desktop)
            rules_raw = raw.get("rules")
            if isinstance(rules_raw, list) and rules_raw:
                cfg.rules = [
                    ArchiveRule.from_dict(r) for r in rules_raw if isinstance(r, dict)
                ]
                cfg.rules = _merge_missing_categories(cfg.rules)
            pol = raw.get("conflict_policy")
            if pol in ("rename", "skip", "overwrite"):
                cfg.conflict_policy = pol
            cfg.show_hidden = bool(raw.get("show_hidden", False))
            cfg.recursive = bool(raw.get("recursive", False))
            cfg.content_search = bool(raw.get("content_search", False))
        return cfg

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "desktop_dir": self.desktop_dir,
            "conflict_policy": self.conflict_policy,
            "show_hidden": self.show_hidden,
            "recursive": self.recursive,
            "content_search": self.content_search,
            "rules": [r.as_dict() for r in self.rules],
        }
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(self.path)

    # ---------- 便捷访问 ----------

    @property
    def root(self) -> Path:
        return Path(self.desktop_dir)

    def rule_map(self) -> dict[str, ArchiveRule]:
        return {r.category: r for r in self.rules}

    def enabled_targets(self) -> dict[str, str]:
        """分类 -> 目标二级文件夹名，仅包含已启用的规则。"""
        out: dict[str, str] = {}
        for r in self.rules:
            target = (r.target or "").strip().strip("\\/")
            if r.enabled and target:
                out[r.category] = target
        return out


def _merge_missing_categories(rules: list[ArchiveRule]) -> list[ArchiveRule]:
    """配置缺了新版本的分类时补齐，顺序按 CATEGORY_ORDER 归一。"""
    have = {r.category for r in rules}
    for r in default_rules():
        if r.category not in have:
            rules.append(r)
    order = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    rules.sort(key=lambda r: order.get(r.category, 999))
    return rules
