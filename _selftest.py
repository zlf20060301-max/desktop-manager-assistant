"""无界面自测：在临时目录里跑通 扫描 -> 归档 -> 撤销 -> 重命名 -> 撤销。"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.fileops import (  # noqa: E402
    POLICY_RENAME,
    RenameOptions,
    execute,
    plan_archive,
    plan_rename,
    undo_batch,
    unique_path,
)
from app.journal import Journal  # noqa: E402
from app.scanner import category_counts, human_size, scan  # noqa: E402

FAILED: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("  [OK]   " if cond else "  [FAIL] ") + label)
    if not cond:
        FAILED.append(label)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="desk_mgr_test_"))
    sandbox = tmp / "Desktop"
    sandbox.mkdir()
    print(f"沙箱目录：{sandbox}\n")

    samples = [
        "报告.docx", "合同.pdf", "预算表.xlsx", "讲义.pptx",
        "照片.jpg", "音乐.mp3", "素材.zip", "安装包.exe",
        "笔记.txt", "脚本.py", "爱奇艺.url", "快捷方式.lnk",
        "desktop.ini", "无扩展名文件",
    ]
    for name in samples:
        (sandbox / name).write_text("x" * 10, encoding="utf-8")
    (sandbox / "子文件夹").mkdir()
    (sandbox / "子文件夹" / "内部.docx").write_text("y", encoding="utf-8")

    # ---------- 1. 扫描 ----------
    print("1) 扫描与分类")
    entries = scan(sandbox, include_dirs=True)
    names = {e.name for e in entries}
    check("desktop.ini" not in names, "desktop.ini 被排除")
    check("报告.docx" in names and "无扩展名文件" in names, "普通文件被扫到")
    check("子文件夹" in names, "文件夹被扫到")
    by_name = {e.name: e for e in entries}
    check(by_name["报告.docx"].category == "文档", "docx -> 文档")
    check(by_name["预算表.xlsx"].category == "表格", "xlsx -> 表格")
    check(by_name["合同.pdf"].category == "PDF", "pdf -> PDF")
    check(by_name["照片.jpg"].category == "图片", "jpg -> 图片")
    check(by_name["快捷方式.lnk"].category == "快捷方式", "lnk -> 快捷方式")
    check(by_name["无扩展名文件"].category == "其他", "无扩展名 -> 其他")
    check(by_name["子文件夹"].category == "文件夹", "目录 -> 文件夹")
    counts = category_counts(entries)
    print(f"     分类统计：{counts}")
    check(human_size(0) == "0 B" and human_size(2048).endswith("KB"), "大小格式化正常")

    # ---------- 2. 归档 ----------
    print("\n2) 按规则归档")
    targets = {"文档": "文档", "PDF": "PDF", "表格": "表格", "图片": "图片"}
    plan = plan_archive(entries, targets, sandbox, POLICY_RENAME)
    runnable = [p for p in plan if p.runnable]
    # 文档x2(报告.docx/笔记.txt) + PDFx1 + 表格x1 + 图片x1 = 5
    check(len(runnable) == 5, f"规划出 5 项归档（实际 {len(runnable)}）")
    check(any(p.src.name == "讲义.pptx" and p.status != "ok" for p in plan)
          or all(p.src.name != "讲义.pptx" for p in plan), "未启用规则的分类不参与归档")
    check(all(not p.src.is_dir() for p in runnable), "文件夹不参与归档")

    journal = Journal(tmp / "journal.json")
    res = execute(plan, policy=POLICY_RENAME, journal=journal, action="archive", note="测试归档")
    check(res.ok == 5, f"归档执行成功 5 项（实际 {res.ok}，失败 {res.failed}）")
    check((sandbox / "文档" / "报告.docx").is_file(), "报告.docx 已进入 文档/")
    check((sandbox / "PDF" / "合同.pdf").is_file(), "合同.pdf 已进入 PDF/")
    check((sandbox / "文档" / "笔记.txt").is_file(), "笔记.txt 已进入 文档/")
    check(not (sandbox / "报告.docx").exists(), "桌面上的原文件已消失")
    check((sandbox / "子文件夹" / "内部.docx").is_file(), "子文件夹内的文件未被误动")
    check(journal.last_undoable() is not None, "日志记录了可撤销批次")

    # ---------- 3. 重名冲突 ----------
    print("\n3) 同名冲突处理")
    (sandbox / "报告.docx").write_text("new", encoding="utf-8")
    entries2 = scan(sandbox)
    plan2 = plan_archive(entries2, {"文档": "文档"}, sandbox, POLICY_RENAME)
    tgt = [p for p in plan2 if p.runnable]
    check(len(tgt) == 1 and tgt[0].dst.name == "报告 (1).docx", "重名自动改名 报告 (1).docx")
    up1 = unique_path(sandbox / "文档" / "报告.docx")
    check(up1.name == "报告 (1).docx", "unique_path 对已存在文件加序号")
    (sandbox / "文档" / "报告 (1).docx").write_text("dup", encoding="utf-8")
    up2 = unique_path(sandbox / "文档" / "报告.docx")
    check(up2.name == "报告 (2).docx", "unique_path 序号递增到 (2)")

    # ---------- 4. 撤销归档 ----------
    print("\n4) 撤销归档")
    res = undo_batch(journal)
    check(res.ok == 5 and res.failed == 0, f"撤销成功 5 项（实际 {res.ok}，失败 {res.failed}）")
    check((sandbox / "报告.docx").is_file(), "报告.docx 回到桌面")
    check(not (sandbox / "文档" / "笔记.txt").exists(), "笔记.txt 离开 文档/")
    check((sandbox / "子文件夹" / "内部.docx").is_file(), "子文件夹内容依旧完好")
    check(journal.last_undoable() is None, "撤销后无剩余可撤销批次")

    # ---------- 5. 批量重命名 ----------
    print("\n5) 批量重命名")
    targets_rename = [e for e in scan(sandbox) if e.name.endswith((".docx", ".txt", ".pdf"))]
    check(len(targets_rename) >= 2, f"选中 {len(targets_rename)} 个待改名文件")

    plan3 = plan_rename(targets_rename, RenameOptions(mode="prefix", prefix="2026_"))
    check(all(p.runnable for p in plan3), "前缀重命名全部可执行")
    res = execute(plan3, journal=journal, action="rename", note="测试重命名")
    check(res.ok == len(plan3), f"重命名成功 {res.ok} 项")
    check((sandbox / "2026_报告.docx").is_file(), "2026_报告.docx 存在")

    plan4 = plan_rename([e for e in scan(sandbox) if e.name.startswith("2026_")],
                        RenameOptions(mode="replace", find="2026_", replace=""))
    res = execute(plan4, journal=journal, action="rename", note="去前缀")
    check(res.ok == len(plan4), f"查找替换成功 {res.ok} 项")
    check((sandbox / "报告.docx").is_file(), "前缀已去除")

    # ---------- 6. 编号 / 冲突防护 ----------
    print("\n6) 编号与冲突防护")
    files = [e for e in scan(sandbox) if e.name.endswith(".txt")]
    plan5 = plan_rename(files, RenameOptions(mode="number", number_base="T", number_digits=3))
    check(len(plan5) == len(files), "编号方案生成条目数一致")
    if plan5:
        print(f"     示例：{plan5[0].src.name} -> {plan5[0].dst.name}")

    bad = plan_rename([e for e in scan(sandbox) if e.name == "报告.docx"],
                      RenameOptions(mode="replace", find="报告", replace="a/b"))
    check(not bad[0].runnable and bad[0].status == "conflict", "非法字符被拦截")

    empty = plan_rename([e for e in scan(sandbox) if e.name == "报告.docx"],
                        RenameOptions(mode="replace", find="报告.docx", replace=""))
    check(not empty[0].runnable, "空名称被拦截")

    # ---------- 7. 越界防护 ----------
    print("\n7) 越界防护")
    from app.fileops import is_within

    outside = tmp / "外部文件.txt"
    outside.write_text("z", encoding="utf-8")
    check(is_within(sandbox, sandbox / "文档"), "内部路径判定为在内")
    check(not is_within(sandbox, outside), "外部路径判定为越界")
    e_out = scan(tmp)
    plan6 = plan_archive([e for e in e_out if e.name == "外部文件.txt"],
                         {"文档": "文档"}, sandbox, POLICY_RENAME)
    check(all(not p.runnable for p in plan6), "外部文件不会被归档进目标目录")

    shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + "=" * 46)
    if FAILED:
        print(f"失败 {len(FAILED)} 项：")
        for f in FAILED:
            print("  - " + f)
        return 1
    print("全部通过 ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
