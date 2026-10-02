"""端到端集成测试：通过真实界面对象完成 扫描 -> 归档 -> 撤销 -> 重命名 -> 回收站。

所有操作都在临时沙箱目录里进行，不碰真实桌面。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app.config import Config  # noqa: E402
from app.fileops import RenameOptions, plan_rename, execute  # noqa: E402
from app.journal import Journal  # noqa: E402
from app.ui.archive_dialog import ArchiveDialog  # noqa: E402
from app.ui.main_window import MainWindow, apply_theme  # noqa: E402
from app.ui.rename_dialog import RenameDialog  # noqa: E402

FAILED: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("  [OK]   " if cond else "  [FAIL] ") + label)
    if not cond:
        FAILED.append(label)


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app)

    # 自动确认所有弹窗
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)

    tmp = Path(tempfile.mkdtemp(prefix="desk_mgr_gui_"))
    sandbox = tmp / "Desktop"
    sandbox.mkdir()
    for name in ("甲.docx", "乙.docx", "丙.pdf", "丁.xlsx", "戊.jpg",
                 "己.zip", "庚.lnk", "辛.txt"):
        (sandbox / name).write_text("data-" + name, encoding="utf-8")
    (sandbox / "项目资料").mkdir()
    (sandbox / "项目资料" / "内部.docx").write_text("keep", encoding="utf-8")

    cfg = Config(
        desktop_dir=str(sandbox),
        rules=Config().rules,
        path=tmp / "config.json",  # 关键：配置写回沙箱，不碰真实 config.json
    )
    journal = Journal(tmp / "journal.json")

    print("1) 主窗口扫描沙箱目录")
    win = MainWindow(cfg, journal)
    check(len(win.entries) == 9, f"扫描到 9 项（实际 {len(win.entries)}）")
    check(win.proxy.rowCount() == 9, "表格初始显示全部")
    check(win.btn_rename.isEnabled() is False, "未选中时重命名按钮禁用")

    win.table.selectAll()
    check(len(win.selected_entries()) == 9, "全选得到 9 项")
    check(win.btn_rename.isEnabled() is True, "选中后重命名按钮启用")

    print("\n2) 通过归档对话框执行归档")
    dlg = ArchiveDialog(cfg, win.entries, journal, win)
    runnable = [p for p in dlg.plan if p.runnable]
    # 文档: 甲.docx/乙.docx/辛.txt + PDF + 表格 + 图片 + 压缩包 = 7
    check(len(runnable) == 7, f"预览出 7 项待归档（实际 {len(runnable)}）")
    check(dlg.btn_run.isEnabled(), "执行按钮可用")
    dlg.run_archive()
    check(dlg.executed == 7, f"对话框报告执行 7 项（实际 {dlg.executed}）")
    check((sandbox / "文档" / "甲.docx").is_file(), "甲.docx 已归档到 文档/")
    check((sandbox / "文档" / "辛.txt").is_file(), "辛.txt 已归档到 文档/")
    check((sandbox / "PDF" / "丙.pdf").is_file(), "丙.pdf 已归档到 PDF/")
    check((sandbox / "表格" / "丁.xlsx").is_file(), "丁.xlsx 已归档到 表格/")
    check((sandbox / "图片" / "戊.jpg").is_file(), "戊.jpg 已归档到 图片/")
    check((sandbox / "压缩包" / "己.zip").is_file(), "己.zip 已归档到 压缩包/")
    check((sandbox / "庚.lnk").is_file(), "未启用分类的 庚.lnk 留在桌面")
    check((sandbox / "项目资料" / "内部.docx").is_file(), "子文件夹内容未被动")

    print("\n3) 主窗口重新扫描 + 撤销")
    win.rescan()
    check(len(win.entries) == 7, f"归档后桌面剩 7 项（5 个新文件夹 + 2 个未归档项，实际 {len(win.entries)}）")
    check(win.btn_undo.isEnabled() is True, "撤销按钮变为可用")
    win.undo_last()
    check((sandbox / "甲.docx").is_file(), "撤销后 甲.docx 回到桌面")
    check((sandbox / "丙.pdf").is_file(), "撤销后 丙.pdf 回到桌面")
    check(not (sandbox / "文档" / "甲.docx").exists(), "文档/ 里的副本已移回")
    check(not (sandbox / "文档").exists(), "撤销后空的 文档/ 文件夹被清理")
    check(not (sandbox / "PDF").exists(), "撤销后空的 PDF/ 文件夹被清理")
    check((sandbox / "项目资料").is_dir(), "用户自己的文件夹不会被误删")
    check(win.journal.last_undoable() is None, "撤销后无剩余可撤销批次")
    win.rescan()
    check(len(win.entries) == 9, f"撤销后回到 9 项（实际 {len(win.entries)}）")

    print("\n4) 通过重命名对话框批量改名")
    win.rescan()
    win.search.setText("docx")
    docx_entries = win.visible_entries()
    win.search.setText("")
    check(len(docx_entries) == 2, f"筛出 2 个 docx（实际 {len(docx_entries)}）")

    rdlg = RenameDialog(docx_entries, journal, win)
    rdlg.mode_box.setCurrentIndex(3)  # 自动编号
    rdlg.num_base.setText("报告")
    rdlg.num_digits.setValue(2)
    rdlg.refresh_preview()
    check(rdlg.btn_run.isEnabled(), "编号模式预览可执行")
    preview_names = [rdlg.preview.item(r, 2).text() for r in range(rdlg.preview.rowCount())]
    print(f"     预览新名：{preview_names}")
    rdlg.run_rename()
    check(rdlg.executed == 2, f"改名 2 项（实际 {rdlg.executed}）")
    check((sandbox / "报告01.docx").is_file(), "报告01.docx 生成")

    print("\n5) 撤销重命名")
    win.rescan()
    win.undo_last()
    check((sandbox / "甲.docx").is_file(), "撤销后恢复 甲.docx")

    print("\n6) 移入回收站的防护")
    win.rescan()
    win.table.clearSelection()
    before = tuple(sorted(p.name for p in sandbox.iterdir()))
    win.delete_selected()  # 没有选中 -> 应该什么都不做
    after = tuple(sorted(p.name for p in sandbox.iterdir()))
    check(before == after, "未选中时删除不做任何事")

    win.rescan()
    target = next(e for e in win.entries if e.name == "辛.txt")
    win.table.selectRow(win.proxy.mapFromSource(win.model.index(
        win.model.entries().index(target), 0)).row())
    check([e.name for e in win.selected_entries()] == ["辛.txt"], "精确定位到 辛.txt")
    win.delete_selected()
    check(not (sandbox / "辛.txt").exists(), "辛.txt 已离开桌面（进回收站）")

    win.close()
    shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 46)
    if FAILED:
        print(f"失败 {len(FAILED)} 项：")
        for f in FAILED:
            print("  - " + f)
        return 1
    print("集成测试全部通过 ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
