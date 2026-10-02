"""配置读写：config.json 与 data 目录。"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .categorizer import CATEGORY_ORDER, DEFAULT_TARGETS

APP_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = APP_DIR / "config.json"
DATA_DIR = APP_DIR / "data"
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

    # ---------- 读写 ----------

    @staticmethod
    def load() -> "Config":
        cfg = Config(desktop_dir=str(known_desktop()))
        if CONFIG_PATH.is_file():
            try:
                raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
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
        return cfg

    def save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "desktop_dir": self.desktop_dir,
            "conflict_policy": self.conflict_policy,
            "show_hidden": self.show_hidden,
            "recursive": self.recursive,
            "rules": [r.as_dict() for r in self.rules],
        }
        tmp = CONFIG_PATH.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(CONFIG_PATH)

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
