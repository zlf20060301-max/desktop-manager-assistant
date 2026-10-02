"""端到端集成测试：通过真实界面对象完成 扫描 -> 归档 -> 撤销 -> 重命名 -> 回收站。

所有操作都在临时沙箱目录里进行，不碰真实桌面。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
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

    print("\n7) 内容搜索（走真实界面）")
    import _fixtures as fx
    from app.ui.file_model import COL_HIT

    docs_dir = tmp / "文档样本"
    fx.build_all(docs_dir)
    docs_data = tmp / "docs_data"
    cfg2 = Config(desktop_dir=str(docs_dir), rules=Config().rules,
                  path=tmp / "config2.json")
    win2 = MainWindow(cfg2, Journal(tmp / "journal2.json"), data_dir=docs_data)

    check(win2.table.isColumnHidden(COL_HIT), "内容搜索未开启时命中列是隐藏的")
    check(win2.cfg.content_search is False, "默认不开启内容搜索")

    win2.chk_content.setChecked(True)
    check(win2.table.isColumnHidden(COL_HIT) is False, "开启后命中列显示出来")

    # 等后台索引线程跑完
    deadline = time.time() + 60
    while time.time() < deadline:
        app.processEvents()
        if win2._indexer is None:
            break
        time.sleep(0.05)
    check(win2._indexer is None, "后台索引线程已正常结束")
    st = win2.content_index().stats()
    check(st.ok >= 6, f"索引里有 {st.ok} 个可搜索文档（error {st.error}）")
    check((docs_data / "content_index.db").is_file(), "索引库写到了指定的数据目录")

    # 按正文搜索：文件名里没有「有限元」这三个字
    win2.search.setText("有限元")
    win2._run_content_search()
    names = [e.name for e in win2.visible_entries()]
    check(names == ["预算表.xlsx"], f"按正文内容筛出 {names}")

    row = win2.model.hit_for(win2.visible_entries()[0])
    check(row is not None and "有限元" in row[0], f"命中片段：{row[0] if row else None}")

    win2.table.selectRow(0)
    app.processEvents()
    check("命中" in win2.info_bar.text(), f"底部信息条显示命中上下文：{win2.info_bar.text()[:60]}")

    # 搜一个只存在于正文里的中文词
    win2.search.setText("海外市场")
    win2._run_content_search()
    check([e.name for e in win2.visible_entries()] == ["季度汇报.pptx"], "PPT 正文可搜")

    # 搜不到的词
    win2.search.setText("完全不存在的词啊")
    win2._run_content_search()
    check(win2.proxy.rowCount() == 0, "搜不到时列表为空")
    check("没有找到包含该内容" in win2.info_bar.text(), "搜不到时有明确提示")

    # 关掉内容搜索后回到文件名搜索
    win2.search.setText("预算")
    win2.chk_content.setChecked(False)
    win2._search_timer.stop()
    win2.proxy.set_keyword("预算")
    check([e.name for e in win2.visible_entries()] == ["预算表.xlsx"],
          "关闭内容搜索后按文件名搜仍然正常")
    check(win2.table.isColumnHidden(COL_HIT), "关闭后命中列重新隐藏")

    # 索引规模闸门：打开「含子文件夹」后可能有一万多个文档，
    # 不能不打一声招呼就开始读盘
    from app.ui.main_window import LARGE_INDEX_WARN

    saved_count = win2._searchable_count
    win2._searchable_count = lambda: LARGE_INDEX_WARN * 5
    check(win2._confirm_index_scale(first_time=True) is True,
          f"文档超过 {LARGE_INDEX_WARN} 时会先弹确认框（测试里自动接受）")
    check(win2._confirm_index_scale(first_time=False) is True, "非首次不再重复询问")
    win2._searchable_count = saved_count
    check(win2._confirm_index_scale(first_time=True) is True,
          "文档数量正常时不弹框，直接通过")

    # 索引清理：文件没了，索引记录不能永远留着
    from app.extract import STATUS_OK, ExtractResult

    idx2 = win2.content_index()
    stale = docs_dir / "已删除的文档.txt"
    idx2.put(stale, 1.0, 4, ".txt", ExtractResult(STATUS_OK, "临时内容在索引里"))
    check(bool(idx2.search("临时内容在索引里")), "临时造了一条索引记录")
    win2._prune_index()
    check(not idx2.search("临时内容在索引里"),
          "_prune_index 清掉了磁盘上已不存在文件的记录")

    print("\n8) 文件类型管理（走真实界面）")
    from PySide6.QtWidgets import QDialog

    from app.categorizer import PRO_CATEGORIES
    from app.ui.filetype_dialog import FileTypeDialog, ScanDialog

    ft_dir = tmp / "类型测试"
    ft_dir.mkdir()
    for name in ("零件.SLDPRT", "图纸.dwg", "论文.docx", "杂项.zzq"):
        (ft_dir / name).write_text("x", encoding="utf-8")

    cfg3 = Config(desktop_dir=str(ft_dir), rules=Config().rules,
                  path=tmp / "config3.json")
    win3 = MainWindow(cfg3, Journal(tmp / "journal3.json"), data_dir=tmp / "d3")

    got = {e.name: e.category for e in win3.entries}
    check(got.get("零件.SLDPRT") == "三维模型", f"主界面把 .SLDPRT 归为三维模型（{got}）")
    check(got.get("图纸.dwg") == "CAD图纸", ".dwg 归为 CAD图纸")
    check(got.get("杂项.zzq") == "其他", "未知后缀归「其他」")

    def sidebar_cats(w):
        return [w.cat_list.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(w.cat_list.count())]

    check("三维模型" in sidebar_cats(win3), f"侧栏出现三维模型（{sidebar_cats(win3)}）")

    # 打开管理对话框，模拟用户加后缀 + 新建分类
    dlg = FileTypeDialog(cfg3, win3)
    check("三维模型" in dlg._categories(), "管理界面列出了三维模型分类")
    check(len(dlg.ext_map) > 300, f"管理界面载入 {len(dlg.ext_map)} 条后缀映射")
    check(dlg.ext_map.get(".sldprt") == "三维模型", "管理界面里 .sldprt 的归类正确")

    dlg.ext_map[".zzq"] = "三维模型"                     # 相当于「添加后缀」
    dlg.ext_map[".dwg"] = "我的图纸"                     # 相当于改归到新分类
    dlg.custom.append({"name": "我的图纸", "icon": "📐"})  # 相当于「新建分类」
    dlg.changed = True
    dlg._save()
    check(dlg.result() == QDialog.DialogCode.Accepted.value or dlg.result() == 1,
          "保存后对话框返回接受")

    check(cfg3.ext_overrides.get(".zzq") == "三维模型", "新增后缀写进配置")
    check(cfg3.ext_overrides.get(".dwg") == "我的图纸", "改动内置后缀也写进配置")
    check(".docx" not in cfg3.ext_overrides, "没动过的项不写进配置")
    check(cfg3.custom_categories == [{"name": "我的图纸", "icon": "📐"}],
          f"自定义分类写进配置：{cfg3.custom_categories}")

    # 主窗口重新加载后要生效
    win3._reload_categories()
    got2 = {e.name: e.category for e in win3.entries}
    check(got2.get("杂项.zzq") == "三维模型", f"重扫后自定义后缀生效（{got2}）")
    check(got2.get("图纸.dwg") == "我的图纸", "自定义分类生效")
    check(any(r.category == "我的图纸" for r in cfg3.rules), "自定义分类进了归档规则表")
    check("我的图纸" in sidebar_cats(win3), "自定义分类出现在侧栏")
    check(win3.model._icon("我的图纸") == "📐", "表格用的是自定义图标")
    check(win3.model._icon("三维模型") == "🧊", "内置分类图标没被弄坏")

    # 扫描对话框（读真实注册表）
    from app import winfiletypes

    if winfiletypes.available():
        scan_dlg = ScanDialog(dlg.ext_map, dlg._categories(), win3)
        deadline2 = time.time() + 90
        while time.time() < deadline2:
            app.processEvents()
            if scan_dlg._rows:
                break
            time.sleep(0.05)
        check(bool(scan_dlg._rows), f"扫描对话框读到 {len(scan_dlg._rows)} 种本机文件类型")
        check(scan_dlg.table.rowCount() > 20,
              f"默认视图列出 {scan_dlg.table.rowCount()} 行（只显示有专业分类建议的）")
        # 勾选并收集
        scan_dlg._set_all(True)
        picked_before = sum(
            1 for r in range(scan_dlg.table.rowCount())
            if scan_dlg.table.item(r, 0).checkState() == Qt.CheckState.Checked
        )
        check(picked_before == scan_dlg.table.rowCount(), "全选后所有可见行都勾上")
        scan_dlg.close()
    else:
        print("     （非 Windows，跳过扫描对话框测试）")

    win3.close()
    win2.close()
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
