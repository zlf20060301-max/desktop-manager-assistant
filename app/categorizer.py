"""文件分类器：扩展名 → 分类。

分两层：
1. 内置表 —— 常见文档格式，加上专业软件（CAD / 三维 / 仿真 / EDA /
   设计 / 影音 / 科学计算）生成的文件格式。
2. 用户覆盖 —— 用户在「文件类型管理」里自己加的后缀和分类，
   优先级高于内置表。

CategoryMap 把两层合成一份可用的映射；不传就用默认映射。
"""

from __future__ import annotations

from pathlib import Path

# 分类顺序同时决定界面上的显示顺序
CATEGORY_ORDER: list[str] = [
    "文档",
    "表格",
    "演示",
    "PDF",
    "图片",
    "设计源文件",
    "音视频",
    "影音工程",
    "三维模型",
    "CAD图纸",
    "仿真分析",
    "电子设计",
    "科学计算",
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
    "设计源文件": "设计源文件",
    "音视频": "音视频",
    "影音工程": "影音工程",
    "三维模型": "三维模型",
    "CAD图纸": "CAD图纸",
    "仿真分析": "仿真分析",
    "电子设计": "电子设计",
    "科学计算": "科学计算",
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
        ".tif", ".tiff", ".heic", ".heif", ".raw", ".cr2", ".nef", ".arw",
        ".dng", ".wmf", ".emf", ".jfif", ".avif",
    ),
    # 设计软件的工程源文件：能再编辑，和导出的成品图不是一回事
    "设计源文件": (
        ".psd", ".psb", ".ai", ".ait", ".cdr", ".cmx", ".indd", ".idml",
        ".sketch", ".xd", ".fig", ".afdesign", ".afphoto", ".afpub",
        ".procreate", ".clip", ".kra", ".xcf", ".ase", ".aco", ".abr",
        ".csh", ".pat", ".aseprite", ".ora",
    ),
    "音视频": (
        ".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".wma", ".ape",
        ".mid", ".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm",
        ".m4v", ".rmvb", ".ts", ".3gp", ".opus", ".aiff", ".m4v",
    ),
    # 剪辑 / 混音的工程文件
    "影音工程": (
        ".prproj", ".aep", ".aepx", ".veg", ".vf", ".fcpxml", ".fcpproject",
        ".drp", ".flp", ".als", ".cpr", ".npr", ".logicx", ".ptx", ".ptf",
        ".rpp", ".sesx", ".aup", ".aup3", ".band", ".reason", ".song",
        ".omf", ".aaf", ".edl", ".mlt", ".kdenlive", ".veg", ".vprj",
    ),
    # 三维建模 / 交换格式
    "三维模型": (
        ".sldprt", ".sldasm", ".slddrw", ".sldftp",
        ".prt", ".asm", ".xpr", ".catpart", ".catproduct", ".catdrawing",
        ".model", ".ipt", ".iam", ".idw", ".ipn", ".3dxml", ".jt",
        ".x_t", ".x_b", ".xmt_txt", ".xmt_bin", ".sat", ".sab",
        ".step", ".stp", ".stpz", ".iges", ".igs", ".igs2",
        ".stl", ".obj", ".3mf", ".ply", ".fbx", ".dae", ".gltf", ".glb",
        ".usd", ".usda", ".usdc", ".usdz", ".abc",
        ".max", ".3ds", ".blend", ".skp", ".3dm", ".c4d", ".ma", ".mb",
        ".rvt", ".rfa", ".rte", ".ifc", ".dgn", ".3dm",
    ),
    # 二维图纸 / 工程图 / 出图相关
    "CAD图纸": (
        ".dwg", ".dxf", ".dwt", ".dws", ".dwf", ".dwfx", ".dgn",
        ".exb", ".plt", ".hpgl", ".hpg", ".ctb", ".stb", ".shx",
        ".lin", ".pat", ".scr", ".pc3", ".pmp", ".arg", ".cuix", ".mnu",
    ),
    # 有限元 / 流体 / 多物理场
    "仿真分析": (
        ".ansys", ".anf", ".inp", ".cae", ".odb", ".cdb", ".msh",
        ".cas", ".flprj", ".mph", ".sim", ".nas", ".bdf", ".fem", ".unv",
        ".rst", ".op2", ".pch", ".sif", ".wbpj", ".wbpz", ".acmo",
        ".mechdb", ".engd", ".agdb", ".res",
    ),
    # 电路 / PCB / 版图
    "电子设计": (
        ".sch", ".schdoc", ".schlib", ".pcb", ".pcbdoc", ".pcblib",
        ".brd", ".dsn", ".gbr", ".ger", ".gtl", ".gbl", ".gts", ".gbs",
        ".gto", ".gbo", ".gtp", ".gbp", ".drl", ".apr", ".prjpcb",
        ".prjsch", ".ddb", ".olb", ".kicad_pcb", ".kicad_sch",
        ".kicad_pro", ".kicad_mod", ".kicad_sym", ".fzz", ".fz", ".fzpz",
        ".ltspice", ".asc", ".cir", ".sp", ".lib",
    ),
    # 数学 / 统计软件
    "科学计算": (
        ".mat", ".slx", ".mdl", ".mlx", ".mlapp", ".mltbx", ".mldatx",
        ".nb", ".wl", ".wls", ".cdf", ".sav", ".spv", ".por",
        ".dta", ".do", ".rdata", ".rds", ".rda", ".sas7bdat", ".jmp",
        ".mwx", ".mws", ".ogwu", ".ogw", ".opju", ".opj",
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
        ".vhd", ".vhdl", ".sv", ".v",
    ),
    "快捷方式": (".lnk", ".url"),
}

