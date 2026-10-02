"""文件分类器：按扩展名把文件归入固定分类。"""

from __future__ import annotations

from pathlib import Path

# 分类顺序同时决定界面上的显示顺序
CATEGORY_ORDER: list[str] = [
    "文档",
    "表格",
    "演示",
    "PDF",
    "图片",
    "音视频",
    "压缩包",
    "程序",
    "代码",
    "快捷方式",
    "文件夹",
    "其他",
]

# 每个分类的默认二级文件夹名（归档时使用）
DEFAULT_TARGETS: dict[str, str] = {
    "文档": "文档",
    "表格": "表格",
    "演示": "演示",
    "PDF": "PDF",
    "图片": "图片",
    "音视频": "音视频",
    "压缩包": "压缩包",
    "程序": "安装包",
    "代码": "代码",
    "快捷方式": "快捷方式",
    "其他": "其他",
}

_EXT_GROUPS: dict[str, tuple[str, ...]] = {
    "文档": (
        ".doc", ".docx", ".rtf", ".txt", ".md", ".odt", ".wps", ".pages",
        ".tex", ".epub", ".mobi", ".wpt", ".dot", ".dotx",
    ),
    "表格": (
        ".xls", ".xlsx", ".xlsm", ".csv", ".tsv", ".ods", ".et", ".numbers",
        ".ett", ".xlt", ".xltx",
    ),
    "演示": (
        ".ppt", ".pptx", ".pps", ".ppsx", ".odp", ".dps", ".key", ".dpt",
    ),
    "PDF": (".pdf",),
    "图片": (
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".ico",
        ".tif", ".tiff", ".heic", ".heif", ".psd", ".ai", ".raw", ".cr2",
        ".nef", ".arw", ".dng", ".wmf", ".emf",
    ),
    "音视频": (
        ".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".wma", ".ape",
        ".mid", ".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm",
        ".m4v", ".rmvb", ".ts", ".3gp",
    ),
    "压缩包": (
        ".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz",
        ".cab", ".iso", ".img", ".jar",
    ),
    "程序": (
        ".exe", ".msi", ".bat", ".cmd", ".ps1", ".reg", ".vbs", ".lnk",
        ".url", ".apk", ".dmg", ".appx", ".msix", ".wsf", ".inf",
    ),
    "代码": (
        ".py", ".pyw", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
        ".html", ".htm", ".css", ".scss", ".less", ".json", ".xml", ".yml",
        ".yaml", ".toml", ".ini", ".cfg", ".java", ".kt", ".c", ".cpp",
        ".cc", ".h", ".hpp", ".cs", ".go", ".rs", ".php", ".rb", ".swift",
        ".sql", ".sh", ".bash", ".vue", ".svelte", ".ipynb", ".r", ".m",
        ".lua", ".pl", ".dart", ".gradle", ".sln", ".csproj", ".vcxproj",
    ),
    "快捷方式": (".lnk", ".url"),
}

# 扩展名 -> 分类 反查表（后写的分组不覆盖先写的，保证确定性）
EXT_TO_CATEGORY: dict[str, str] = {}
for _cat, _exts in _EXT_GROUPS.items():
    for _e in _exts:
        EXT_TO_CATEGORY.setdefault(_e, _cat)

# 快捷方式优先级最高：.lnk/.url 虽然也在"程序"里列了一次，但语义上单独成类
for _e in (".lnk", ".url"):
    EXT_TO_CATEGORY[_e] = "快捷方式"


def categorize(name: str, is_dir: bool = False) -> str:
    """返回文件/文件夹所属分类。"""
    if is_dir:
        return "文件夹"
    ext = Path(name).suffix.lower()
    return EXT_TO_CATEGORY.get(ext, "其他")


def ext_of(name: str) -> str:
    """返回小写扩展名（含点）；无扩展名返回空串。"""
    return Path(name).suffix.lower()
