"""归档对话框：编辑规则 -> 预览 -> 执行。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..categorizer import CategoryMap
from ..config import Config
from ..fileops import (
    POLICY_LABELS,
    POLICY_RENAME,
    STATUS_CONFLICT,
    STATUS_OK,
    STATUS_SKIP,
    execute,
    plan_archive,
)
from ..journal import Journal
from ..scanner import Entry


class ArchiveDialog(QDialog):
    """按分类把桌面文件收进二级文件夹。"""

    def __init__(
        self,
        cfg: Config,
        entries: list[Entry],
        journal: Journal,
        parent: QWidget | None = None,
        cats: CategoryMap | None = None,
    ) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.entries = entries
        self.journal = journal
        self.cats = cats or CategoryMap.from_config(cfg)
        self.plan = []
        self.executed = 0

        self.setWindowTitle("自动归档 — 按规则整理桌面")
        self.resize(1020, 860)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # ---------- 说明 ----------
        tip = QLabel(
            "规则说明：把「分类」对应的文件移动到桌面下的二级文件夹。<br>"
            "只处理<b>直接放在桌面上的文件</b>（不含子文件夹内容、不含文件夹本身）。"
        )
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        root.addWidget(tip)

        # ---------- 规则表 ----------
        self.rule_table = QTableWidget(0, 3)
        self.rule_table.setHorizontalHeaderLabels(["分类", "目标文件夹", "启用"])
        self.rule_table.verticalHeader().setVisible(False)
        self.rule_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        hh = self.rule_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.rule_table.setColumnWidth(0, 190)
        self.rule_table.setColumnWidth(2, 70)
        self.rule_table.verticalHeader().setDefaultSectionSize(30)
        self._fill_rules()
        self.rule_table.itemChanged.connect(self._on_rule_changed)
        self.rule_table.setToolTip("双击「目标文件夹」可修改名称；取消勾选「启用」则不归档该分类。")
        root.addWidget(self.rule_table)

        # ---------- 冲突策略 ----------
        row = QHBoxLayout()
        row.addWidget(QLabel("遇到同名文件时："))
        self.policy_box = QComboBox()
        for key, label in POLICY_LABELS.items():
            self.policy_box.addItem(label, key)
        idx = self.policy_box.findData(self.cfg.conflict_policy or POLICY_RENAME)
        self.policy_box.setCurrentIndex(max(0, idx))
        row.addWidget(self.policy_box)
        row.addStretch(1)

        btn_preview = QPushButton("刷新预览")
        btn_preview.clicked.connect(self.refresh_preview)
        row.addWidget(btn_preview)
        self.btn_run = QPushButton("执行归档")
        self.btn_run.setObjectName("Primary")
        self.btn_run.clicked.connect(self.run_archive)
        row.addWidget(self.btn_run)
        root.addLayout(row)

        # ---------- 预览 ----------
        root.addWidget(self._section_label("归档预览"))
        self.preview = QTableWidget(0, 4)
        self.preview.setHorizontalHeaderLabels(["状态", "文件名", "移动到", "说明"])
        self.preview.verticalHeader().setVisible(False)
        self.preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        ph = self.preview.horizontalHeader()
        ph.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        ph.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        ph.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        ph.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.preview.setColumnWidth(0, 92)
        self.preview.setColumnWidth(2, 220)
        self.preview.setColumnWidth(3, 190)
        root.addWidget(self.preview, 3)

        # ---------- 底部按钮 ----------
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        root.addWidget(buttons)

        self.refresh_preview()

    # ------------------------------------------------------------------

    @staticmethod
    def _section_label(text: str) -> QLabel:
        lb = QLabel(text)
        lb.setObjectName("SectionTitle")
        return lb

    def _fill_rules(self) -> None:
        # 规则不多时让表格一次全部显示，不用滚动
        visible_rows = min(max(len(self.cfg.rules), 3), 12)
        self.rule_table.setFixedHeight(visible_rows * 30 + 36)

        self.rule_table.blockSignals(True)
        self.rule_table.setRowCount(len(self.cfg.rules))
        for i, rule in enumerate(self.cfg.rules):
            cat_item = QTableWidgetItem(f"{self.cats.icon(rule.category)} {rule.category}")
            cat_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.rule_table.setItem(i, 0, cat_item)
            self.rule_table.setItem(i, 1, QTableWidgetItem(rule.target))
            chk = QTableWidgetItem()
            chk.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
            )
            chk.setCheckState(
                Qt.CheckState.Checked if rule.enabled else Qt.CheckState.Unchecked
            )
            self.rule_table.setItem(i, 2, chk)
        self.rule_table.blockSignals(False)

    def _on_rule_changed(self, item: QTableWidgetItem) -> None:
        i = item.row()
        if not (0 <= i < len(self.cfg.rules)):
            return
        rule = self.cfg.rules[i]
        if item.column() == 1:
            rule.target = item.text().strip()
        elif item.column() == 2:
            rule.enabled = item.checkState() == Qt.CheckState.Checked
        self.cfg.conflict_policy = self.policy_box.currentData()
        self.cfg.save()
        self.refresh_preview()

    # ------------------------------------------------------------------

    def _collect_targets(self) -> dict[str, str]:
        return self.cfg.enabled_targets()

    def refresh_preview(self) -> None:
        targets = self._collect_targets()
        policy = self.policy_box.currentData()
        self.plan = plan_archive(self.entries, targets, self.cfg.root, policy)

        runnable = [p for p in self.plan if p.status == STATUS_OK]
        skipped = [p for p in self.plan if p.status == STATUS_SKIP]

        self.preview.setRowCount(len(self.plan))
        root_path = Path(self.cfg.desktop_dir)
        for r, item in enumerate(self.plan):
            if item.status == STATUS_OK:
                badge, color = "✔ 待处理", "#059669"
            elif item.status == STATUS_SKIP:
                badge, color = "— 跳过", "#6b7280"
            else:
                badge, color = "✖ 冲突", "#dc2626"
            try:
                rel_dst = str(item.dst.relative_to(root_path))
            except ValueError:
                rel_dst = str(item.dst)
            cells = [
                badge,
                item.src.name,
                rel_dst,
                item.message or ("将移动" if item.status == STATUS_OK else ""),
            ]
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if c == 0:
                    it.setForeground(Qt.GlobalColor.darkGreen if item.status == STATUS_OK
                                     else (Qt.GlobalColor.red if item.status == STATUS_CONFLICT
                                           else Qt.GlobalColor.gray))
                elif c == 2:
                    it.setToolTip(str(item.dst))
                self.preview.setItem(r, c, it)

        self.btn_run.setEnabled(bool(runnable))
        self.btn_run.setText(f"执行归档（{len(runnable)} 项）" if runnable else "没有可归档的文件")
        self._summary = (len(runnable), len(skipped))

    def run_archive(self) -> None:
        self.cfg.conflict_policy = self.policy_box.currentData()
        self.cfg.save()
        runnable = [p for p in self.plan if p.status == STATUS_OK]
        if not runnable:
            return

        targets: dict[str, Path] = {}
        for p in runnable:
            targets[p.dst.parent] = p.dst.parent

        preview_lines = "\n".join(
            f"  {p.src.name}  →  {p.dst.parent.name}\\" for p in runnable[:12]
        )
        if len(runnable) > 12:
            preview_lines += f"\n  …… 以及另外 {len(runnable) - 12} 个文件"

        ok = QMessageBox.question(
            self,
            "确认归档",
            f"即将移动 {len(runnable)} 个文件：\n\n{preview_lines}\n\n"
            f"涉及的目标文件夹：{len(targets)} 个\n"
            "操作可在主界面「撤销」中整批还原，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if ok != QMessageBox.StandardButton.Yes:
            return

        res = execute(
            self.plan,
            policy=self.policy_box.currentData(),
            journal=self.journal,
            action="archive",
            note=f"按分类归档 {len(runnable)} 个文件",
        )
        self.executed = res.ok

        msg = f"归档完成：{res.summary()}"
        if res.errors:
            msg += "\n\n失败明细：\n" + "\n".join(res.errors[:10])
        QMessageBox.information(self, "归档结果", msg + "\n\n可随时用主界面「撤销上一步」还原。")
        self.refresh_preview()
        if res.ok:
            self.accept()