# 扩展名 -> 分类 反查表。逐组写入、先到先得，保证结果与分组顺序无关且可确定。
# 注意只用单段扩展名：Path.suffix 只返回最后一段，".tar.gz" 这种永远匹配不上。
EXT_TO_CATEGORY: dict[str, str] = {}
for _cat in CATEGORY_ORDER:
    for _e in _EXT_GROUPS.get(_cat, ()):
        EXT_TO_CATEGORY.setdefault(_e, _cat)

# 快捷方式单独成类（.lnk/.url 也在"程序"里列过）
for _e in (".lnk", ".url"):
    EXT_TO_CATEGORY[_e] = "快捷方式"

# .raw 在图片（相机 RAW）和电子设计（LTspice 波形）里都有，归图片更常见
EXT_TO_CATEGORY[".raw"] = "图片"

# 专业软件分类集合，供"只看专业软件"筛选和扫描建议使用
PRO_CATEGORIES: tuple[str, ...] = (
    "设计源文件", "影音工程", "三维模型", "CAD图纸",
    "仿真分析", "电子设计", "科学计算",
)


def ext_of(name: str) -> str:
    """返回小写扩展名（含点）；无扩展名返回空串。"""
    return Path(name).suffix.lower()


# --------------------------------------------------------------------------
# 软件名 / 类型名 关键词 —— 注册表里没有扩展名记录时用来猜分类
# --------------------------------------------------------------------------

APP_HINTS: tuple[tuple[str, str], ...] = (
    # 三维建模
    ("solidworks", "三维模型"), ("sldworks", "三维模型"), ("swshell", "三维模型"),
    ("edrawings", "三维模型"), ("catia", "三维模型"), ("inventor", "三维模型"),
    ("ugraf", "三维模型"), ("siemens nx", "三维模型"), ("creo", "三维模型"),
    ("proengineer", "三维模型"), ("blender", "三维模型"), ("3dsmax", "三维模型"),
    ("3ds max", "三维模型"), ("maya", "三维模型"), ("sketchup", "三维模型"),
    ("rhino", "三维模型"), ("solid edge", "三维模型"), ("fusion", "三维模型"),
    # 二维图纸
    ("autocad", "CAD图纸"), ("acad", "CAD图纸"), ("bricscad", "CAD图纸"),
    ("zwcad", "CAD图纸"), ("gstarcad", "CAD图纸"), ("caxa", "CAD图纸"),
    ("microstation", "CAD图纸"),
    # 仿真
    ("ansys", "仿真分析"), ("workbench", "仿真分析"), ("abaqus", "仿真分析"),
    ("comsol", "仿真分析"), ("fluent", "仿真分析"), ("nastran", "仿真分析"),
    ("ls-dyna", "仿真分析"), ("hypermesh", "仿真分析"), ("adams", "仿真分析"),
    # 电子设计
    ("altium", "电子设计"), ("orcad", "电子设计"), ("kicad", "电子设计"),
    ("allegro", "电子设计"), ("pads", "电子设计"), ("protel", "电子设计"),
    ("ltspice", "电子设计"), ("multisim", "电子设计"), ("easyeda", "电子设计"),
    ("立创", "电子设计"), ("嘉立创", "电子设计"),
    # 设计源文件
    ("photoshop", "设计源文件"), ("illustrator", "设计源文件"),
    ("coreldraw", "设计源文件"), ("indesign", "设计源文件"),
    ("figma", "设计源文件"), ("sketch", "设计源文件"), ("affinity", "设计源文件"),
    # 影音工程
    ("premiere", "影音工程"), ("after effects", "影音工程"),
    ("vegas", "影音工程"), ("davinci", "影音工程"), ("resolve", "影音工程"),
    ("fl studio", "影音工程"), ("ableton", "影音工程"), ("cubase", "影音工程"),
    ("pro tools", "影音工程"), ("reaper", "影音工程"), ("audition", "影音工程"),
    ("剪映", "影音工程"), ("会声会影", "影音工程"),
    # 科学计算
    ("matlab", "科学计算"), ("simulink", "科学计算"), ("mathematica", "科学计算"),
    ("spss", "科学计算"), ("stata", "科学计算"), ("sas ", "科学计算"),
    ("origin", "科学计算"), ("jmp", "科学计算"), ("minitab", "科学计算"),
)


