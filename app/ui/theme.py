"""界面样式（QSS）与分类图标。"""

from __future__ import annotations

from ..icons import BUILTIN_ICONS, CUSTOM_ICON_CHOICES

CATEGORY_ICON: dict[str, str] = dict(BUILTIN_ICONS)


def category_icon(cat: str) -> str:
    return CATEGORY_ICON.get(cat, "🗂️")


QSS = """
* { font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif; }

QWidget { font-size: 13px; color: #1f2937; background: #f5f6f8; }

QMainWindow, QDialog { background: #f5f6f8; }

/* ---------- 顶部标题条 ---------- */
#HeaderBar {
    background: #ffffff;
    border-bottom: 1px solid #e3e6ea;
}
#AppTitle { font-size: 16px; font-weight: 600; color: #111827; }
#AppPath  { color: #6b7280; font-size: 12px; }

/* ---------- 工具条 ---------- */
QToolBar {
    background: #ffffff;
    border: none;
    border-bottom: 1px solid #e3e6ea;
    padding: 6px 10px;
    spacing: 6px;
}
QToolBar QToolButton {
    padding: 6px 12px;
    border-radius: 6px;
    border: 1px solid transparent;
    color: #374151;
}
QToolBar QToolButton:hover  { background: #eef2ff; border-color: #dbe3ff; }
QToolBar QToolButton:pressed { background: #e0e7ff; }
QToolBar QToolButton:disabled { color: #b6bcc6; }
QToolBar::separator { background: #e3e6ea; width: 1px; margin: 4px 8px; }

/* ---------- 按钮 ---------- */
QPushButton {
    background: #ffffff;
    border: 1px solid #d5d9e0;
    border-radius: 6px;
    padding: 6px 14px;
    color: #374151;
}
QPushButton:hover   { background: #f3f4f6; border-color: #c3c9d2; }
QPushButton:pressed { background: #e5e7eb; }
QPushButton:disabled { color: #b6bcc6; background: #fafafa; }

QPushButton#Primary {
    background: #2563eb; border: 1px solid #2563eb; color: #ffffff; font-weight: 600;
}
QPushButton#Primary:hover   { background: #1d4ed8; border-color: #1d4ed8; }
QPushButton#Primary:pressed { background: #1e40af; }
QPushButton#Primary:disabled { background: #a9bdf0; border-color: #a9bdf0; color: #f0f4ff; }

QPushButton#Danger { color: #b91c1c; border-color: #f0c4c4; }
QPushButton#Danger:hover { background: #fef2f2; border-color: #e8a5a5; }

/* ---------- 输入 ---------- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox {
    background: #ffffff;
    border: 1px solid #d5d9e0;
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: #bfdbfe;
    selection-color: #111827;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {
    border-color: #2563eb;
}
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background: #ffffff; border: 1px solid #d5d9e0;
    selection-background-color: #eef2ff; selection-color: #111827;
    outline: none;
}
QCheckBox { spacing: 6px; }
QCheckBox::indicator { width: 15px; height: 15px; }
QCheckBox::indicator:unchecked {
    border: 1px solid #c3c9d2; border-radius: 3px; background: #ffffff;
}
QCheckBox::indicator:checked {
    border: 1px solid #2563eb; border-radius: 3px; background: #2563eb;
}

/* ---------- 表格 ---------- */
QTableView, QTableWidget {
    background: #ffffff;
    alternate-background-color: #fafbfc;
    border: 1px solid #e3e6ea;
    border-radius: 8px;
    gridline-color: #f0f2f5;
    selection-background-color: #e0e7ff;
    selection-color: #111827;
    outline: none;
}
QTableView::item, QTableWidget::item { padding: 4px 6px; border: none; }
QHeaderView::section {
    background: #f8f9fb;
    color: #4b5563;
    padding: 7px 8px;
    border: none;
    border-bottom: 1px solid #e3e6ea;
    border-right: 1px solid #f0f2f5;
    font-weight: 600;
}
QTableCornerButton::section { background: #f8f9fb; border: none; }

/* 表格里的勾选框（归档规则的「启用」列） */
QTableView::indicator, QTableWidget::indicator { width: 15px; height: 15px; }
QTableView::indicator:unchecked, QTableWidget::indicator:unchecked {
    border: 1px solid #c3c9d2; border-radius: 3px; background: #ffffff;
}
QTableView::indicator:checked, QTableWidget::indicator:checked {
    border: 1px solid #2563eb; border-radius: 3px; background: #2563eb;
}

/* ---------- 左侧分类 ---------- */
QListWidget#CategoryList {
    background: #ffffff;
    border: 1px solid #e3e6ea;
    border-radius: 8px;
    padding: 4px;
    outline: none;
}
QListWidget#CategoryList::item {
    padding: 7px 10px;
    border-radius: 6px;
    margin: 1px 0;
}
QListWidget#CategoryList::item:hover    { background: #f3f4f6; }
QListWidget#CategoryList::item:selected { background: #e0e7ff; color: #1e40af; font-weight: 600; }

/* ---------- 其它 ---------- */
QStatusBar { background: #ffffff; border-top: 1px solid #e3e6ea; color: #4b5563; }
QStatusBar::item { border: none; }
QGroupBox {
    border: 1px solid #e3e6ea; border-radius: 8px;
    background: #ffffff; margin-top: 12px; padding: 12px 10px 10px 10px;
    font-weight: 600;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #374151; }
QSplitter::handle { background: transparent; width: 8px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #cfd4dc; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #b3bac4; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #cfd4dc; border-radius: 5px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QLabel#Hint { color: #6b7280; font-size: 12px; }
QLabel#SectionTitle { font-size: 14px; font-weight: 600; color: #111827; }
"""
