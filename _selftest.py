"""无界面自测：在临时目录里跑通 扫描 -> 归档 -> 撤销 -> 重命名 -> 撤销。"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
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
    print("\n3) 同名冲突处理：往名字后面直接加数字")
    (sandbox / "报告.docx").write_text("new", encoding="utf-8")
    entries2 = scan(sandbox)
    plan2 = plan_archive(entries2, {"文档": "文档"}, sandbox, POLICY_RENAME)
    tgt = [p for p in plan2 if p.runnable]
    check(len(tgt) == 1 and tgt[0].dst.name == "报告1.docx", "归档重名自动改名 报告1.docx")
    up1 = unique_path(sandbox / "文档" / "报告.docx")
    check(up1.name == "报告1.docx", "unique_path 对已存在文件加数字")
    (sandbox / "文档" / "报告1.docx").write_text("dup", encoding="utf-8")
    up2 = unique_path(sandbox / "文档" / "报告.docx")
    check(up2.name == "报告2.docx", "unique_path 数字递增到 2")
    (sandbox / "文档" / "报告2.docx").write_text("dup", encoding="utf-8")
    check(unique_path(sandbox / "文档" / "报告.docx").name == "报告3.docx", "unique_path 继续递增到 3")
    # 名字末尾本来就是数字时不能黏在一起出歧义（2026报表 -> 2026报表1）
    (sandbox / "文档" / "2026报表.docx").write_text("a", encoding="utf-8")
    check(unique_path(sandbox / "文档" / "2026报表.docx").name == "2026报表1.docx",
          "原名以数字结尾也能正确加数字")
    # 多扩展名只动最后一段，保住 .gz
    (sandbox / "文档" / "备份.tar.gz").write_text("a", encoding="utf-8")
    check(unique_path(sandbox / "文档" / "备份.tar.gz").name == "备份.tar1.gz",
          "多扩展名 备份.tar.gz -> 备份.tar1.gz")

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

    # ---------- 6. 批量重命名：撞名自动加数字 ----------
    print("\n6) 批量重命名撞名自动加数字")
    lab = sandbox / "改名测试"
    lab.mkdir()

    def mk(name: str):
        p = lab / name
        p.write_text("x", encoding="utf-8")
        return p

    def plan_for(*names: str, **opts):
        entries = [e for e in scan(lab) if e.name in names]
        return plan_rename(entries, RenameOptions(**opts))

    # A. 目标已存在磁盘上，且那个文件不会被执行改走 -> 加数字
    mk("A.docx"); mk("B.docx")
    pa = plan_for("A.docx", "B.docx", mode="replace", find="B", replace="A")
    got = {p.src.name: p.dst.name for p in pa}
    check(got.get("A.docx") == "A.docx", "名称未变的条目保持原样")
    check(got.get("B.docx") == "A1.docx", f"撞已有文件 -> A1.docx（实际 {got.get('B.docx')}）")
    for f in ("A.docx", "B.docx"):
        (lab / f).unlink(missing_ok=True)

    # B. 本批次内两条产生同一个名字 -> 第二条加数字
    mk("报告A.docx"); mk("报告B.docx")
    pb = plan_for("报告A.docx", "报告B.docx",
                  mode="replace", find="[AB]", replace="X", use_regex=True)
    names = sorted(p.dst.name for p in pb)
    check(names == ["报告X.docx", "报告X1.docx"], f"批次内重名 -> {names}")
    for f in ("报告A.docx", "报告B.docx"):
        (lab / f).unlink(missing_ok=True)

    # C. 链式依赖：a.txt 想改成 Xa.txt，而 Xa.txt 自己也要改名 —— 必须先腾位置
    mk("a.txt"); mk("Xa.txt")
    pc = plan_for("a.txt", "Xa.txt", mode="prefix", prefix="X")
    got = {p.src.name: p.dst.name for p in pc}
    order = [p.src.name for p in pc]
    check(got.get("a.txt") == "Xa.txt", f"a.txt -> Xa.txt（实际 {got.get('a.txt')}）")
    check(got.get("Xa.txt") == "XXa.txt", f"Xa.txt -> XXa.txt（实际 {got.get('Xa.txt')}）")
    check(order.index("Xa.txt") < order.index("a.txt"), f"执行顺序先腾后占：{order}")
    for f in ("a.txt", "Xa.txt"):
        (lab / f).unlink(missing_ok=True)

    # D. 名称没变的文件不会让位，别人不能指望它腾地方
    mk("甲.txt"); mk("乙甲.txt")
    pd = plan_for("甲.txt", "乙甲.txt", mode="replace", find="乙", replace="")
    got = {p.src.name: p.dst.name for p in pd}
    check(got.get("乙甲.txt") == "甲1.txt", f"未变的文件不让位 -> 甲1.txt（实际 {got.get('乙甲.txt')}）")
    for f in ("甲.txt", "乙甲.txt"):
        (lab / f).unlink(missing_ok=True)

    # E. 真跑一遍，确认落盘结果和预览一致
    mk("报告A.docx"); mk("报告B.docx")
    pe = plan_for("报告A.docx", "报告B.docx",
                  mode="replace", find="[AB]", replace="X", use_regex=True)
    res = execute(pe, journal=journal, action="rename", note="撞名加数字")
    check(res.ok == 2 and res.failed == 0, f"实际执行 {res.ok} 项，失败 {res.failed}")
    check((lab / "报告X.docx").is_file() and (lab / "报告X1.docx").is_file(),
          "落盘结果：报告X.docx + 报告X1.docx")

    # F. 非法字符 / 空名字仍然拦截 —— 这类问题不该用加数字掩盖
    bad = plan_rename([e for e in scan(lab) if e.name == "报告X.docx"],
                      RenameOptions(mode="replace", find="报告", replace="a/b"))
    check(not bad[0].runnable and bad[0].status == "conflict", "非法字符被拦截")

    empty = plan_rename([e for e in scan(lab) if e.name == "报告X.docx"],
                        RenameOptions(mode="replace", find="报告X.docx", replace=""))
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

    # ---------- 8. 文档内容提取与内容搜索 ----------
    print("\n8) 文档内容提取与内容搜索")
    import _fixtures as fx
    from app.content_index import (
        ContentIndex,
        describe_status,
        make_snippet,
        terms_of,
    )
    from app.extract import extract, is_supported

    docs_dir = tmp / "文档样本"
    files = fx.build_all(docs_dir)

    # 9.1 各种格式都能抠出正文
    expect = {
        "docx": "桌面管理助手",
        "xlsx": "机械结构有限元分析预算",
        "pptx": "营收同比增长",
        "pdf": "Project Acceptance Report",
        "txt_utf8": "桌面整理",
        "txt_gbk": "发票归档",
        "rtf": "项目验收报告",
    }
    for key, needle in expect.items():
        r = extract(files[key])
        check(r.status == "ok" and needle in r.text,
              f"{key} 提取到「{needle}」（状态 {r.status}）")

    # RTF 的两种转义都要还原，且汉字不能被空格拆开
    rtf_text = extract(files["rtf"]).text
    check("项目验收" in rtf_text, "RTF 的 \\uNNNN 转义已还原且汉字连续")
    check("报告" in rtf_text, "RTF 的 \\'xx GBK 转义已还原")
    check("SimSun" not in rtf_text, "RTF 字体表没有泄漏进正文")

    # 9.2 坏文件不能把索引搞崩
    bad = extract(files["corrupt"])
    check(bad.status == "error", f"损坏的 docx 返回 error（实际 {bad.status}）")
    legacy = extract(files["legacy"])
    check(legacy.status == "unsupported", "老版 .doc 标记为不支持")
    check("老版 Office" in describe_status("", "", ".doc"), "老版格式有可读的原因说明")
    check(not is_supported(".doc") and is_supported(".pdf"), "格式支持判断正确")

    # 9.3 建索引
    entries = scan(docs_dir)
    idx = ContentIndex(tmp / "content_index.db")
    added, skipped, failed = idx.ensure(entries)
    check(added == 7, f"首次索引了 7 个文档（实际 {added}）")
    check(failed == 1, f"只有那个故意损坏的 docx 失败（实际 {failed}）")
    check("损坏的.docx" in {Path(k).name for k in
                            [r[0] for r in idx._conn.execute("SELECT path FROM docs WHERE status='error'")]},
          "损坏的文件被记成 error 而不是让整轮索引中断")

    # 9.4 增量：内容没变就不重复提取
    added2, skipped2, _ = idx.ensure(scan(docs_dir))
    check(added2 == 0 and skipped2 >= 7, f"第二次索引全部跳过（新增 {added2}，跳过 {skipped2}）")

    # 9.5 文件被改过就要重新提取
    docx_path = files["docx"]
    time.sleep(1.05)                       # 让 mtime 确实变化（部分文件系统精度到秒）
    fx.make_docx(docx_path, ["改过之后的正文", "新增关键词：橙子计划"])
    added3, _, _ = idx.ensure(scan(docs_dir))
    check(added3 == 1, f"文件改动后重新索引 1 个（实际 {added3}）")
    check(bool(idx.search("橙子计划")), "改动后的新内容能被搜到")

    # 9.6 核心：只靠正文内容找出文档（文件名里根本没这些字）
    hits = idx.search("有限元")
    hit_names = {Path(p).name for p in hits}
    check(hit_names == {"预算表.xlsx"}, f"按正文搜「有限元」命中 {hit_names}")
    key = str(files["xlsx"]).lower()
    check(key in hits and "有限元" in hits[key][0], "命中的是内容片段而不是文件名")
    # 键必须是小写的：界面查表用的就是小写路径，不统一的话
    # C:\Users\... 这种带大写的路径永远查不中（GUI 测试抓到过这个 bug）
    check(all(k == k.lower() for k in hits), "返回的路径键统一为小写")

    hits = idx.search("海外市场")
    check({Path(p).name for p in hits} == {"季度汇报.pptx"}, "按正文搜 PPT 内容命中")

    hits = idx.search("Acceptance")
    check({Path(p).name for p in hits} == {"验收报告.pdf"}, "英文大小写不敏感地搜 PDF 内容")

    hits = idx.search("发票归档")
    check({Path(p).name for p in hits} == {"老文件.txt"}, "GBK 编码的老文件也能搜到")

    hits = idx.search("项目验收")
    check({Path(p).name for p in hits} == {"备忘.rtf"}, "RTF 内容可搜")

    # 9.7 搜不存在的词
    check(idx.search("这个词肯定不存在于任何文档") == {}, "搜不到时返回空")
    check(idx.search("   ") == {}, "空白查询返回空")

    # 9.8 多词是「都要出现」
    check(bool(idx.search("预算 有限元")), "多词 AND：两个词都在时命中")
    check(not idx.search("预算 橙子计划"), "多词 AND：只满足一个时不命中")

    # 9.9 片段与计数
    long_text = "前" * 60 + "关键命中词" + "后" * 200
    snip = make_snippet(long_text, "关键命中词")
    check("关键命中词" in snip, "片段里包含关键词")
    check(snip.startswith("…") and snip.endswith("…"), f"片段两端有省略号（{snip[:12]}…{snip[-6:]}）")
    check("\n" not in snip, "片段里的换行被压掉了")
    check(make_snippet("命中就在开头" + "尾" * 200, "命中").startswith("命中"),
          "命中在开头时不加前置省略号")
    check(terms_of("甲 乙  丙") == ["甲", "乙", "丙"], "查询词拆分正确")
    check(terms_of("  ") == [], "空白查询拆出空列表")
    check(idx.search("预算")[str(files["xlsx"]).lower()][1] == 1, "命中次数统计正确")

    # 9.10 删掉的文件不留残渣
    removed_file = files["txt_utf8"]
    removed_file.unlink()
    pruned = idx.prune(docs_dir, [e.path for e in scan(docs_dir)])
    check(pruned == 1, f"清掉了 1 条失效记录（实际 {pruned}）")
    check(idx.search("桌面整理") == {}, "已删除文件的内容不再被搜到")

    st = idx.stats()
    check(st.total >= 7 and st.ok >= 6, f"索引统计：{st}")
    idx.close()

    # ---------- 9. 配置写入隔离 ----------
    print("\n9) 配置写入隔离（防止测试/多环境覆盖真实配置）")
    from app.config import CONFIG_PATH, Config

    before = CONFIG_PATH.read_bytes() if CONFIG_PATH.is_file() else None
    cfg_file = tmp / "cfg" / "config.json"
    c = Config(desktop_dir=str(sandbox), path=cfg_file)
    c.save()
    check(cfg_file.is_file(), "配置写到了指定的路径")
    check(Config.load(cfg_file).desktop_dir == str(sandbox), "从指定路径能读回一致内容")

    # 带 BOM 的配置文件也必须能读（PowerShell / 记事本写出来就带 BOM）。
    # 读不出来的话会被 except 吞掉，用户会莫名其妙丢掉全部设置。
    bom_file = tmp / "cfg" / "bom_config.json"
    bom_file.write_bytes(b"\xef\xbb\xbf" + cfg_file.read_bytes())
    bom_cfg = Config.load(bom_file)
    check(bom_cfg.desktop_dir == str(sandbox), "带 BOM 的 config.json 仍能正确读出目录")
    check(len(bom_cfg.rules) == len(c.rules), "带 BOM 的 config.json 规则没有丢失")

    # 日志文件同理
    from app.journal import Journal as _J

    j2 = tmp / "journal_bom.json"
    j2.write_bytes(b"\xef\xbb\xbf" + (tmp / "journal.json").read_bytes())
    check(len(_J(j2).batches) >= 1, "带 BOM 的操作台账仍能读出批次")

    after = CONFIG_PATH.read_bytes() if CONFIG_PATH.is_file() else None
    check(before == after, "真实 config.json 全程未被触碰")

    # ---------- 10. 专业软件分类与自定义文件类型 ----------
    print("\n10) 专业软件分类与自定义文件类型")
    from app.categorizer import (
        CATEGORY_ORDER,
        PRO_CATEGORIES,
        CategoryMap,
        suggest_category,
    )
    from app.config import merge_missing_categories

    m = CategoryMap()
    pro_cases = {
        "零件.SLDPRT": "三维模型", "装配体.sldasm": "三维模型",
        "工程图.slddrw": "三维模型", "模型.step": "三维模型",
        "网格.stl": "三维模型", "草图.3dm": "三维模型",
        "图纸.dwg": "CAD图纸", "布局.dxf": "CAD图纸", "出图.plt": "CAD图纸",
        "分析.inp": "仿真分析", "工作台.wbpj": "仿真分析", "网格.msh": "仿真分析",
        "原理图.schdoc": "电子设计", "板子.pcbdoc": "电子设计", "打样.gtl": "电子设计",
        "海报.psd": "设计源文件", "矢量.ai": "设计源文件", "排版.indd": "设计源文件",
        "剪辑.prproj": "影音工程", "特效.aep": "影音工程", "工程.flp": "影音工程",
        "数据.mat": "科学计算", "模型.slx": "科学计算", "统计.sav": "科学计算",
    }
    wrong = {k: m.categorize(k) for k, v in pro_cases.items() if m.categorize(k) != v}
    check(not wrong, f"专业软件后缀 {len(pro_cases)} 项全部识别正确（错的：{wrong}）")
    check(m.categorize("零件.sldprt") == "三维模型", "后缀大小写不敏感")
    check(len(CATEGORY_ORDER) >= 19, f"分类数 {len(CATEGORY_ORDER)}")
    check(all(c in CATEGORY_ORDER for c in PRO_CATEGORIES), "专业分类都在分类表里")
    # 老分类不能被改坏
    check(m.categorize("论文.docx") == "文档" and m.categorize("照片.jpg") == "图片"
          and m.categorize("脚本.py") == "代码", "原有分类没有被改坏")

    # ---- 用户自定义 ----
    cm = CategoryMap(
        overrides={".psd": "我的设计稿", ".zzq": "我的设计稿", ".inp": "其他"},
        custom_categories=[{"name": "我的设计稿", "icon": "⭐"}],
    )
    check(cm.categorize("海报.psd") == "我的设计稿", "自定义后缀覆盖内置分类")
    check(cm.categorize("某某.zzq") == "我的设计稿", "自定义的新后缀生效")
    check(cm.categorize("分析.inp") == "其他", "可以把内置后缀覆盖成「其他」")
    check(cm.categorize("论文.docx") == "文档", "没覆盖的仍按内置规则")
    check(cm.is_custom("我的设计稿") and not cm.is_custom("文档"), "自定义分类标记正确")
    check("我的设计稿" in cm.categories(), "自定义分类出现在分类列表里")
    check(cm.categories()[-1] == "其他", "「其他」始终排在最后")
    check(cm.icon("我的设计稿") == "⭐" and cm.icon("文档") == "📄", "自定义图标与内置图标都对")

    overrides = cm.to_overrides(cm.effective_ext_map())
    check(overrides.get(".psd") == "我的设计稿", "差异被记录进配置")
    check(".docx" not in overrides, "与内置一致的项不入配置（否则配置会肿到几百行）")
    check(len(overrides) < 10, f"压缩后只有 {len(overrides)} 项覆盖")

    # ---- 用自定义映射扫描 ----
    custom_dir = tmp / "自定义分类测试"
    custom_dir.mkdir()
    for name in ("海报.psd", "未知.zzq", "论文.docx"):
        (custom_dir / name).write_text("x", encoding="utf-8")
    got = {e.name: e.category for e in scan(custom_dir, categorizer=cm)}
    check(got.get("海报.psd") == "我的设计稿" and got.get("未知.zzq") == "我的设计稿",
          f"扫描时确实用了自定义映射（{got}）")
    plain = {e.name: e.category for e in scan(custom_dir)}
    check(plain.get("海报.psd") == "设计源文件", "不传映射时仍用内置规则")
    check(plain.get("未知.zzq") == "其他", "内置表里没有的后缀归「其他」")

    # ---- 从注册表记录猜分类 ----
    check(suggest_category(".zzz", "SolidWorks Part Document", "SLDWORKS.exe") == "三维模型",
          "按类型名关键词猜出三维模型")
    check(suggest_category(".zzz", "Ansys 2024 R1 .inp File", "RunWB2.exe") == "仿真分析",
          "按类型名关键词猜出仿真分析")
    check(suggest_category(".zzz", "Adobe Photoshop Image", "Photoshop.exe") == "设计源文件",
          "按程序名关键词猜出设计源文件")
    check(suggest_category(".zzz", "某个无关类型", "notepad.exe") == "", "猜不出时返回空串")
    check(suggest_category(".dwg", "", "") == "CAD图纸", "扩展名精确命中优先于关键词")

    # ---- 规则表要包含自定义分类 ----
    rules = merge_missing_categories([], cm.categories())
    cats_in_rules = {r.category for r in rules}
    check("我的设计稿" in cats_in_rules, "自定义分类也会生成归档规则")
    check("文件夹" not in cats_in_rules, "「文件夹」不生成归档规则")
    check(len(rules) == len(cm.categories()) - 1, "规则数 = 分类数 - 1（去掉文件夹）")

    # ---- 注册表发现（仅 Windows）----
    from app import winfiletypes

    if winfiletypes.available():
        found = winfiletypes.discover()
        check(len(found) > 100, f"从注册表发现 {len(found)} 种本机文件类型")
        check(all(i.ext.startswith(".") and i.ext == i.ext.lower() for i in found),
              "扩展名统一成小写带点")
        short = [i for i in found if "~" in i.app]
        check(not short, f"8.3 短名已展开成长名（残留 {len(short)} 个）")
        check(len([i for i in found if i.app]) > 50,
              f"{len([i for i in found if i.app])} 种能定位到关联程序")
        check(len([i for i in found if i.type_name]) > 50,
              f"{len([i for i in found if i.type_name])} 种有人可读的类型名")
        # 本机装的专业软件应该被认出来
        by_ext = {i.ext: i for i in found}
        sw = by_ext.get(".sldprt")
        if sw is not None:
            check("SOLIDWORKS" in (sw.type_name + sw.app).upper()
                  or "SW" in sw.app.upper(),
                  f"识别出 SolidWorks 的 .sldprt（{sw.type_name or sw.app}）")
            check(suggest_category(".sldprt", sw.type_name, sw.app) == "三维模型",
                  "本机 .sldprt 被建议归入三维模型")
        pro_count = sum(
            1 for i in found
            if suggest_category(i.ext, i.type_name, i.app) in PRO_CATEGORIES
        )
        check(pro_count > 20, f"其中 {pro_count} 种能猜出专业分类")
    else:
        print("     （非 Windows，跳过注册表发现测试）")

    # ---- 递归扫描与数量上限 ----
    from app.scanner import scan_with_meta

    deep_root = tmp / "递归测试"
    (deep_root / "a" / "b" / "c").mkdir(parents=True)
    for i in range(5):
        (deep_root / f"顶层{i}.txt").write_text("x", encoding="utf-8")
        (deep_root / "a" / f"一层{i}.txt").write_text("x", encoding="utf-8")
        (deep_root / "a" / "b" / f"二层{i}.txt").write_text("x", encoding="utf-8")
    for i in range(20):
        (deep_root / "a" / "b" / "c" / f"深层{i}.txt").write_text("x", encoding="utf-8")

    check(len(scan(deep_root)) == 6, f"不递归只扫顶层 6 项（实际 {len(scan(deep_root))}）")
    full = scan(deep_root, recursive=True, include_dirs=False)
    check(len(full) == 35, f"递归拿到全部 35 个文件（实际 {len(full)}）")

    capped = scan_with_meta(deep_root, recursive=True, include_dirs=False, max_items=12)
    check(len(capped.entries) == 12 and capped.truncated,
          f"数量上限生效且被标记为截断（{len(capped.entries)} 项，truncated={capped.truncated}）")
    names = {e.name for e in capped.entries}
    check(all(f"顶层{i}.txt" in names for i in range(5)),
          "浅层文件优先进入结果（截断后最先丢的是深层文件）")
    check(not any(n.startswith("深层") for n in names), "深层文件先被截掉")

    over = scan_with_meta(deep_root, recursive=True, include_dirs=False, max_items=1000)
    check(not over.truncated, "没到上限时不标记截断")

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
