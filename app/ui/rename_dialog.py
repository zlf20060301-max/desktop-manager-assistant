"""批量重命名对话框：配置规则 -> 预览 -> 执行。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..fileops import (
    POLICY_SKIP,
    STATUS_CONFLICT,
    STATUS_OK,
    STATUS_SKIP,
    RenameOptions,
    execute,
    plan_rename,
)
from ..journal import Journal
from ..scanner import Entry

MODE_ITEMS = [
    ("查找并替换", "replace"),
    ("添加前缀", "prefix"),
    ("添加后缀", "suffix"),
    ("自动编号", "number"),
    ("修改大小写", "case"),
]


class RenameDialog(QDialog):
    """对选中条目做批量改名，执行前给完整预览。"""

    def __init__(
        self,
        entries: list[Entry],
        journal: Journal,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.entries = entries
        self.journal = journal
        self.plan = []
        self.executed = 0

        self.setWindowTitle(f"批量重命名 — 共 {len(entries)} 项")
        # 高度跟着条目数走，选得少时不留大片空白
        self.resize(980, min(840, 420 + min(len(entries), 14) * 30))

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        top = QHBoxLayout()
        top.addWidget(QLabel("重命名方式："))
        self.mode_box = QComboBox()
        for label, key in MODE_ITEMS:
            self.mode_box.addItem(label, key)
        self.mode_box.setMinimumWidth(160)
        self.mode_box.currentIndexChanged.connect(self._on_mode_changed)
        top.addWidget(self.mode_box)
        top.addStretch(1)
        root.addLayout(top)

        # ---------- 参数区 ----------
        self.stack = QStackedWidget()
        self.stack.addWidget(self._page_replace())
        self.stack.addWidget(self._page_prefix())
        self.stack.addWidget(self._page_suffix())
        self.stack.addWidget(self._page_number())
        self.stack.addWidget(self._page_case())
        root.addWidget(self.stack)

        # ---------- 预览 ----------
        title = QLabel("预览（灰色=不处理，重名会自动在名字后面加数字）")
        title.setObjectName("SectionTitle")
        root.addWidget(title)

        self.preview = QTableWidget(0, 4)
        self.preview.setHorizontalHeaderLabels(["状态", "原名称", "新名称", "说明"])
        self.preview.verticalHeader().setVisible(False)
        self.preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        ph = self.preview.horizontalHeader()
        ph.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        ph.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        ph.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        ph.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.preview.setColumnWidth(0, 92)
        self.preview.setColumnWidth(3, 210)
        root.addWidget(self.preview, 1)

        # ---------- 底部 ----------
        bottom = QHBoxLayout()
        btn_refresh = QPushButton("刷新预览")
        btn_refresh.clicked.connect(self.refresh_preview)
        bottom.addWidget(btn_refresh)
        bottom.addStretch(1)
        self.btn_run = QPushButton("执行重命名")
        self.btn_run.setObjectName("Primary")
        self.btn_run.clicked.connect(self.run_rename)
        bottom.addWidget(self.btn_run)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.reject)
        box.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        bottom.addWidget(box)
        root.addLayout(bottom)

        self._wire_live_preview()
        self._fit_stack_height()
        self.refresh_preview()

    # ------------------------------------------------------------------
    # 参数页
    # ------------------------------------------------------------------

    def _page_replace(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(0, 4, 0, 4)
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("要查找的文字（留空则不处理）")
        self.repl_edit = QLineEdit()
        self.repl_edit.setPlaceholderText("替换为（可留空表示删除）")
        self.regex_chk = QCheckBox("使用正则表达式")
        self.case_chk = QCheckBox("区分大小写")
        form.addRow("查找：", self.find_edit)
        form.addRow("替换为：", self.repl_edit)
        opts = QHBoxLayout()
        opts.addWidget(self.regex_chk)
        opts.addWidget(self.case_chk)
        opts.addStretch(1)
        holder = QWidget()
        holder.setLayout(opts)
        form.addRow("", holder)
        return w

    def _page_prefix(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(0, 4, 0, 4)
        self.prefix_edit = QLineEdit()
        self.prefix_edit.setPlaceholderText("加在文件名最前面，例如：2026_")
        form.addRow("前缀：", self.prefix_edit)
        return w

    def _page_suffix(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(0, 4, 0, 4)
        self.suffix_edit = QLineEdit()
        self.suffix_edit.setPlaceholderText("加在扩展名前，例如：_已归档")
        form.addRow("后缀：", self.suffix_edit)
        return w

    def _page_number(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(0, 4, 0, 4)
        self.num_base = QLineEdit("文件")
        self.num_start = QSpinBox()
        self.num_start.setRange(0, 999999)
        self.num_start.setValue(1)
        self.num_step = QSpinBox()
        self.num_step.setRange(1, 1000)
        self.num_step.setValue(1)
        self.num_digits = QSpinBox()
        self.num_digits.setRange(1, 8)
        self.num_digits.setValue(2)
        self.num_keep = QCheckBox("保留原文件名（格式：基础名01_原名）")
        form.addRow("基础名：", self.num_base)
        form.addRow("起始序号：", self.num_start)
        form.addRow("步长：", self.num_step)
        form.addRow("序号位数：", self.num_digits)
        form.addRow("", self.num_keep)
        return w

    def _page_case(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(0, 4, 0, 4)
        self.case_box = QComboBox()
        self.case_box.addItem("全部小写", "lower")
        self.case_box.addItem("全部大写", "upper")
        self.case_box.addItem("首字母大写", "title")
        form.addRow("转换方式：", self.case_box)
        hint = QLabel("只改主文件名，扩展名保持不变。")
        hint.setObjectName("Hint")
        form.addRow("", hint)
        return w

    def _wire_live_preview(self) -> None:
        for le in (self.find_edit, self.repl_edit, self.prefix_edit,
                   self.suffix_edit, self.num_base):
            le.textChanged.connect(self.refresh_preview)
        for sp in (self.num_start, self.num_step, self.num_digits):
            sp.valueChanged.connect(self.refresh_preview)
        for chk in (self.regex_chk, self.case_chk, self.num_keep):
            chk.toggled.connect(self.refresh_preview)
        self.case_box.currentIndexChanged.connect(self.refresh_preview)

    def _on_mode_changed(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self._fit_stack_height()
        self.refresh_preview()

    def _fit_stack_height(self) -> None:
        """让参数区高度只包住当前模式的控件，避免大块空白。"""
        page = self.stack.currentWidget()
        if page is not None:
            self.stack.setFixedHeight(page.sizeHint().height())

    # ------------------------------------------------------------------

    def options(self) -> RenameOptions:
        mode = self.mode_box.currentData()
        return RenameOptions(
            mode=mode,
            find=self.find_edit.text(),
            replace=self.repl_edit.text(),
            use_regex=self.regex_chk.isChecked(),
            case_sensitive=self.case_chk.isChecked(),
            prefix=self.prefix_edit.text(),
            suffix=self.suffix_edit.text(),
            number_base=self.num_base.text(),
            number_start=self.num_start.value(),
            number_step=self.num_step.value(),
            number_digits=self.num_digits.value(),
            number_keep_name=self.num_keep.isChecked(),
            case_mode=self.case_box.currentData(),
        )

    def refresh_preview(self) -> None:
        self.plan = plan_rename(self.entries, self.options())
        runnable = [p for p in self.plan if p.status == STATUS_OK]

        self.preview.setRowCount(len(self.plan))
        for r, item in enumerate(self.plan):
            if item.status == STATUS_OK:
                badge = "✔ 加数字" if item.message else "✔ 改名"
                color = Qt.GlobalColor.darkGreen
            elif item.status == STATUS_SKIP:
                badge = "— 不变"
                color = Qt.GlobalColor.gray
            else:
                badge = "✖ 跳过"
                color = Qt.GlobalColor.red
            cells = [badge, item.src.name, item.dst.name, item.message]
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                it.setForeground(color)
                self.preview.setItem(r, c, it)

        self.btn_run.setEnabled(bool(runnable))
        self.btn_run.setText(
            f"执行重命名（{len(runnable)} 项）" if runnable else "没有需要改名的条目"
        )

    def run_rename(self) -> None:
        runnable = [p for p in self.plan if p.status == STATUS_OK]
        if not runnable:
            return
        lines = "\n".join(f"  {p.src.name}  →  {p.dst.name}" for p in runnable[:12])
        if len(runnable) > 12:
            lines += f"\n  …… 以及另外 {len(runnable) - 12} 项"

        ok = QMessageBox.question(
            self,
            "确认重命名",
            f"即将重命名 {len(runnable)} 项：\n\n{lines}\n\n"
            "重命名可在主界面「撤销」中整批还原，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if ok != QMessageBox.StandardButton.Yes:
            return

        res = execute(
            self.plan,
            policy=POLICY_SKIP,
            journal=self.journal,
            action="rename",
            note=f"批量重命名 {len(runnable)} 项",
        )
        self.executed = res.ok

        msg = f"重命名完成：{res.summary()}"
        if res.errors:
            msg += "\n\n失败明细：\n" + "\n".join(res.errors[:10])
        QMessageBox.information(self, "重命名结果", msg)
        self.refresh_preview()
        if res.ok:
            self.accept()
