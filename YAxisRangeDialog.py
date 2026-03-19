# -*- coding: utf-8 -*-
"""Y 轴范围设置弹窗：编辑套管压力、套管排量、砂比、粘度四组纵坐标的最小/最大值，确定写入 config.ini。"""
import configparser
import os
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QDoubleSpinBox, QPushButton, QMessageBox,
)
from PyQt5.QtCore import Qt

CONFIG_SECTION = 'plot_y_ranges'
CONFIG_KEYS = [
    ('pressure_min', 'pressure_max', '套管压力(MPa)'),
    ('rate_min', 'rate_max', '套管排量'),
    ('sand_min', 'sand_max', '砂比'),
    ('viscosity_min', 'viscosity_max', '粘度(mPa·s)'),
]
DEFAULTS = {
    'pressure_min': 0.0, 'pressure_max': 100.0,
    'rate_min': 0.0, 'rate_max': 50.0,
    'sand_min': 0.0, 'sand_max': 100.0,
    'viscosity_min': 0.0, 'viscosity_max': 100.0,
}


def _config_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.ini')


def load_y_ranges_from_config():
    """从 config.ini 读取 [plot_y_ranges]，缺失键用 DEFAULTS。返回 dict。与项目一致使用 GBK 编码。"""
    cfg = configparser.ConfigParser()
    path = _config_path()
    if os.path.isfile(path):
        try:
            cfg.read(path, encoding='gbk')
        except (UnicodeDecodeError, LookupError):
            cfg.read(path, encoding='utf-8')
    section = cfg[CONFIG_SECTION] if CONFIG_SECTION in cfg else {}
    out = {}
    for k, v in DEFAULTS.items():
        try:
            out[k] = float(section.get(k, v))
        except (TypeError, ValueError):
            out[k] = v
    return out


def save_y_ranges_to_config(ranges):
    """将 ranges 字典写入 config.ini 的 [plot_y_ranges]。与项目一致使用 GBK 编码。"""
    path = _config_path()
    cfg = configparser.ConfigParser()
    if os.path.isfile(path):
        try:
            cfg.read(path, encoding='gbk')
        except (UnicodeDecodeError, LookupError):
            cfg.read(path, encoding='utf-8')
    if CONFIG_SECTION not in cfg:
        cfg.add_section(CONFIG_SECTION)
    for k, v in ranges.items():
        cfg[CONFIG_SECTION][k] = str(v)
    try:
        with open(path, 'w', encoding='gbk') as f:
            cfg.write(f)
    except (UnicodeEncodeError, LookupError):
        with open(path, 'w', encoding='utf-8') as f:
            cfg.write(f)


class YAxisRangeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Y 轴范围调整')
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._spinboxes = {}
        for min_key, max_key, label in CONFIG_KEYS:
            min_sb = QDoubleSpinBox(self)
            # 最小值下限改为 0，禁止出现负数
            min_sb.setRange(0.0, 1e6)
            min_sb.setDecimals(2)

            max_sb = QDoubleSpinBox(self)
            # 最大值下限同样从 0 开始，禁止出现负数
            max_sb.setRange(0.0, 1e6)
            max_sb.setDecimals(2)

            form.addRow(QLabel(label + ' 最小值:'), min_sb)
            form.addRow(QLabel(label + ' 最大值:'), max_sb)
            self._spinboxes[min_key] = min_sb
            self._spinboxes[max_key] = max_sb

        layout.addLayout(form)
        btn_layout = QHBoxLayout()
        btn_ok = QPushButton('确定', self)
        btn_ok.clicked.connect(self._on_ok)
        btn_exit = QPushButton('退出', self)
        btn_exit.clicked.connect(self.reject)
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_exit)
        layout.addLayout(btn_layout)
        self._load_from_config()

    def _load_from_config(self):
        try:
            r = load_y_ranges_from_config()
        except Exception:
            r = DEFAULTS.copy()
        for k, sb in self._spinboxes.items():
            # 若配置里有负数，spinbox 会自动裁剪到 setRange 的下限 0.0
            sb.setValue(r.get(k, DEFAULTS.get(k, 0.0)))

    def _on_ok(self):
        ranges = {k: sb.value() for k, sb in self._spinboxes.items()}
        for min_key, max_key, _ in CONFIG_KEYS:
            min_val = ranges[min_key]
            max_val = ranges[max_key]
            # 业务约束：最小值 >= 0，最大值 > 0，且最小值 < 最大值
            if min_val < 0.0 or max_val <= 0.0 or min_val >= max_val:
                QMessageBox.warning(
                    self,
                    '提示',
                    '每组 Y 轴范围需满足：最小值 ≥ 0、最大值 > 0，且最小值小于最大值。'
                )
                return
        save_y_ranges_to_config(ranges)
        self.accept()