def suggest_category(ext: str, type_name: str = "", app: str = "") -> str:
    """给一个注册表里发现的文件类型猜分类。猜不出返回空串。

    先用扩展名精确匹配内置表，再用"类型名 / 软件名"里的关键词兜底 ——
    很多专业软件注册的类型名里会带自己的名字（如 "Ansys 2024 R1 .inp File"）。
    """
    e = (ext or "").lower()
    if not e.startswith("."):
        return ""
    known = EXT_TO_CATEGORY.get(e)
    if known and known not in ("其他", "代码"):
        return known

    haystack = f"{type_name} {app}".lower()
    if haystack.strip():
        for keyword, category in APP_HINTS:
            if keyword in haystack:
                return category

    return known or ""


# --------------------------------------------------------------------------
# 分类映射
# --------------------------------------------------------------------------

DEFAULT_ICON = "🗂️"


class CategoryMap:
    """内置分类表 + 用户自定义覆盖，合成一份可用的映射。"""

    def __init__(
        self,
        overrides: dict[str, str] | None = None,
        custom_categories: list[dict] | None = None,
    ) -> None:
        self._user_ext: dict[str, str] = {}
        for ext, cat in (overrides or {}).items():
            e = str(ext).lower().strip()
            if not e.startswith("."):
                e = "." + e
            cat = str(cat).strip()
            if e and cat:
                self._user_ext[e] = cat

        self._custom: list[tuple[str, str]] = []
        seen: set[str] = set()
        for item in custom_categories or []:
            if isinstance(item, dict):
                name = str(item.get("name", "")).strip()
                icon = str(item.get("icon", "")).strip() or DEFAULT_ICON
            else:
                name, icon = str(item).strip(), DEFAULT_ICON
            if name and name not in seen and name not in CATEGORY_ORDER:
                seen.add(name)
                self._custom.append((name, icon))
        self._custom_icons = dict(self._custom)

    # ---------- 构造 ----------

    @classmethod
    def from_config(cls, cfg) -> "CategoryMap":
        return cls(
            overrides=getattr(cfg, "ext_overrides", None),
            custom_categories=getattr(cfg, "custom_categories", None),
        )

    # ---------- 查询 ----------

    def categorize(self, name: str, is_dir: bool = False) -> str:
        if is_dir:
            return "文件夹"
        ext = ext_of(name)
        if not ext:
            return "其他"
        user = self._user_ext.get(ext)
        if user is not None:
            return user
        return EXT_TO_CATEGORY.get(ext, "其他")

    def categories(self) -> list[str]:
        """全部可选分类（内置顺序，自定义排在内置最后一项之前）。"""
        builtin = list(CATEGORY_ORDER)
        if not self._custom:
            return builtin
        out = [c for c in builtin if c != "其他"]
        out.extend(name for name, _ in self._custom)
        out.append("其他")
        return out

    def builtin_categories(self) -> list[str]:
        return list(CATEGORY_ORDER)

    def custom_categories(self) -> list[tuple[str, str]]:
        return list(self._custom)

    def is_custom(self, category: str) -> bool:
        return category in self._custom_icons

    def icon(self, category: str) -> str:
        from .icons import icon_for

        return self._custom_icons.get(category) or icon_for(category)

    def effective_ext_map(self) -> dict[str, str]:
        """完整映射：内置 + 用户覆盖。管理界面编辑的就是它。"""
        merged = dict(EXT_TO_CATEGORY)
        merged.update(self._user_ext)
        return merged

    def exts_of(self, category: str) -> list[str]:
        return sorted(e for e, c in self.effective_ext_map().items() if c == category)

    # ---------- 导出 ----------

    def to_overrides(self, edited: dict[str, str]) -> dict[str, str]:
        """把编辑后的完整映射压成"只记录与内置不同的部分"，避免配置文件臃肿。"""
        out: dict[str, str] = {}
        for ext, cat in edited.items():
            e = str(ext).lower().strip()
            if not e.startswith("."):
                e = "." + e
            cat = str(cat).strip() or "其他"
            if EXT_TO_CATEGORY.get(e) != cat:
                out[e] = cat
        return dict(sorted(out.items()))

    def user_overrides(self) -> dict[str, str]:
        return dict(self._user_ext)


# 默认映射：给不关心自定义的调用方（以及测试）用
DEFAULT_MAP = CategoryMap()


def categorize(name: str, is_dir: bool = False) -> str:
    """按默认映射分类。需要用户自定义时用 CategoryMap.categorize。"""
    return DEFAULT_MAP.categorize(name, is_dir)
