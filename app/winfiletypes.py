"""从 Windows 注册表发现本机已安装软件注册过的文件类型。

Windows 上每个"我能打开这种文件"的声明都落在注册表里：
    HKEY_CLASSES_ROOT\.dwg            -> 默认值 = ProgID
    HKEY_CLASSES_ROOT\.dwg\OpenWithProgids -> 另外几个 ProgID
    HKEY_CLASSES_ROOT\<ProgID>        -> 默认值 = 人可读的类型名
    HKEY_CLASSES_ROOT\<ProgID>\shell\open\command -> "C:\...\acad.exe" "%1"

所以不用去猜哪些专业软件装了，直接问注册表就行。

非 Windows 平台或读不到注册表时返回空列表，不影响程序其它部分。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

try:
    import ctypes
    import winreg  # type: ignore
except ImportError:  # 非 Windows
    winreg = None
    ctypes = None

# 打开注册表时不要因为权限问题抛异常
_ACCESS = 0x20019 if winreg else 0  # KEY_READ

_EXE_RE = re.compile(r'"([^"]+\.exe)"|^([^\s]+\.exe)', re.IGNORECASE)
_RESOURCE_RE = re.compile(r"^@[^,]+,-?\d+$")
_SHORT_NAME_RE = re.compile(r"~[0-9]")


@dataclass
class DiscoveredType:
    """本机注册的一个文件类型。"""

    ext: str
    type_name: str = ""
    progid: str = ""
    app: str = ""            # 关联程序的 exe 文件名，如 SLDWORKS.exe
    app_path: str = ""
    sources: list[str] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        if self.type_name:
            return self.type_name
        if self.app:
            return self.app
        return self.progid or "未知类型"


def available() -> bool:
    return winreg is not None


# --------------------------------------------------------------------------
# 注册表小工具
# --------------------------------------------------------------------------

def _default_value(key) -> str:
    try:
        value, _kind = winreg.QueryValueEx(key, "")
        return str(value).strip() if value else ""
    except OSError:
        return ""


def _subkeys(key) -> list[str]:
    names: list[str] = []
    i = 0
    while True:
        try:
            names.append(winreg.EnumKey(key, i))
        except OSError:
            break
        i += 1
    return names


def _value_names(key) -> list[str]:
    names: list[str] = []
    i = 0
    while True:
        try:
            name, _val, _kind = winreg.EnumValue(key, i)
        except OSError:
            break
        if name:
            names.append(name)
        i += 1
    return names


def _open(root, path: str):
    try:
        return winreg.OpenKey(root, path, 0, _ACCESS)
    except OSError:
        return None


def _long_path(path: str) -> str:
    """把 8.3 短名还原成长名（SWSHEL~1.EXE -> SWSH.EXE）。"""
    if not path or ctypes is None or not _SHORT_NAME_RE.search(path):
        return path
    try:
        buf = ctypes.create_unicode_buffer(32768)
        n = ctypes.windll.kernel32.GetLongPathNameW(path, buf, 32768)
        if n and buf.value:
            return buf.value
    except Exception:
        pass
    return path


def _parse_exe(command: str) -> tuple[str, str]:
    """从 `"C:\\...\\acad.exe" "%1"` 里抠出 exe 的完整路径和文件名。"""
    if not command:
        return "", ""
    m = _EXE_RE.search(command)
    if not m:
        return "", ""
    full = (m.group(1) or m.group(2) or "").strip()
    if not full:
        return "", ""
    full = _long_path(full)
    return full, Path(full).name


def _looks_like_resource(text: str) -> bool:
    # FriendlyTypeName 常写成 @C:\...\foo.dll,-1234，对人没意义
    return bool(_RESOURCE_RE.match(text or ""))


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def _resolve_progid(root, progid: str) -> tuple[str, str, str]:
    """ProgID -> (类型名, exe 全路径, exe 文件名)。"""
    if not progid:
        return "", "", ""
    key = _open(root, progid)
    if key is None:
        # OpenWithProgids 里常是 Applications\foo.exe 形式
        key = _open(root, rf"Applications\{progid}")
        if key is None:
            return "", "", ""
    with key:
        type_name = _default_value(key)
        if _looks_like_resource(type_name):
            type_name = ""
        cmd_key = _open(key, r"shell\open\command")
        app_path = ""
        if cmd_key is not None:
            with cmd_key:
                app_path = _default_value(cmd_key)
    full, exe = _parse_exe(app_path)
    if not type_name:
        alt = _open(root, progid + r"\FriendlyTypeName")
        if alt is not None:
            with alt:
                cand = _default_value(alt)
                if cand and not _looks_like_resource(cand):
                    type_name = cand
    return type_name, full, exe


def discover(progress=None, should_cancel=None) -> list[DiscoveredType]:
    """枚举本机注册的文件类型。

    progress: 可选回调 (已处理, 总数)
    should_cancel: 可选回调，返回 True 时提前结束
    """
    if winreg is None:
        return []

    try:
        root = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "", 0, _ACCESS)
    except OSError:
        return []

    with root:
        try:
            all_sub = _subkeys(root)
        except OSError:
            return []

        ext_keys = [k for k in all_sub if k.startswith(".") and len(k) > 1]
        total = len(ext_keys)
        found: dict[str, DiscoveredType] = {}

        for i, ext_name in enumerate(ext_keys):
            if should_cancel is not None and should_cancel():
                break
            if progress is not None:
                progress(i, total)

            ext = ext_name.lower()
            key = _open(root, ext_name)
            if key is None:
                continue
            with key:
                progids: list[str] = []
                default = _default_value(key)
                if default and not default.startswith("."):
                    progids.append(default)
                owp = _open(key, "OpenWithProgids")
                if owp is not None:
                    with owp:
                        progids.extend(_value_names(owp))

            info = found.get(ext)
            if info is None:
                info = DiscoveredType(ext=ext)
                found[ext] = info

            for progid in progids[:6]:
                type_name, app_path, app = _resolve_progid(root, progid)
                if not info.progid and progid:
                    info.progid = progid
                if not info.type_name and type_name:
                    info.type_name = type_name
                if not info.app and app:
                    info.app, info.app_path = app, app_path

        # Applications\<exe>\SupportedTypes 是另一处声明的"我能打开这些"
        apps_key = _open(root, "Applications")
        if apps_key is not None:
            with apps_key:
                for app_name in _subkeys(apps_key):
                    if should_cancel is not None and should_cancel():
                        break
                    st = _open(apps_key, app_name + r"\SupportedTypes")
                    if st is None:
                        continue
                    exe = app_name if app_name.lower().endswith(".exe") else ""
                    app_path = ""
                    if not exe:
                        cmd = _open(apps_key, app_name + r"\shell\open\command")
                        if cmd is not None:
                            with cmd:
                                app_path, exe = _parse_exe(_default_value(cmd))
                    with st:
                        for value_name in _value_names(st):
                            if not value_name.startswith("."):
                                continue
                            e = value_name.lower()
                            info = found.get(e)
                            if info is None:
                                info = DiscoveredType(ext=e)
                                found[e] = info
                            if exe and not info.app:
                                info.app, info.app_path = exe, app_path
                            info.sources.append(f"Applications\\{app_name}")

    result = sorted(found.values(), key=lambda d: d.ext)
    for item in result:
        item.sources = sorted(set(item.sources))
    return result
