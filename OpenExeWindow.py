# coding=gb2312
import configparser
import csv
import os
import re
import sqlite3
import pyodbc
import pandas as pd
import time
from PyQt5 import QtGui, QtWidgets
import datetime
import uploadMainWindow
from LocalPlotWidget import LocalPlotWidget
from YAxisRangeDialog import YAxisRangeDialog, load_y_ranges_from_config
import requests
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import *
import serial
import serial.tools.list_ports
from thread import WorkerThread
from thread import ReceiverThread
from thread import ReceiverViscosityThread
from thread import UploadViscosityThread
from db_to_csv import db_to_csv, get_processed_log_data, write_processed_csv
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout
import json

class WellInfoDialog(QDialog):
    """井信息设置弹窗：左侧井信息表单，右侧井信息状态栏。"""
    def __init__(self, main_ui, parent=None):
        super().__init__(parent)
        self.main_ui = main_ui
        self.setWindowTitle("井信息设置")
        self.setMinimumSize(720, 520)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        # 从主窗口容器中取出井信息表单和井信息状态栏，放入本弹窗
        layout.addWidget(main_ui.tab, stretch=4)
        layout.addWidget(main_ui.groupBox1, stretch=3)
        self.setWindowModality(Qt.NonModal)
        self.setLayout(layout)
    def closeEvent(self, event):
        # 关闭时把两个控件还回主窗口的隐藏容器，避免被析构
        self.main_ui.well_info_container_layout.addWidget(self.main_ui.tab, stretch=4)
        self.main_ui.well_info_container_layout.addWidget(self.main_ui.groupBox1, stretch=3)
        super().closeEvent(event)

class SecondPointDialog(QDialog):
    """功能 -> 秒点数据采集：左侧 串口号(秒点)+字段设置+开始/停止接收，右侧 施工秒点数据、液体性能数据状态栏。"""
    def __init__(self, main_ui, parent=None):
        super().__init__(parent)
        self.main_ui = main_ui
        self.setWindowTitle("秒点数据采集")
        self.setMinimumSize(760, 520)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(main_ui.second_point_container, stretch=4)
        layout.addWidget(main_ui.groupBox2, stretch=3)
        self.setWindowModality(Qt.NonModal)
        self.setLayout(layout)
    def closeEvent(self, event):
        # 关闭时放回主窗口的隐藏容器，避免被析构
        lay = self.main_ui.second_point_dialog_container_layout
        lay.addWidget(self.main_ui.second_point_container, stretch=4)
        lay.addWidget(self.main_ui.groupBox2, stretch=3)
        super().closeEvent(event)

class ViscosityDialog(QDialog):
    """功能 -> 黏度数据采集：左侧 串口号(黏/密度)+选择液体类型+开始/停止接收+开始上传/结束，右侧 黏度数据状态栏。"""
    def __init__(self, main_ui, parent=None):
        super().__init__(parent)
        self.main_ui = main_ui
        self.setWindowTitle("黏度数据采集")
        self.setMinimumSize(680, 480)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(main_ui.viscosity_container, stretch=4)
        layout.addWidget(main_ui.groupBox3, stretch=3)
        self.setWindowModality(Qt.NonModal)
        self.setLayout(layout)
    def closeEvent(self, event):
        lay = self.main_ui.viscosity_dialog_container_layout
        lay.addWidget(self.main_ui.viscosity_container, stretch=4)
        lay.addWidget(self.main_ui.groupBox3, stretch=3)
        super().closeEvent(event)
class PlotDialog(QDialog):
    """查看 -> 绘图：曲线绘制弹窗，内容为 LocalPlotWidget + 刷新按钮。"""
    def __init__(self, main_ui, plot_container, parent=None):
        super().__init__(parent)
        self.main_ui = main_ui
        self.setWindowTitle("实时曲线")
        self.setMinimumSize(800, 500)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(plot_container)
        self.setWindowModality(Qt.NonModal)
        # 标题栏显示最小化、最大化（最大化后变为“还原”）、关闭，不显示“?”帮助按钮
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint
        )
        self.setLayout(layout)

class HistoryCurveDialog(QDialog):
    """查看 -> 历史曲线：与曲线绘制界面相同，顶部增加选择文件，选 db 后刷新显示曲线与表格。"""
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self._history_file_path = ''
        self.setWindowTitle("历史曲线")
        self.setMinimumSize(800, 500)
        self.setWindowModality(Qt.NonModal)
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        # 最上方：选择文件
        file_layout = QHBoxLayout()
        self.btn_history_select_file = QPushButton('选择文件', self)
        self.btn_history_select_file.clicked.connect(self._on_history_select_file_clicked)
        self.label_history_path = QLabel('未选择文件', self)
        self.label_history_path.setStyleSheet('color: gray;')
        file_layout.addWidget(self.btn_history_select_file)
        file_layout.addWidget(self.label_history_path, 1)
        layout.addLayout(file_layout)
        # 下方：与曲线绘制相同布局（左曲线+右表格）
        content = QWidget()
        main_layout = QHBoxLayout(content)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self._history_plot_widget = LocalPlotWidget(left_widget)
        left_layout.addWidget(self._history_plot_widget)
        btn_layout = QHBoxLayout()
        self.btn_history_refresh = QPushButton('刷新本地秒点曲线', left_widget)
        self.btn_history_adjust = QPushButton('调整', left_widget)
        btn_layout.addWidget(self.btn_history_refresh)
        btn_layout.addWidget(self.btn_history_adjust)
        left_layout.addLayout(btn_layout)
        self.btn_history_refresh.clicked.connect(self._on_history_refresh_clicked)
        self.btn_history_adjust.clicked.connect(self._on_history_adjust_clicked)
        main_layout.addWidget(left_widget, 3)
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_title_row = QHBoxLayout()
        right_title = QLabel('由当前 db 转存的 CSV 数据（与左侧曲线同源）')
        self.btn_save_history_csv = QPushButton('保存csv文件', right_widget)
        self.btn_save_history_csv.setEnabled(False)
        self.btn_save_history_csv.clicked.connect(self._on_save_history_csv_clicked)
        right_title_row.addWidget(right_title)
        right_title_row.addWidget(self.btn_save_history_csv)
        right_layout.addLayout(right_title_row)
        self._history_table = QTableWidget()
        self._history_processed_data = None
        self._history_table.setAlternatingRowColors(True)
        self._history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._history_table.horizontalHeader().setStretchLastSection(True)
        right_layout.addWidget(self._history_table)
        main_layout.addWidget(right_widget, 2)
        layout.addWidget(content)
        self._history_plot_widget.curve_data_updated.connect(self._on_history_curve_data_updated)
        self.setLayout(layout)
    def _on_history_curve_data_updated(self, db_path):
        """历史曲线（全量/增量）加载完成后调用，同步刷新右侧表格与保存用数据。"""
        if not db_path or not str(db_path).strip():
            return
        self._history_processed_data = self.main_window._fill_plot_table_from_db(db_path, self._history_table)
        if self._history_processed_data is not None:
            self.btn_save_history_csv.setEnabled(True)
    def _on_history_select_file_clicked(self):
        default_dir = 'C:/a_transmission_data'
        if self._history_file_path:
            default_dir = os.path.dirname(self._history_file_path)
        path, _ = QFileDialog.getOpenFileName(self, '选择 db 文件', default_dir, '数据库 (*.db);;所有文件 (*)')
        if path:
            self._history_file_path = path
            self.label_history_path.setText(path)
            self.label_history_path.setStyleSheet('')
    def _parse_well_info_from_filename(self, db_path):
        """从 db 文件名解析 井号、压裂次数、层位、段，用于图表标题。"""
        name = os.path.splitext(os.path.basename(db_path))[0]
        m = re.match(r'^(.+?)第(\d+)次压裂(.+?)第(\d+)段$', name)
        if m:
            return m.group(1), m.group(2), m.group(3), m.group(4)
        return name, '', '', ''


    def _on_history_refresh_clicked(self):
        if not self._history_file_path or not os.path.isfile(self._history_file_path):
            return
        well, frac_num, layer, period = self._parse_well_info_from_filename(self._history_file_path)
        self._history_plot_widget.set_db_path(self._history_file_path, well, frac_num, layer, period)
        try:
            r = load_y_ranges_from_config()
            p_range = (r.get('pressure_min', 0.0), r.get('pressure_max', 100.0))
            rate_range = (r.get('rate_min', 0.0), r.get('rate_max', 50.0))
            sand_range = (r.get('sand_min', 0.0), r.get('sand_max', 100.0))
            v_range = (r.get('viscosity_min', 0.0), r.get('viscosity_max', 100.0))
            self._history_plot_widget.set_user_y_ranges(p_range, rate_range, sand_range, v_range)
            self._history_plot_widget.load_full_data()
        except Exception as e:
            print('历史曲线加载异常:', e)
        self._history_processed_data = self.main_window._fill_plot_table_from_db(self._history_file_path,
                                                                                 self._history_table)
        if self._history_processed_data is not None:
            self.btn_save_history_csv.setEnabled(True)

    def _on_history_adjust_clicked(self):
        """打开 Y 轴范围调整弹窗；确定后写入 config，下次刷新历史曲线时生效。"""
        dlg = YAxisRangeDialog(self)
        dlg.exec_()

    def _on_save_history_csv_clicked(self):
        if getattr(self, '_history_processed_data', None) is None:
            return
        from db_to_csv import write_processed_csv
        headers, rows = self._history_processed_data
        default_path = 'C:/a_transmission_data/data.csv'
        if self._history_file_path and str(self._history_file_path).strip():
            db_dir = os.path.dirname(os.path.abspath(self._history_file_path))
            base = os.path.splitext(os.path.basename(self._history_file_path))[0]
            if db_dir and base:
                default_path = os.path.join(db_dir, base + '.csv')
            elif db_dir:
                default_path = os.path.join(db_dir, 'data.csv')
        path, _ = QFileDialog.getSaveFileName(
            self, '保存 CSV 文件', default_path,
            'CSV (*.csv);;所有文件 (*)'
        )
        if not path:
            return
        try:
            write_processed_csv(headers, rows, path)
            self.main_window.ui.statusbar.showMessage('已保存: {}'.format(path))
        except Exception as e:
            QMessageBox.warning(self, '保存失败', '保存 CSV 失败: {}'.format(e))

class CsvFileDialog(QDialog):
    """查看 -> CSV：选择由 db 转存的 csv 文件，下方以表格形式显示内容（无曲线）。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._csv_path = ''
        self.setWindowTitle("CSV文件")
        self.setMinimumSize(700, 500)
        self.setWindowModality(Qt.NonModal)
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        file_layout = QHBoxLayout()
        self.btn_select_csv = QPushButton('选择文件', self)
        self.btn_select_csv.clicked.connect(self._on_select_csv_clicked)
        self.label_csv_path = QLabel('未选择文件', self)
        self.label_csv_path.setStyleSheet('color: gray;')
        file_layout.addWidget(self.btn_select_csv)
        file_layout.addWidget(self.label_csv_path, 1)
        layout.addLayout(file_layout)
        self._csv_table = QTableWidget()
        self._csv_table.setAlternatingRowColors(True)
        self._csv_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._csv_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._csv_table)
        self.setLayout(layout)
    def _on_select_csv_clicked(self):
        default_dir = 'C:/a_transmission_data'
        if self._csv_path:
            default_dir = os.path.dirname(self._csv_path)
        path, _ = QFileDialog.getOpenFileName(self, '选择 CSV 文件', default_dir, 'CSV (*.csv);;所有文件 (*)')
        if path:
            self._csv_path = path
            self.label_csv_path.setText(path)
            self.label_csv_path.setStyleSheet('')
            self._load_csv_to_table(path)
    def _load_csv_to_table(self, csv_path):
        if not csv_path or not os.path.isfile(csv_path):
            return
        self._csv_table.setRowCount(0)
        self._csv_table.setColumnCount(0)
        try:
            with open(csv_path, 'r', encoding='utf-8-sig', newline='') as f:
                reader = csv.reader(f)
                rows = list(reader)
            if not rows:
                return
            header = rows[0]
            data_rows = rows[1:]
            self._csv_table.setColumnCount(len(header))
            self._csv_table.setRowCount(len(data_rows))
            self._csv_table.setHorizontalHeaderLabels(header)
            for i, row in enumerate(data_rows):
                for j in range(len(header)):
                    cell = row[j] if j < len(row) else ''
                    s = '' if cell is None else str(cell).strip()
                    if s.lower() == 'none':
                        s = ''
                    self._csv_table.setItem(i, j, QTableWidgetItem(s))
        except Exception as e:
            self._csv_table.setColumnCount(1)
            self._csv_table.setRowCount(1)
            self._csv_table.setHorizontalHeaderLabels(['提示'])
            self._csv_table.setItem(0, 0, QTableWidgetItem('加载失败: {}'.format(e)))


# 打开主窗口(选项卡)
class OpenExeWindow(QMainWindow):

    def __init__(self, jwt_token, parent=None):
        super().__init__(parent)  # 调用父类构造函数，创建窗体
        self.ui = uploadMainWindow.Ui_MainWindow()  # 创建UI对象
        self.ui.setupUi(self)  # 构造UI界面
        self.jwt_token = jwt_token
        print('main:', self.jwt_token)
        # 选择的数据库文件路径（可能是直传时的数据库文件、也可能是接收串口保存在本地的数据库文件）
        self.file_path = ''

        self.worker_thread = None
        self.receiver_viscosity_thread = None
        self.receive_water_thread = None
        # 初始化数据 函数
        self.init_data()

        # 设置状态栏为只读
        self.ui.textEdit.setReadOnly(True)
        # 设置状态栏为只读
        self.ui.textEdit2.setReadOnly(True)
        # 设置状态栏为只读
        self.ui.textEdit3.setReadOnly(True)
        # 底部状态栏版权信息
        font = QtGui.QFont()
        font.setPointSize(10)
        self.ui.statusbar.setFont(font)
        self.ui.statusbar.showMessage("@copyright   如需要更高版本请联系:祝凯 17806265805")

        # 单机版：保存井信息
        self.ui.pushButton_upload_wellinfo.clicked.connect(self.save_wellinfo)
        # 文件->井信息设置:打开井信息弹窗
        self.ui.action_well_info.triggered.connect(self.show_well_info_dialog)
        self.ui.action_second_point.triggered.connect(self.show_second_point_dialog)
        self.ui.action_viscosity.triggered.connect(self.show_viscosity_dialog)
        # 开始\停止接收（秒点数据）
        self.pushButton_start_receive.clicked.connect(self.start_receive)
        self.pushButton_stop_receive.clicked.connect(self.stop_receive)
        self.pushButton_stop_receive.setEnabled(False)
        # 开始\停止上传（秒点数据）
        # self.pushButton_start_upload.clicked.connect(self.start_upload_tab4)
        # self.pushButton_stop_upload.clicked.connect(self.end_upload_tab4)
        # self.pushButton_stop_upload.setEnabled(False)
        # self.pushButton_start_upload.setEnabled(False)

        # 开始/停止接收（粘度、密度数据）
        self.btn_start_tab6.clicked.connect(self.receive_viscosity_data)
        self.btn_stop_tab6.clicked.connect(self.stop_receive_viscosity_data)
        self.btn_stop_tab6.setEnabled(False)
        # 开始/停止上传（粘度、密度数据）
        # self.btn2_start_tab6.clicked.connect(self.start_upload_viscosity_data)
        # self.btn2_stop_tab6.clicked.connect(self.end_upload_viscosity_data)
        # self.btn2_stop_tab6.setEnabled(False)
        self.btn2_start_tab6.clicked.connect(self.start_upload_tab4)
        self.btn2_stop_tab6.clicked.connect(self.end_upload_tab4)
        self.btn2_stop_tab6.setEnabled(False)



        # 开始\停止上传（软件直传）
        self.btn_start.clicked.connect(self.start_upload)
        self.btn_stop.clicked.connect(self.end_upload)
        # 文件选择按钮
        self.btn_fileselect.clicked.connect(self.openFileDialog)
        # 获取字段按钮
        self.btn_getcolumn.clicked.connect(self.get_columns)  # 根据选择的文件获取字段

        # 选项卡单击事件
        self.ui.tabWidget.tabBarClicked.connect(self.tab_clicked)
        self.ui.action_edit_liquid.triggered.connect(self.show_liquid_calibration_dialog)
        # 传输方式选择变化时，切换对应选项卡的可见性
        self.ui.radioButton_direct_transmission.toggled.connect(self.on_radio_button_changed)
        self.ui.radioButton_indirect_transmission.toggled.connect(self.on_radio_button_changed)
        # 上传时的参数
        self.point_1 = 0
        self.point_2 = 0
        # 粘度、密度指针
        self.viscosity_point_1 = 0
        self.viscosity_point_2 = 0


        self.columns_info = ''  # db文件表头信息
        # 配置文件中的接收字段信息信息
        self.config_name_save = ''
        # 根据区块过滤井号时使用，存储所有井号
        self.well_names = []
        # 配置文件
        self.load_config()
        # 创建数据表的字段数量
        self.field_num = 0
        # 根据当前传输方式（默认串口转传）设置选项卡可见性
        self.on_radio_button_changed()

    # 加载配置文件@@@
    def load_config(self):
        # 从配置文件加载参数
        config = configparser.ConfigParser()
        try:
            config.read('config.ini', encoding='utf-8')
        except UnicodeDecodeError:
            config.read('config.ini', encoding='gbk')
        if 'Parameters' in config:
            params = config['Parameters']
            self.point_1 = int(params.get('point_1', 0))
            self.point_2 = int(params.get('point_2', 0))
        if 'viscosity_pointer' in config:
            params = config['viscosity_pointer']
            self.viscosity_point_1 = int(params.get('viscosity_point_1', 0))
            self.viscosity_point_2 = int(params.get('viscosity_point_2', 0))
        if 'basic_information_settings' in config:
            params = config['basic_information_settings']
            self.ui.lineEdit_block.setText(str(params.get("block_name", '')))
            self.ui.lineEdit_platform.setText(str(params.get("platform", '')))
            self.ui.lineEdit_well.setText(str(params.get("well_name", '')))
            self.ui.lineEdit_frac_num.setText(str(params.get("frac_num", '')))
            self.ui.lineEdit_layer.setText(str(params.get("layer", '')))
            self.ui.lineEdit_period.setText(str(params.get("period", '')))
            self.ui.comboBox_crew.setCurrentText(str(params.get("crew", '')))

    # 将point_1, point_2存到配置文件，软件每次打开会重新加载@@@
    def save_config(self):
        # 保存参数到配置文件
        config = configparser.ConfigParser()
        try:
            config.read('config.ini', encoding='utf-8')
        except UnicodeDecodeError:
            config.read('config.ini', encoding='gbk')
        config['Parameters']['point_1'] = str(self.point_1)
        config['Parameters']['point_2'] = str(self.point_2)
        config['viscosity_pointer']['viscosity_point_1'] = str(self.viscosity_point_1)
        config['viscosity_pointer']['viscosity_point_2'] = str(self.viscosity_point_2)

        config['basic_information_settings']['block_name'] = self.ui.lineEdit_block.text()
        config['basic_information_settings']['platform'] = self.ui.lineEdit_platform.text()
        config['basic_information_settings']['well_name'] = self.ui.lineEdit_well.text()
        config['basic_information_settings']['frac_num'] = self.ui.lineEdit_frac_num.text()
        config['basic_information_settings']['layer'] = self.ui.lineEdit_layer.text()
        config['basic_information_settings']['period'] = self.ui.lineEdit_period.text()
        config['basic_information_settings']['crew'] = self.ui.comboBox_crew.currentText()

        name = self.ui.comboBox_measuring_truck.currentText()
        if name != '' and self.config_name_save != '':
            str_ = ''
            if name == '宏华':
                str_ = 'HongHua'
            if name == '杰瑞':
                str_ = 'JieRui'
            if name == '四机厂':
                str_ = 'SiJi'
            config['measuring_truck_field_settings'][f'field_names_{str_}'] = self.config_name_save
        with open('config.ini', 'w') as configfile:
            config.write(configfile)



    # 初始化数据（单机版：字段列表优先从 config.ini 读取）
    def init_data(self):
        # 串口列表、液体类型列表（本地）
        port_list = self.get_all_ports()
        liquid_list = self.get_liquid_parameter()
        liquid_list.insert(0, '')

        # 读取本地配置
        config = configparser.ConfigParser()
        try:
            config.read('config.ini', encoding='utf-8')
        except UnicodeDecodeError:
            config.read('config.ini', encoding='gbk')

        # 如果在线模式下 base_API 有真实实现，这里仍然可以拿到后端的基础信息；
        # 单机版下我们之前把 base_API 改成了返回空列表的占位实现，也不会报错。
        rel_dic = self.base_API({'url': '/basic_info_get', 'method': 'GET'})

        # 仪表车厂家
        # 仪表车厂家：先加入固定四项，再补接口返回的（避免接口为空时下拉无选项）
        for opt in ['宏华', '杰瑞', '三一重工', '四机厂']:
            self.ui.comboBox_measuring_truck.addItem(opt)
        for item in rel_dic.get('measure_trucks', []):
            if self.ui.comboBox_measuring_truck.findText(item) == -1:
                self.ui.comboBox_measuring_truck.addItem(item)
        self.ui.comboBox_measuring_truck.setCurrentIndex(-1)

        # 压裂队
        for item in rel_dic.get('crew_names', []):
            self.ui.comboBox_crew.addItem(item)
        self.ui.comboBox_crew.setCurrentIndex(-1)

        # 设备号
        for item in rel_dic.get('gate_way_devices', []):
            self.ui.comboBox_device_num.addItem(item)

        # 井信息下拉框全部设置为可编辑（支持手动输入）
        self.ui.comboBox_crew.setEditable(True)
        self.ui.comboBox_measuring_truck.setEditable(False)
        self.ui.comboBox_device_num.setEditable(True)

        # 从 config.ini 中恢复上次保存的井信息
        # config.iniл??α??
        if 'basic_information_settings' in config:
            params = config['basic_information_settings']
            self.ui.lineEdit_block.setText(str(params.get("block_name", '')))
            self.ui.lineEdit_platform.setText(str(params.get("platform", '')))
            self.ui.lineEdit_well.setText(str(params.get("well_name", '')))
            self.ui.lineEdit_frac_num.setText(str(params.get("frac_num", '')))
            self.ui.lineEdit_layer.setText(str(params.get("layer", '')))
            self.ui.lineEdit_period.setText(str(params.get("period", '')))
            self.ui.comboBox_crew.setCurrentText(str(params.get("crew", '')))

        # ---------- 字段中文名列表：优先从 config.ini[column_cname] 读取 ----------
        labels = []
        if 'column_cname' in config:
            col_section = config['column_cname']
            names_str = col_section.get('names', '')
            if names_str.strip():
                labels = [name.strip() for name in names_str.split(',') if name.strip()]

        # 如果本地配置里没写，就退回到后端返回的 column_cname（在线模式下可用）
        if not labels:
            labels = rel_dic.get('column_cname', [])

        # 创建一个字典，用于保存标签和选项的对应关系
        self.label_combo_dict = []
        self.dict_label_combox_db = []

        # 选项卡2的总体布局
        tab2_layout = QVBoxLayout(self.ui.tab_2)

        # 源文件水平布局  label+button(选择文件)
        fileselect_layout = QHBoxLayout(self.ui.tab_2)
        label_select_file = QLabel('源文件', self.ui.tab_2)
        self.btn_fileselect = QPushButton('选择文件', self.ui.tab_2)
        fileselect_layout.addWidget(label_select_file)
        fileselect_layout.addWidget(self.btn_fileselect)
        fileselect_layout.setStretch(0, 1)
        fileselect_layout.setStretch(1, 8)

        # 获取字段水平布局  label+button
        get_column_layout = QHBoxLayout(self.ui.tab_2)
        label_get_columns = QLabel('表 头', self.ui.tab_2)
        self.btn_getcolumn = QPushButton('获取字段', self.ui.tab_2)
        get_column_layout.addWidget(label_get_columns)
        get_column_layout.addWidget(self.btn_getcolumn)
        get_column_layout.setStretch(0, 1)
        get_column_layout.setStretch(1, 8)

        # 拆分本井字段 / 邻井字段
        main_labels = [label for label in labels if '邻' not in label]
        linjing_labels = [label for label in labels if '邻' in label]
        print(f'linjing_labels={linjing_labels}')

        # ---------- tab2：本井字段表单 ----------
        form_layout1 = QVBoxLayout(self.ui.tab_2)
        # 循环生成除了邻井压力的字段
        for i in range(0, len(main_labels), 2):
            row_layout = QHBoxLayout()
            row_layout.setAlignment(Qt.AlignRight)  # 设置对齐方式为右对齐
            for j in range(2):
                if i + j < len(main_labels):
                    label = QLabel(main_labels[i + j], self.ui.tab_2)
                    combo_box = QComboBox()
                    setattr(self, f"label_{main_labels[i + j]}", label)
                    setattr(self, f"comboBox_{main_labels[i + j]}", combo_box)
                    # 将标签和下拉框添加到字典中
                    dic_ = {}
                    dic_['label'] = str(label.text())
                    dic_['value'] = ''
                    dic_['combo_box'] = combo_box
                    self.label_combo_dict.append(dic_)

                    label.setFixedHeight(25)
                    label.setFixedWidth(70)
                    label.setAlignment(Qt.AlignCenter)
                    combo_box.setFixedHeight(25)

                    row_layout.addWidget(label)
                    row_layout.addWidget(combo_box)
                # 同一行中，两组label+QComboBox之间加一定间距隔开
                if j == 0:
                    row_layout.addItem(QSpacerItem(30, 1, QSizePolicy.Fixed, QSizePolicy.Minimum))
            row_layout.setStretch(0, 1)
            row_layout.setStretch(1, 5)
            row_layout.setStretch(2, 5)
            row_layout.setStretch(3, 1)
            row_layout.setStretch(4, 5)
            form_layout1.addLayout(row_layout)
        groupbox1 = QtWidgets.QGroupBox('本井', self.ui.tab_2)
        groupbox1.setLayout(form_layout1)
        box_layout1 = QtWidgets.QVBoxLayout()
        box_layout1.addWidget(groupbox1)

        # ---------- tab2：邻井字段表单 ----------
        form_layout2 = QtWidgets.QVBoxLayout(self.ui.tab_2)  # 临井压力表单单独列出来
        # 循环生成邻井压力的字段
        for i in range(0, len(linjing_labels), 2):
            row_layout = QHBoxLayout()
            row_layout.setAlignment(Qt.AlignRight)  # 设置对齐方式为左对齐
            for j in range(2):
                if i + j < len(linjing_labels):
                    label = QLabel(linjing_labels[i + j], self.ui.tab_2)
                    combo_box = QComboBox()
                    setattr(self, f"label_{linjing_labels[i + j]}", label)
                    setattr(self, f"comboBox_{linjing_labels[i + j]}", combo_box)
                    # 将标签和下拉框添加到字典中
                    dic_ = {}
                    dic_['label'] = str(label.text())
                    dic_['value'] = ''
                    dic_['combo_box'] = combo_box
                    self.label_combo_dict.append(dic_)

                    label.setFixedHeight(25)
                    label.setFixedWidth(80)
                    label.setAlignment(Qt.AlignCenter)
                    combo_box.setFixedHeight(25)

                    row_layout.addWidget(label)
                    row_layout.addWidget(combo_box)
                # 同一行中，两组label+QComboBox之间加一定间距隔开
                if j == 0:
                    row_layout.addItem(QSpacerItem(30, 1, QSizePolicy.Fixed, QSizePolicy.Minimum))
            row_layout.setStretch(0, 1)
            row_layout.setStretch(1, 5)
            row_layout.setStretch(2, 5)
            row_layout.setStretch(3, 1)
            row_layout.setStretch(4, 5)
            form_layout2.addLayout(row_layout)
        groupbox2 = QtWidgets.QGroupBox('邻井', self.ui.tab_2)
        groupbox2.setLayout(form_layout2)
        box_layout2 = QtWidgets.QVBoxLayout()
        box_layout2.addWidget(groupbox2)

        # 按钮水平布局对象
        btn_layout = QHBoxLayout(self.ui.tab_2)
        # 创建按钮对象
        self.btn_start = QPushButton('开始上传', self.ui.tab_2)
        self.btn_stop = QPushButton('结束', self.ui.tab_2)
        # 将按钮添加到水平布局中
        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_stop)
        # 设置按钮高度为40
        self.btn_start.setFixedHeight(45)
        self.btn_stop.setFixedHeight(45)
        btn_layout.setSpacing(40)

        tab2_layout.addLayout(fileselect_layout)
        tab2_layout.addLayout(get_column_layout)
        tab2_layout.addLayout(box_layout1)
        tab2_layout.addLayout(box_layout2)
        tab2_layout.addLayout(btn_layout)
        # 设置父部件的布局
        self.ui.tab_2.setLayout(tab2_layout)

        # ---------- 选项卡3的总体布局（原始代码保持不变） ----------
        tab3_layout = QVBoxLayout(self.ui.tab_3)
        self.second_point_container = QWidget(self.ui.tab_3)
        self.second_point_container.setObjectName("second_point_container")
        second_point_layout = QVBoxLayout(self.second_point_container)

        port_layout = QHBoxLayout(self.second_point_container)
        port_layout.setSpacing(5)
        label_name = QLabel('串口号(秒点)', self.second_point_container)
        self.comboBox_port_tab3 = QtWidgets.QComboBox()
        self.comboBox_port_tab3.setObjectName("comboBox_port_tab3")
        self.comboBox_port_tab3.setFixedHeight(27)
        self.comboBox_port_tab3.setEditable(True)
        port_layout.addWidget(label_name)
        port_layout.addWidget(self.comboBox_port_tab3)
        port_layout.setStretch(0, 1)
        port_layout.setStretch(1, 8)
        # 串口名
        for item in port_list:
            self.comboBox_port_tab3.addItem(item)
            self.comboBox_port_tab3.setCurrentIndex(-1)

        form_layout_tab3 = QVBoxLayout(self.ui.tab_3)
        groupbox_tab3 = QtWidgets.QGroupBox('字段设置', self.second_point_container)
        for i in range(0, len(main_labels), 2):
            row_layout2 = QHBoxLayout()
            row_layout2.setAlignment(Qt.AlignRight)  # 设置对齐方式为右对齐
            for j in range(2):
                if i + j < len(main_labels):
                    label = QLabel(main_labels[i + j], self.second_point_container)
                    combo_box = QComboBox()
                    # 添加 1 到 18 的数据到 combo_box
                    combo_box.addItems([''])
                    combo_box.addItems([str(x) for x in range(1, 19)])
                    combo_box.setCurrentIndex(-1)

                    setattr(self, f"label_{main_labels[i + j]}", label)
                    setattr(self, f"comboBox_{main_labels[i + j]}_", combo_box)
                    # 将标签和下拉框添加到字典中
                    dic_ = {}
                    dic_['label'] = str(label.text())
                    dic_['value'] = ''
                    dic_['combo_box'] = combo_box

                    self.dict_label_combox_db.append(dic_)

                    label.setFixedHeight(25)
                    label.setFixedWidth(70)
                    label.setAlignment(Qt.AlignCenter)
                    combo_box.setFixedHeight(25)
                    row_layout2.addWidget(label)
                    row_layout2.addWidget(combo_box)
                # 同一行中，两组label+QComboBox之间加一定间距隔开
                if j == 0:
                    row_layout2.addItem(QSpacerItem(30, 1, QSizePolicy.Fixed, QSizePolicy.Minimum))
            row_layout2.setStretch(0, 1)
            row_layout2.setStretch(1, 5)
            row_layout2.setStretch(2, 5)
            row_layout2.setStretch(3, 1)
            row_layout2.setStretch(4, 5)
            form_layout_tab3.addLayout(row_layout2)
        groupbox_tab3.setLayout(form_layout_tab3)
        box_layout_tab3 = QtWidgets.QVBoxLayout()
        box_layout_tab3.addWidget(groupbox_tab3)

        # form_layout2_tab3 = QtWidgets.QVBoxLayout()  # 邻井压力表单单独列出来
        # groupbox2_tab3 = QtWidgets.QGroupBox('邻井压力', self.ui.tab_3)
        # groupbox2_tab3.setFixedHeight(95)
        # # 循环生成邻井压力的字段
        # for i in range(0, len(linjing_labels), 2):
        #     row_layout3 = QHBoxLayout()
        #     row_layout3.setAlignment(Qt.AlignRight)  # 设置对齐方式为左对齐
        #     for j in range(2):
        #         if i + j < len(linjing_labels):
        #             label = QLabel(linjing_labels[i + j], self.ui.tab_3)
        #             combo_box = QComboBox()
        #             combo_box.addItems([''])
        #             combo_box.addItems([str(x) for x in range(1, 19)])
        #             combo_box.setCurrentIndex(-1)
        #             setattr(self, f"label_{linjing_labels[i + j]}", label)
        #             setattr(self, f"comboBox_{linjing_labels[i + j]}_", combo_box)
        #             dic_ = {}
        #             dic_['label'] = str(label.text())
        #             dic_['value'] = ''
        #             dic_['combo_box'] = combo_box
        #             self.dict_label_combox_db.append(dic_)
        #
        #             label.setFixedHeight(25)
        #             label.setFixedWidth(80)
        #             label.setAlignment(Qt.AlignCenter)
        #             combo_box.setFixedHeight(25)
        #             row_layout3.addWidget(label)
        #             row_layout3.addWidget(combo_box)
        #         if j == 0:
        #             row_layout3.addItem(QSpacerItem(30, 1, QSizePolicy.Fixed, QSizePolicy.Minimum))
        #     row_layout3.setStretch(0, 1)
        #     row_layout3.setStretch(1, 5)
        #     row_layout3.setStretch(2, 5)
        #     row_layout3.setStretch(3, 1)
        #     row_layout3.setStretch(4, 5)
        #     form_layout2_tab3.addLayout(row_layout3)
        # groupbox2_tab3.setLayout(form_layout2_tab3)
        # box_layout2_tab3 = QtWidgets.QVBoxLayout()
        # box_layout2_tab3.addWidget(groupbox2_tab3)

        button_layout = QHBoxLayout(self.second_point_container)
        self.pushButton_start_receive = QPushButton('开始接收', self.second_point_container)
        self.pushButton_stop_receive = QPushButton('停止接收', self.second_point_container)
        button_layout.addWidget(self.pushButton_start_receive)
        button_layout.addWidget(self.pushButton_stop_receive)
        self.pushButton_start_receive.setFixedHeight(38)
        self.pushButton_stop_receive.setFixedHeight(38)
        button_layout.setSpacing(40)

        # 黏度部分：放入单独容器，仅用于「黏度数据采集」弹窗
        self.viscosity_container = QWidget()
        self.viscosity_container.setObjectName("viscosity_container")
        viscosity_layout = QVBoxLayout(self.viscosity_container)
        label_layout_tab6 = QHBoxLayout(self.viscosity_container)
        label_port_tab6 = QLabel('串口号(黏/密度)', self.viscosity_container)
        self.comboBox_port_tab6 = QtWidgets.QComboBox()
        self.comboBox_port_tab6.setObjectName("comboBox_port_tab6")
        self.comboBox_port_tab6.setFixedHeight(27)
        self.comboBox_port_tab6.setEditable(True)
        label_layout_tab6.addWidget(label_port_tab6)
        label_layout_tab6.addWidget(self.comboBox_port_tab6)
        label_layout_tab6.setStretch(0, 1)
        label_layout_tab6.setStretch(1, 8)
        for item in port_list:
            self.comboBox_port_tab6.addItem(item)
            self.comboBox_port_tab6.setCurrentIndex(-1)

        # 液体类型
        liquid_layout = QHBoxLayout(self.viscosity_container)
        liquid_port = QLabel('选择液体类型', self.viscosity_container)
        self.comboBox_port_tab8 = QtWidgets.QComboBox()
        self.comboBox_port_tab8.setObjectName("comboBox_port_tab8")
        self.comboBox_port_tab8.setFixedHeight(27)
        self.comboBox_port_tab8.setEditable(True)
        liquid_layout.addWidget(liquid_port)
        liquid_layout.addWidget(self.comboBox_port_tab8)
        liquid_layout.setStretch(0, 1)
        liquid_layout.setStretch(1, 8)
        for item in liquid_list:
            self.comboBox_port_tab8.addItem(item)
            self.comboBox_port_tab8.setCurrentIndex(-1)

        button_layout_tab6 = QHBoxLayout(self.viscosity_container)
        self.btn_start_tab6 = QPushButton('开始接收', self.viscosity_container)
        self.btn_stop_tab6 = QPushButton('停止接收', self.viscosity_container)
        button_layout_tab6.addWidget(self.btn_start_tab6)
        button_layout_tab6.addWidget(self.btn_stop_tab6)
        self.btn_start_tab6.setFixedHeight(38)
        self.btn_stop_tab6.setFixedHeight(38)
        button_layout_tab6.setSpacing(40)

        button2_layout_tab6 = QHBoxLayout(self.viscosity_container)
        self.btn2_start_tab6 = QPushButton('开始上传', self.viscosity_container)
        self.btn2_stop_tab6 = QPushButton('结束', self.viscosity_container)
        button2_layout_tab6.addWidget(self.btn2_start_tab6)
        button2_layout_tab6.addWidget(self.btn2_stop_tab6)
        self.btn2_start_tab6.setFixedHeight(38)
        self.btn2_stop_tab6.setFixedHeight(38)
        button2_layout_tab6.setSpacing(40)
        # 黏度数据采集弹窗不显示「开始上传」「结束」按钮
        self.btn2_start_tab6.setVisible(False)
        self.btn2_stop_tab6.setVisible(False)

        second_point_layout.addLayout(port_layout)
        second_point_layout.addLayout(box_layout_tab3)
        second_point_layout.addLayout(button_layout)
        self.ui.second_point_dialog_container_layout.insertWidget(0, self.second_point_container, stretch=4)
        self.ui.second_point_container = self.second_point_container
        self.ui.second_point_dialog_container_layout.insertWidget(0, self.second_point_container, stretch=4)
        self.ui.second_point_container = self.second_point_container
        viscosity_layout.addLayout(label_layout_tab6)
        viscosity_layout.addLayout(liquid_layout)
        viscosity_layout.addLayout(button_layout_tab6)
        self.ui.viscosity_dialog_container_layout.addWidget(self.viscosity_container, stretch=4)
        self.ui.viscosity_dialog_container_layout.addWidget(self.ui.groupBox3, stretch=3)
        self.ui.viscosity_container = self.viscosity_container
        self._init_local_plot_tab()

    # 过滤井号
    # def filter_wellname(self):
    #     platform_name = self.ui.comboBox_platform.currentText()
    #     prefix = platform_name.split('井')[0]
    #     filtered_list = list(filter(lambda item: item.startswith(prefix), self.well_names))
    #     self.ui.comboBox_well.clear()
    #     for item in filtered_list:
    #         self.ui.comboBox_well.addItem(str(item))
    #         self.ui.comboBox_well.setCurrentIndex(-1)
    def filter_wellname(self):
        # 区块/井台/井号已改为纯文本输入，不再根据井台过滤井号
        return

    # 根据仪表车厂家获取数据发送字段
    def get_field(self):
        for data in self.dict_label_combox_db:
            data['combo_box'].setCurrentIndex(-1)
        config = configparser.ConfigParser()
        try:
            config.read('config.ini', encoding='utf-8')
        except UnicodeDecodeError:
            config.read('config.ini', encoding='gbk')
        if 'measuring_truck_field_settings' in config:
            params = config['measuring_truck_field_settings']
            crew_name = self.ui.comboBox_measuring_truck.currentText()
            str_ = ''
            if crew_name == '宏华':
                str_ = 'HongHua'
            if crew_name == '杰瑞':
                str_ = 'JieRui'
            if crew_name == '三一重工':
                str_ = 'SanYi'
            if crew_name == '四机厂':
                str_ = 'SiJi'
            field_names_str = params.get(f"field_names_{str_}", '')  # 获取 field_names 字符串
            # 将 field_names 字符串转换为列表
            field_names = [field.strip() for field in field_names_str.split(',')]
            print(field_names)
            for data in self.dict_label_combox_db:
                label = data['label']
                try:
                    # 查找 label 在 field_names 中的索引
                    index = field_names.index(label)
                    print(f"Label '{label}' 在 field_names 中的索引是: {index}")
                    data['combo_box'].setCurrentIndex(index + 1)
                    data['value'] = index + 1
                except ValueError:
                    # 如果 label 不在 field_names 中
                    print(f"Label '{label}' 不在 field_names 中")
            print(self.dict_label_combox_db)

    # 获取所有串口号
    def get_all_ports(self):
        # 获取所有串口信息
        ports = serial.tools.list_ports.comports()
        # 提取串口名称
        port_list = [port.device for port in ports]
        return port_list

    def get_liquid_parameter(self):
        # 从配置文件加载参数
        config = configparser.ConfigParser()
        try:
            config.read('config.ini', encoding='utf-8')
        except UnicodeDecodeError:
            config.read('config.ini', encoding='gbk')
        liquid_list = []  # 默认空列表
        if 'liquid_list' in config:
            params = config['liquid_list']
            if 'liquid_styles' in params:
                # 使用逗号分割字符串并去除空格
                liquid_str = params['liquid_styles']
                liquid_list = [item.strip() for item in liquid_str.split(',')]
        return liquid_list
    def refresh_liquid_list(self):
        """从 config.ini 重新读取液体类型并刷新「粘度数据采集」里的液体类型下拉框，保存后不重启即可生效。"""
        liquid_list = self.get_liquid_parameter()
        self.comboBox_port_tab8.clear()
        self.comboBox_port_tab8.addItem('')
        for item in liquid_list:
            self.comboBox_port_tab8.addItem(item)
        self.comboBox_port_tab8.setCurrentIndex(0)
    # 液体类型中文名 -> config.ini [calibration_parameter] 键名（与 thread 中一致）
    def show_liquid_calibration_dialog(self):
        """编辑液体类型：查看/增加液体类型、修改 k 和 b 值。"""
        LIQUID_NAME_TO_KEY = {
            '滑溜水': 'slippery_water',
            '胍胶': 'gua_gum',
            '交联胶': 'jiaolian_gum',
            '线性胶': 'xianxing_gum',
            '盐酸': 'muriatic_acid',
        }
        try:
            config = configparser.ConfigParser()
            try:
                config.read('config.ini', encoding='utf-8')
            except UnicodeDecodeError:
                config.read('config.ini', encoding='gbk')
        except Exception as e:
            QMessageBox.warning(self, '提示', '读取 config.ini 失败：' + str(e))
            return

        try:
            liquid_names = []
            if 'liquid_list' in config and 'liquid_styles' in config['liquid_list']:
                liquid_str = config['liquid_list']['liquid_styles']
                liquid_names = [s.strip() for s in liquid_str.split(',') if s.strip()]
            calib = {}
            if 'calibration_parameter' in config:
                calib = dict(config['calibration_parameter'])
            default_kb = {'k': 1.0, 'b': 0.3}
            if 'default' in calib:
                try:
                    default_kb = json.loads(calib['default'])
                except Exception:
                    pass
            rows = []
            for i, name in enumerate(liquid_names):
                key = LIQUID_NAME_TO_KEY.get(name, 'liquid_' + str(i + 1))
                raw = calib.get(key, calib.get('default', '{"k":1, "b":0.3}'))
                try:
                    kb = json.loads(raw)
                    k_val = float(kb.get('k', default_kb.get('k', 1.0)))
                    b_val = float(kb.get('b', default_kb.get('b', 0.3)))
                except Exception:
                    k_val = default_kb.get('k', 1.0)
                    b_val = default_kb.get('b', 0.3)
                rows.append([name, k_val, b_val])

            dlg = QDialog(self)
            dlg.setWindowTitle('液体类型与校准参数（k、b 值）')
            dlg.setMinimumSize(480, 320)
            layout = QVBoxLayout(dlg)

            table = QTableWidget()
            table.setColumnCount(3)
            table.setHorizontalHeaderLabels(['液体类型', 'k 值', 'b 值'])
            table.setRowCount(len(rows))
            table.horizontalHeader().setStretchLastSection(True)
            for i, (name, k, b) in enumerate(rows):
                table.setItem(i, 0, QTableWidgetItem(str(name)))
                table.setItem(i, 1, QTableWidgetItem(str(k)))
                table.setItem(i, 2, QTableWidgetItem(str(b)))
            for r in range(table.rowCount()):
                for c in range(3):
                    item = table.item(r, c)
                    if item is not None:
                        item.setFlags(item.flags() | Qt.ItemIsEditable)

            def add_row():
                row = table.rowCount()
                table.insertRow(row)
                table.setItem(row, 0, QTableWidgetItem(''))
                table.setItem(row, 1, QTableWidgetItem('1'))
                table.setItem(row, 2, QTableWidgetItem('0.3'))
                for c in range(3):
                    it = table.item(row, c)
                    if it is not None:
                        it.setFlags(it.flags() | Qt.ItemIsEditable)

            def save_to_config():
                try:
                    names = []
                    calib_items = []
                    for r in range(table.rowCount()):
                        name_item = table.item(r, 0)
                        k_item = table.item(r, 1)
                        b_item = table.item(r, 2)
                        name = (name_item.text() if name_item else '').strip()
                        if not name:
                            QMessageBox.warning(dlg, '提示', '第 %d 行液体类型不能为空。' % (r + 1))
                            return
                        try:
                            k_val = float(k_item.text() if k_item else '1')
                        except ValueError:
                            QMessageBox.warning(dlg, '提示', '第 %d 行 k 值必须是数字。' % (r + 1))
                            return
                        try:
                            b_val = float(b_item.text() if b_item else '0.3')
                        except ValueError:
                            QMessageBox.warning(dlg, '提示', '第 %d 行 b 值必须是数字。' % (r + 1))
                            return
                        names.append(name)
                        key = LIQUID_NAME_TO_KEY.get(name, 'liquid_' + str(r + 1))
                        calib_items.append((key, json.dumps({'k': k_val, 'b': b_val})))
                    cfg = configparser.ConfigParser()
                    try:
                        cfg.read('config.ini', encoding='utf-8')
                    except UnicodeDecodeError:
                        cfg.read('config.ini', encoding='gbk')
                    if 'liquid_list' not in cfg:
                        cfg.add_section('liquid_list')
                    cfg['liquid_list']['liquid_styles'] = ', '.join(names)
                    if 'calibration_parameter' not in cfg:
                        cfg.add_section('calibration_parameter')
                    if 'default' not in cfg['calibration_parameter']:
                        cfg['calibration_parameter']['default'] = '{"k":1, "b":0.3}'
                    for key, val in calib_items:
                        cfg['calibration_parameter'][key] = val
                    with open('config.ini', 'w', encoding='utf-8') as f:
                        cfg.write(f)
                    self.refresh_liquid_list()
                    QMessageBox.information(dlg, '提示', '已保存到 config.ini。')
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    QMessageBox.warning(dlg, '错误', '保存失败：' + str(e))

            btn_layout = QHBoxLayout()
            btn_add = QPushButton('增加液体类型')
            btn_add.clicked.connect(add_row)
            btn_save = QPushButton('保存')
            btn_save.clicked.connect(save_to_config)
            btn_close = QPushButton('关闭')
            btn_close.clicked.connect(dlg.close)
            btn_layout.addWidget(btn_add)
            btn_layout.addWidget(btn_save)
            btn_layout.addWidget(btn_close)
            layout.addWidget(table)
            layout.addLayout(btn_layout)
            dlg.setAttribute(Qt.WA_DeleteOnClose)
            dlg.show()
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.warning(self, '错误', '打开编辑液体类型失败：' + str(e))
    # 复选框发生变化时执行
    # def on_radio_button_changed(self):
    #     if self.ui.radioButton_direct_transmission.isChecked():
    #         # 选择直传，数字表示选项卡索引，从左到右 0、1、2、3
    #         self.ui.tabWidget.setTabVisible(1, True)
    #         self.ui.tabWidget.setTabVisible(2, False)
    #     elif self.ui.radioButton_indirect_transmission.isChecked():
    #         # 选择转传
    #         self.ui.tabWidget.setTabVisible(1, False)
    #         self.ui.tabWidget.setTabVisible(2, True)

    # 传输方式单选变化时执行：仅“软件直传”时显示“上传数据”选项卡，“串口转传”时隐藏
    def on_radio_button_changed(self):
        # 用控件引用取索引，避免选项卡顺序变化导致藏错/显错
        idx_upload = self.ui.tabWidget.indexOf(self.ui.tab_2)  # 上传数据
        idx_second = self.ui.tabWidget.indexOf(self.ui.tab_3)  # 施工秒点数据、液体性能数据
        if self.ui.radioButton_direct_transmission.isChecked():
            # 软件直传：显示“上传数据”，隐藏“施工秒点数据、液体性能数据”
            self.ui.tabWidget.setTabVisible(idx_upload, True)
            self.ui.tabWidget.setTabVisible(idx_second, False)
        elif self.ui.radioButton_indirect_transmission.isChecked():
            # 串口转传：隐藏“上传数据”，显示“施工秒点数据、液体性能数据”
            self.ui.tabWidget.setTabVisible(idx_upload, False)
            self.ui.tabWidget.setTabVisible(idx_second, True)
        else:
            # 兜底：两者都未选中时保持上传数据隐藏
            self.ui.tabWidget.setTabVisible(idx_upload, False)
            self.ui.tabWidget.setTabVisible(idx_second, True)


    # 向后端api发送请求@@@ ?? 单机版占位实现，不再真正访问服务器
    def base_API(self, dic_):
        """
        单机版：不再请求任何后端接口，统一返回本地默认空数据结构，
        以保证 init_data 等逻辑在没有网络时也不会崩溃。
        后续会逐步移除对这些数据的依赖。
        """
        return {
            'platform_name': [],
            'blocklist': [],
            'measure_trucks': [],
            'crew_names': [],
            'gate_way_devices': [],
            'column_cname': [],
        }

    # 根据区块，获取井号  返回[大吉-平52井第1次压裂,大吉-平41井第1次压裂]@@@
    # def get_wells(self):
    #     try:
    #         block_name = self.ui.comboBox_block.currentText()
    #         rel = self.base_API({'url': '/get_well', 'method': 'POST', 'data': {'block': block_name}})
    #         well_names = rel['frac_wellnames']
    #         self.well_names = well_names
    #         # self.ui.comboBox_well.clear()
    #         platform_name = self.ui.comboBox_platform.currentText()
    #         # if platform_name == '':
    #         #     QMessageBox.information(self.ui.centralwidget, '提示', "请选择井台！")
    #         #     return
    #         # else:
    #         prefix = platform_name.split('井')[0]
    #         filtered_list = list(filter(lambda item: item.startswith(prefix), well_names))
    #         for item in filtered_list:
    #             self.ui.comboBox_well.addItem(str(item))
    #         # for item in well_names:
    #         #     self.ui.comboBox_well.addItem(str(item))
    #         self.ui.comboBox_well.setCurrentIndex(-1)  # 这样初始值为空，不会默认选中第一个
    #         self.ui.comboBox_well.currentTextChanged.connect(self.get_layerofwell)
    #     except Exception as e:
    #         import traceback
    #         print("An error occurred:")
    #         # 完整的堆栈跟踪信息，包括触发异常的代码行，从而定位到错误出现的具体位置。
    #         traceback.print_exc()
    #         print(f'异常为：{e}')
    def get_wells(self):
        # 区块/井台/井号已改为纯文本输入，不再从接口拉取井号列表
        return

    # 根据井号  根据区块，井号  返回压裂次数,层位@@@
    # def get_layerofwell(self):
    #     try:
    #         well_name = self.ui.comboBox_well.currentText()
    #         rel = self.base_API({'url': '/get_layers', 'method': 'POST', 'data': {'well': well_name}})
    #         self.ui.comboBox_layer.clear()
    #         self.ui.comboBox_frac_num.clear()
    #         for item in rel['layer_list']:
    #             self.ui.comboBox_layer.addItem(item)
    #         for i in rel['frac_num']:
    #             self.ui.comboBox_frac_num.addItem(str(i))
    #         self.ui.comboBox_layer.setCurrentIndex(-1)  # 这样初始值为空，不会默认选中第一个
    #         self.ui.comboBox_frac_num.setCurrentIndex(-1)  # 这样初始值为空，不会默认选中第一个
    #         self.ui.comboBox_layer.currentTextChanged.connect(self.get_period)
    #     except Exception as e:
    #         print(f'异常为：{e}')
    #         import traceback
    #         print("An error occurred:")
    #         # 完整的堆栈跟踪信息，包括触发异常的代码行，从而定位到错误出现的具体位置。
    #         traceback.print_exc()
    def get_layerofwell(self):
        # 井号/层位/压裂次数已改为纯文本输入，不再从接口拉取层位与压裂次数
        return

    # 根据井号，层位，第几次压裂，返回总段数@@@
    # def get_period(self):
    #     try:
    #         # 先读取当前井号和压裂次数
    #         well_name = self.ui.comboBox_well.currentText()
    #         frac_num = self.ui.comboBox_frac_num.currentText()
    #
    #         # 如果井号或压裂次数任一为空，则不向后端请求，直接清空段列表并返回
    #         if (not well_name) or (not frac_num):
    #             self.ui.comboBox_period.clear()
    #             return
    #
    #         # 只有在井号和压裂次数都有有效值时，才调用后端接口获取段数
    #         rel = self.base_API({
    #             'url': '/get_period',
    #             'method': 'POST',
    #             'data': {'well': well_name, 'frac_num': frac_num}
    #         })
    #
    #         # 用返回的 num_period 列表填充段/级编号下拉框
    #         self.ui.comboBox_period.clear()
    #         for i in rel.get('num_period', []):
    #             self.ui.comboBox_period.addItem(str(i))
    #         # 初始不默认选中任何一项
    #         self.ui.comboBox_period.setCurrentIndex(-1)
    #
    #     except Exception as e:
    #         print(f'异常为：{e}')
    #         import traceback
    #         print("An error occurred:")
    #         # 完整的堆栈跟踪信息，包括触发异常的代码行，从而定位到错误出现的具体位置。
    #         traceback.print_exc()
    def get_period(self):
        # 段/级编号已改为纯文本输入，不再从接口拉取段号列表
        return

    # 选择仪表车数据库文件路径@@@
    def openFileDialog(self):
        # options = QFileDialog.Options()
        # 设置文件筛选器，允许选择 .mdb, .db 类型的文件
        file_types = "DataBase Files (*.mdb *.db);;Excel Files (*.xlsx *.xls)"
        file_path, _ = QFileDialog.getOpenFileName(self.ui.centralwidget, "选择文件", ".", file_types)
        if file_path:
            print("选择的文件路径：", file_path)
            self.file_path = file_path
            # self.ui.file_label.setText('选择成功')
            self.ui.textEdit.append('已选择文件：' + file_path)
            self.update_local_plot_source()
        else:
            pass
            # self.ui.file_label.setText('未选择文件')

    # 选择上个选项卡中暂存的db文件
    def openFileDialog_tab4(self):
        # options = QFileDialog.Options()
        # 设置文件筛选器，允许选择 .mdb, .db 类型的文件
        file_types = "DataBase Files (*.mdb *.db);;Excel Files (*.xlsx *.xls)"
        file_path, _ = QFileDialog.getOpenFileName(self.ui.centralwidget, "选择文件", ".", file_types)
        if file_path:
            print("选择的文件路径：", file_path)
            self.file_path = file_path
            self.ui.textEdit.append('已选择文件：' + file_path)
        else:
            pass
            # self.ui.file_label.setText('未选择文件')

    # 获取现场数据库文件表头@@@
    def get_columns(self):
        try:
            crewname = self.ui.comboBox_measuring_truck.currentText()
            file_path = self.file_path
            if not file_path:
                QMessageBox.warning(self.ui.centralwidget, '警告', '请先选择文件！')
                return
            if not crewname:
                QMessageBox.warning(self.ui.centralwidget, '警告', '请先选择仪表车厂家！')
                return
            columns_list = []
            print('走到杰瑞之前了')

            if crewname == '杰瑞':
                #原版代码
                # conn_str = r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=" + file_path
                # print(f'conn_str={conn_str}')
                # conn = pyodbc.connect(conn_str)
                # print('连接建立成功')
                # #创建游标对象
                # cursor = conn.cursor()
                # select_query = 'SELECT * FROM LogData'
                # #执行查询
                # cursor.execute(select_query)


                conn = sqlite3.connect(file_path)
                print('连接建立成功')
                # 创建游标对象
                cursor = conn.cursor()
                select_query = 'SELECT * FROM LogData'
                # 执行查询
                cursor.execute(select_query)

                # 获取字段名
                # columns_info是列表，各元素是元组 = [（id，type,...）, () , ...]
                columns_info = cursor.description
                # columns = [column[0] for column in cursor.description]
                print(f'columns_info={columns_info}')

                # 使用pandas库的read_sql_query可以查询出带表头结果
                #df = pd.read_sql_query("SELECT * FROM LogData", conn)
                # print(df)
                # 获取表头
                # columns_list = df.columns.tolist()
                #columns_list是列表 = [id,date,time,...]
                columns_list = [item[0] for item in columns_info]
                print(f'columns_list={columns_list}')

                self.columns_info = columns_info
                # print(f'columns_list={columns_list}')
                conn.close()

            elif crewname == '三一重工':
                df_list = []
                with open(file_path, 'r', encoding='utf-8') as file:
                    reader = csv.reader(file)
                    for row in reader:
                        # 在这里处理每一行的字段
                        df_list.append(row)

                columns_list = df_list[0]

            elif crewname == '中油科昊':
                # 连接到数据库文件
                conn = sqlite3.connect(file_path)  # 替换为你的数据库文件路径

                fname = os.path.basename(file_path).split('层')[1].split('.')[0]
                # 使用pandas库的read_sql_query可以查询出带表头结果
                query = "SELECT * FROM history_data_{}".format(fname)
                # query = "SELECT name FROM sqlite_master WHERE type='table'"
                df = pd.read_sql_query(query, conn)
                # 获取表头
                columns_list = df.columns.tolist()
                print(f'columns_list={columns_list}')
                conn.close()

            for item in self.label_combo_dict:
                # comboBox = item['combo_box']
                label = item['label']
                comboBox = getattr(self, f'comboBox_{label}')
                comboBox.clear()
                # print('combox已清空')
                comboBox.addItems(columns_list)
                comboBox.setCurrentIndex(-1)  # 这样初始值为空，不会默认选中第一个
                # 字典使用item.values时dict_values类型的数据，需要转为list取值
                # 将当前选中的索引与槽函数关联
                comboBox.currentTextChanged.connect(self.handle_currentIndexChanged)
            QMessageBox.information(self.ui.centralwidget, '提示', "获取成功!\n请至少选择'套管压力'、'套管排量'、'砂比'三项所对应的列名")
        except Exception as e:
            print(f'异常为{e}')
            QMessageBox.warning(self, '警告', '请选择正确的设备厂家！')

    # 当字段combobox选择改变时的槽函数@@@
    def handle_currentIndexChanged(self):
        try:
            sender = self.ui.centralwidget.sender()
            # 遍历字典列表，找到对应的标签和下拉框
            for item in self.label_combo_dict:
                # print(label,combo_box)
                label = item['label']
                combo_box = item['combo_box']
                if sender == combo_box:
                    selected_option = combo_box.currentText()
                    # print(f"选择了 '{selected_option}'，与标签 '{label}' 对应")
                    item['value'] = selected_option
                    values_list = list(filter(lambda x: x['value'] != '', self.label_combo_dict))
                    values_list = [item['value'] for item in values_list]
                    if len(values_list) != len(set(values_list)):
                        combo_box.setCurrentIndex(-1)
                        item['value'] = ''
                        QMessageBox.warning(self.ui.centralwidget, '警告', '不能选择重复的列！')
        except Exception as e:
            import traceback
            print("An error occurred:")
            # 完整的堆栈跟踪信息，包括触发异常的代码行，从而定位到错误出现的具体位置。
            traceback.print_exc()

    # 上传井信息按钮槽函数@@@
    # 单机版：保存井信息按钮槽函数
    def save_wellinfo(self):
        """
        单机版逻辑：
        - 校验井信息是否填写完整；
        - 让用户确认当前井段信息；
        - 本地保存井信息到 config.ini；
        - 设置 state_code = '1002'，用于解锁后续选项卡；
        - 在“井信息状态栏”中追加提示。
        """
        try:
            if not self.ui.lineEdit_block.text().strip():
                QMessageBox.warning(self.ui.centralwidget, '提示', '请填写区块！')
                return
            elif not self.ui.lineEdit_platform.text().strip():
                QMessageBox.warning(self.ui.centralwidget, '提示', '请填写井台！')
                return
            elif not self.ui.lineEdit_well.text().strip():
                QMessageBox.warning(self.ui.centralwidget, '提示', '请填写井号！')
                return
            elif not self.ui.lineEdit_frac_num.text().strip():
                QMessageBox.warning(self.ui.centralwidget, '提示', '请填写压裂次数！')
                return
            elif not self.ui.lineEdit_layer.text().strip():
                QMessageBox.warning(self.ui.centralwidget, '提示', '请填写层位！')
                return
            elif not self.ui.lineEdit_period.text().strip():
                QMessageBox.warning(self.ui.centralwidget, '提示', '请填写段/级编号！')
                return
            elif not self.ui.comboBox_measuring_truck.currentText():
                QMessageBox.warning(self.ui.centralwidget, '警告', '请输入仪表车厂家！')
                return
            cur_crew = self.ui.comboBox_crew.currentText()
            cur_well = self.ui.lineEdit_well.text().strip()
            cur_frac_num = self.ui.lineEdit_frac_num.text().strip()
            cur_layer = self.ui.lineEdit_layer.text().strip()
            cur_period = self.ui.lineEdit_period.text().strip()
            mes_confirm = (
                    '确定要保存 ' + cur_well + ' 第' + cur_frac_num +
                    '次压裂 ' + cur_layer + ' 第' + cur_period + '段 的井信息吗？'
            )
            reply = QMessageBox.question(
                self.ui.centralwidget, '确认', mes_confirm,
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                # 单机版：只在本地保存井信息，并标记为“配置就绪”
                print('save_wellinfo: local only, state_code=1002')
                self.state_code = '1002'
                self.save_config()
                self.ui.textEdit.append('井信息已保存（单机版，本地配置）')
                self.ui.textEdit.append(
                    cur_well + '第' + cur_frac_num + '次压裂' + cur_layer + '第' + cur_period + '段'
                )
            else:
                # 用户取消，不做任何事
                pass
        except Exception as e:
            import traceback
            print("An error occurred:")
            traceback.print_exc()
            print(f'异常为：{e}')

    def show_well_info_dialog(self):
        # 每次显示前都把“井信息表单”和“井信息状态栏”从当前父布局摘出，再放进弹窗，避免关闭后再次打开为空
        def _detach(w):
            p = w.parentWidget()
            if p is None:
                return
            lay = p.layout()
            if lay is not None:
                lay.removeWidget(w)
        _detach(self.ui.tab)
        _detach(self.ui.groupBox1)
        if getattr(self, '_well_info_dialog', None) is None:
            self._well_info_dialog = WellInfoDialog(self.ui, self)
            self._well_info_dialog.destroyed.connect(lambda *_: setattr(self, '_well_info_dialog', None))
        else:
            # 再次打开：控件已在 closeEvent 里还回容器，需重新放进弹窗 layout
            lay = self._well_info_dialog.layout()
            if lay is not None:
                lay.addWidget(self.ui.tab, stretch=4)
                lay.addWidget(self.ui.groupBox1, stretch=3)
        self._well_info_dialog.show()
        self._well_info_dialog.raise_()
        self._well_info_dialog.activateWindow()

    def show_second_point_dialog(self):
        # 已经打开过：直接置前，不要重复搬控件/重复创建
        if getattr(self, "_second_point_dialog", None) is not None:
            if self._second_point_dialog.isVisible():
                self._second_point_dialog.raise_()
                self._second_point_dialog.activateWindow()
                return

        # 第一次打开：把控件从当前父布局里“摘下来”，再创建弹窗
        def _detach(w):
            p = w.parentWidget()
            if p is None:
                return
            lay = p.layout()
            if lay is not None:
                lay.removeWidget(w)

        _detach(self.ui.second_point_container)
        _detach(self.ui.groupBox2)
        self._second_point_dialog = SecondPointDialog(self.ui, self)
        # 关闭时把引用清掉，方便下次重新创建
        self._second_point_dialog.destroyed.connect(lambda *_: setattr(self, "_second_point_dialog", None))
        self._second_point_dialog.show()
        self._second_point_dialog.raise_()
        self._second_point_dialog.activateWindow()

    def show_viscosity_dialog(self):
        if getattr(self, "_viscosity_dialog", None) is not None:
            if self._viscosity_dialog.isVisible():
                self._viscosity_dialog.raise_()
                self._viscosity_dialog.activateWindow()
                return

        def _detach(w):
            p = w.parentWidget()
            if p is None:
                return
            lay = p.layout()
            if lay is not None:
                lay.removeWidget(w)

        _detach(self.ui.viscosity_container)
        _detach(self.ui.groupBox3)
        self._viscosity_dialog = ViscosityDialog(self.ui, self)
        self._viscosity_dialog.destroyed.connect(lambda *_: setattr(self, "_viscosity_dialog", None))
        self._viscosity_dialog.show()
        self._viscosity_dialog.raise_()
        self._viscosity_dialog.activateWindow()
    # 开始上传秒点数据@@@
    def start_upload(self):
        '''
        1、找不到这个井段的，前端提示，先上传井信息
        2、1002：可正常接收数据，则建立socket连接，客户端建立两个指针，指针实时存到配置文件中。不断向服务端发送L1与L2之间的数据。
        L2始终指向仪表车数据库中最新一条数据；L1:1)正常情况下，服务端回复我收到了L1-L2的数据后，状态码更新为1003，
        L1才指向仪表车数据库中最新一条数据，即L1=L2，2)若网络断开，收不到服务器的回复，状态码更新为1004，L1停在当前时间不更新。
        若是软件崩溃，重新打开的话，先读取一下配置文件，井号等信息课直接载入，读取指针信息，进行发送。
        3、1006：施工已结束，状态栏提示
        4、点击后，传输正常，变为正在上传(禁用)，断网变为重连中...
        5、若选网关转存，则无这个按钮，可禁用，处于一直连接状态。串口给服务器发送 时间+套压+排量+砂比+设备号。后端根据设备号查找施工_井段信息表中该井段的信息状态码，可能有多个，
        5.1、再找到状态码为1002的，若找到则和软件直传一样判断传输即可。若找不到，前端提示先上传井信息。
        5.2、上传井信息后，服务端新建空db文件，状态变为1002后，开始计时，若一直收到空或者全为0超过10分钟，状态变为1004，返回前端
        :return:
        '''

        cur_well = self.ui.lineEdit_well.text()
        cur_frac_num = self.ui.lineEdit_frac_num.text()
        cur_layer = self.ui.lineEdit_layer.text()
        cur_period = self.ui.lineEdit_period.text()

        if self.file_path == '':
            QMessageBox.warning(self.ui.centralwidget, '警告', "请先选择文件！")
            return

        # 解析仪表车数据库文件
        columns_info = ''
        if self.columns_info:
            print(f'传到后端前的columns_info={self.columns_info}')
            columns_info = [list(item) for item in self.columns_info]
        else:
            QMessageBox.warning(self.ui.centralwidget, '警告', '请先获取字段！')
            return

        # 至少要选择套管排量、套管排量、砂比三个参数对应的字段
        for item in self.label_combo_dict:
            if item['label'] == '砂比' and item['value'] == '':
                QMessageBox.warning(self.ui.centralwidget, '警告', "请选择'砂比'对应字段！")
                return
            elif item['label'] == '套管排量' and item['value'] == '':
                QMessageBox.warning(self.ui.centralwidget, '警告', "请选择'套管排量'对应字段！")
                return
            elif item['label'] == '套管压力' and item['value'] == '':
                QMessageBox.warning(self.ui.centralwidget, '警告', "请选择'套管压力'对应字段！")
                return

        try:

            for i in range(len(columns_info)):
                column_name = columns_info[i][0]  # 字段名
                column_type = columns_info[i][1]  # 数据类型

                # 如果用户选了将表头字段对应，数据库表头改为相应规范的名字，传给后端建临时db文件
                for item in self.label_combo_dict:
                    if item['value'] != '' and columns_info[i][0] == item['value']:
                        columns_info[i][0] = item['label']

                if columns_info[i][0][0].isdigit():
                    # print(f'{column_name}  第一个字符为数字')
                    columns_info[i][0] = '零' + columns_info[i][0][1:]
                if column_type == int:
                    columns_info[i][1] = 'INT'
                elif column_type == float:
                    columns_info[i][1] = 'FLOAT'
                elif column_type == datetime.datetime:
                    columns_info[i][1] = 'DATETIME'

                # for item in self.label_combo_dict:
                #     if item['value'] != '' and columns_info[i][0] == item['value']:
                #         columns_info[i][0] = item['label']
            # columns_info = [{'name': name, 'type': str(type_), 'nullable': nullable} for name, type_, _, _, _, _, nullable in columns_info]
            print(f'传到后端的columns_info={columns_info}')
            data = {
                'well': cur_well,
                'frac_num': cur_frac_num,
                'layer': cur_layer,
                'period': cur_period,
                'columns_info': columns_info
            }

            rel = self.base_API({'url': '/temp_db_build', 'method': 'POST', 'data': data})

        except Exception as e:
            import traceback
            print("An error occurred:")
            # 完整的堆栈跟踪信息，包括触发异常的代码行，从而定位到错误出现的具体位置。
            traceback.print_exc()
            print(f'异常为：{e}')

        self.start_thread()
        self.btn_start.setEnabled(False)
        self.btn_fileselect.setEnabled(False)
        self.btn_getcolumn.setEnabled(False)

    # 开始上传秒点数据@@@
    def start_upload_tab4(self):
        if self.file_path == '':
            cur_well = self.ui.lineEdit_well.text()
            cur_frac_num = self.ui.lineEdit_frac_num.text()
            cur_layer = self.ui.lineEdit_layer.text()
            cur_period = self.ui.lineEdit_period.text()
            # 创建的.db文件名
            file_name = cur_well + '第' + cur_frac_num + '次压裂' + cur_layer + '第' + cur_period + '段'
            # 文件夹路径 D盘 a_transmission_data 井号
            folder_path = 'C:/a_transmission_data/' + cur_well
            # folder_path = 'D:/a_transmission_data/' + cur_well
            temp_file_path = folder_path + '/' + file_name + '.db'

            # 检查文件是否存在
            if os.path.exists(temp_file_path):

                self.file_path = temp_file_path
                print('.db文件路径：' + self.file_path)
                conn = sqlite3.connect(self.file_path)
                print('连接建立成功')
                # 创建游标对象
                cursor = conn.cursor()
                select_query = 'SELECT * FROM LogData'
                # 执行查询
                cursor.execute(select_query)
                # 获取字段名
                # columns_info是列表，各元素是元组 = [（id，type,...）, () , ...]
                columns_info = cursor.description

                print(f'传到后端的columns_info={columns_info}')
                data = {
                    'well': cur_well,
                    'frac_num': cur_frac_num,
                    'layer': cur_layer,
                    'period': cur_period,
                    'columns_info': columns_info
                }

                # 向后端地址发送请求，在服务器上新建临时db文件
                rel = self.base_API({'url': '/temp_db_build', 'method': 'POST', 'data': data})
                cursor.close()
                conn.close()
                if rel['state_code'] == '1002':
                    # 开启上传数据的线程
                    self.start_thread()
                    # self.pushButton_start_upload.setEnabled(False)
                    # self.pushButton_stop_upload.setEnabled(True)
                    self.btn2_start_tab6.setEnabled(False)
                    self.btn2_stop_tab6.setEnabled(True)
                else:
                    QMessageBox.warning(self.ui.centralwidget, '警告', '服务器链接出错！')
                    return
            else:
                QMessageBox.warning(self.ui.centralwidget, '警告', '请开始接收数据！')
                return
        else:
            cur_well = self.ui.lineEdit_well.text()
            cur_frac_num = self.ui.lineEdit_frac_num.text()
            cur_layer = self.ui.lineEdit_layer.text()
            cur_period = self.ui.lineEdit_period.text()

            conn = sqlite3.connect(self.file_path)
            print('连接建立成功')
            # 创建游标对象
            cursor = conn.cursor()
            select_query = 'SELECT * FROM LogData'
            # 执行查询
            cursor.execute(select_query)
            # 获取字段名
            # columns_info是列表，各元素是元组 = [（id，type,...）, () , ...]
            columns_info = cursor.description

            print(f'传到后端的columns_info={columns_info}')
            data = {
                'well': cur_well,
                'frac_num': cur_frac_num,
                'layer': cur_layer,
                'period': cur_period,
                'columns_info': columns_info
            }
            # 向后端地址发送请求，在服务器上新建临时db文件
            rel = self.base_API({'url': '/temp_db_build', 'method': 'POST', 'data': data})
            cursor.close()
            conn.close()
            if rel['state_code'] == '1002':
                # 开启上传数据的线程
                self.start_thread()
                # self.pushButton_start_upload.setEnabled(False)
                # self.pushButton_stop_upload.setEnabled(True)
                self.btn2_start_tab6.setEnabled(False)
                self.btn2_stop_tab6.setEnabled(True)
            else:
                QMessageBox.warning(self.ui.centralwidget, '警告', '服务器链接出错！')
                return

    # 开始上传粘度、密度数据
    def start_upload_viscosity_data(self):
        if self.file_path == '':
            QMessageBox.warning(self.ui.centralwidget, '警告', '请先开始接收黏/密度数据！')
            return
        # 连接数据库，查看表是否存在
        if self.file_path != '':
            # 尝试连接数据库
            conn = sqlite3.connect(self.file_path)
            # 创建游标对象
            cursor = conn.cursor()
            # 查询所有表
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()
            # 检查是否存在 pointdata 表
            if ('ViscosityData',) not in tables:
                QMessageBox.warning(self.ui.centralwidget, '警告', '请先开始接收黏/密度数据！')
            cursor.close()
            conn.close()

        cur_well = self.ui.lineEdit_well.text()
        cur_frac_num = self.ui.lineEdit_frac_num.text()
        cur_layer = self.ui.lineEdit_layer.text()
        cur_period = self.ui.lineEdit_period.text()
        conn = sqlite3.connect(self.file_path)
        print('连接建立成功')
        # 创建游标对象
        cursor = conn.cursor()
        select_query = 'SELECT * FROM ViscosityData'
        # 执行查询
        cursor.execute(select_query)
        # 获取字段名
        # columns_info是列表，各元素是元组 = [（id，type,...）, () , ...]
        columns_info = cursor.description

        print(f'传到后端的columns_info={columns_info}')
        data = {
            'well': cur_well,
            'frac_num': cur_frac_num,
            'layer': cur_layer,
            'period': cur_period,
            'columns_info': columns_info
        }

        # 向后端地址发送请求，在服务器上新建临时db文件
        rel = self.base_API({'url': '/temp_db_build_two', 'method': 'POST', 'data': data})
        cursor.close()
        conn.close()
        if rel['state_code'] == '1002':
            # 开启上传数据的线程
            # 开启上传数据的线程
            self.start_viscosity_data_thread()
            self.btn2_start_tab6.setEnabled(False)
            self.btn2_stop_tab6.setEnabled(True)
        else:
            QMessageBox.warning(self.ui.centralwidget, '警告', '服务器链接出错！')
            return

    # 启动线程@@@
    def start_thread(self):
        cur_well = self.ui.lineEdit_well.text()
        cur_frac_num = self.ui.lineEdit_frac_num.text()
        cur_layer = self.ui.lineEdit_layer.text()
        cur_period = self.ui.lineEdit_period.text()
        point_1 = self.point_1
        point_2 = self.point_2
        well_info = cur_well + '第' + cur_frac_num + '次压裂' + cur_layer + '第' + cur_period + '段'
        try:
            self.worker_thread = WorkerThread(self.file_path, well_info, point_1, point_2, self.jwt_token)
            self.worker_thread.start()
            self.worker_thread.update_ui_signal.connect(self.thread_finished)
            self.worker_thread.send_mesage_signal.connect(self.update_send_mes)
            self.worker_thread.connect_status_signal.connect(self.update_status)

        except Exception as e:
            print(f'开启线程时出现异常 e={e}')

    # 启动上传粘度、密度数据的线程
    def start_viscosity_data_thread(self):
        cur_well = self.ui.lineEdit_well.text()
        cur_frac_num = self.ui.lineEdit_frac_num.text()
        cur_layer = self.ui.lineEdit_layer.text()
        cur_period = self.ui.lineEdit_period.text()
        point_1 = self.viscosity_point_1
        point_2 = self.viscosity_point_2
        well_info = cur_well + '第' + cur_frac_num + '次压裂' + cur_layer + '第' + cur_period + '段'
        try:
            self.Upload_Viscosity_Thread = UploadViscosityThread(self.file_path, well_info, point_1, point_2, self.jwt_token)
            self.Upload_Viscosity_Thread.start()
            self.Upload_Viscosity_Thread.update_ui_signal.connect(self.thread_finished_2)
            self.Upload_Viscosity_Thread.send_mesage_signal.connect(self.update_send_mes_2)
            self.Upload_Viscosity_Thread.connect_status_signal.connect(self.update_status)
        except Exception as e:
            print(f'开启线程时出现异常 e={e}')

    # 线程出错后，接收发出的信号，尝试重连@@@
    def thread_finished(self, point_1, point_2):
        print('接收到线程出错发出的信号了')
        if self.worker_thread is not None:
            self.worker_thread.terminate()  # 终止线程
        self.point_1 = point_1
        self.point_2 = point_2
        time.sleep(1)
        now_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.ui.textEdit2.append(str(now_time) + ' 重连中')
        self.start_thread()

    # 线程出错后，接收发出的信号，尝试重连@@@
    def thread_finished_2(self, point_1, point_2):
        print('接收到线程出错发出的信号了')
        if self.worker_thread is not None:
            self.worker_thread.terminate()  # 终止线程
        self.viscosity_point_1 = point_1
        self.viscosity_point_2 = point_2
        time.sleep(1)
        now_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.ui.textEdit.append(str(now_time) + ' 重连中')
        self.start_viscosity_data_thread()

    # 每次发送成功后，接收线程发的成功信号，添加到状态栏，并将point_1,point_2保存到配置文件中@@@
    def update_send_mes(self, mes, point_1, point_2):
        now_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S' )
        self.ui.textEdit2.append(str(mes))
        # 更新最新的point_1 和 point_2
        self.point_1 = point_1
        self.point_2 = point_2
        # 保存到配置文件中
        self.save_config()

    # 每次发送成功后，接收线程发的成功信号，添加到状态栏，并将point_1,point_2保存到配置文件中@@@
    def update_send_mes_2(self, mes, point_1, point_2):
        now_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        # 黏度/密度上传状态写入第三栏（黏度数据状态栏）
        self.ui.textEdit3.append(str(mes))
        # 更新最新的point_1 和 point_2
        self.viscosity_point_1 = point_1
        self.viscosity_point_2 = point_2
        # 保存到配置文件中
        self.save_config()

    # 显示websocket的连接状态：连接成功、出错 、重连等
    def update_status(self, msg):
        self.ui.textEdit2.append(str(msg))

    def update_status_water(self, msg):
        self.ui.textEdit3.append(str(msg))

    # 读取数据库文件
    def read_db(self, query_str):
        measuring_truck = self.ui.comboBox_measuring_truck.currentText()
        if measuring_truck == '杰瑞':
            conn_str = r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=" + self.file_path
            conn = pyodbc.connect(conn_str)
            # 创建游标对象
            cursor = conn.cursor()
            # 执行查询
            cursor.execute(query_str)
            # 获取字段名
            columns = [column[0] for column in cursor.description]
            # 获取结果
            rows = cursor.fetchall()
            # 遍历结果
            # for row in rows:
            #     print(row)

            # 关闭游标
            cursor.close()
            # 关闭连接
            conn.close()

            return rows

        return []

    # 初始化本地秒点曲线Tab，创建一个新的QWidget作为该Tab页（左曲线+右表格）
    def _init_local_plot_tab(self):
        plot_container = QWidget()
        main_layout = QHBoxLayout(plot_container)
        # ========== 左侧：曲线 + 刷新按钮 ==========
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        # 曲线上端：套管压力、套管排量、砂比、粘度，每秒从 db 更新
        latest_row = QHBoxLayout()
        latest_row.setSpacing(20)
        for _ in range(4):
            latest_row.addSpacing(10)
        lb_p = QLabel('套管压力(MPa):', left_widget)
        self._label_latest_套管压力 = QLabel('--', left_widget)
        self._label_latest_套管压力.setMinimumWidth(60)
        lb_q = QLabel('套管排量:', left_widget)
        self._label_latest_套管排量 = QLabel('--', left_widget)
        self._label_latest_套管排量.setMinimumWidth(60)
        lb_s = QLabel('砂比:', left_widget)
        self._label_latest_砂比 = QLabel('--', left_widget)
        self._label_latest_砂比.setMinimumWidth(60)
        lb_v = QLabel('粘度(mPa \u00B7 s):', left_widget)
        self._label_latest_粘度 = QLabel('--', left_widget)
        self._label_latest_粘度.setMinimumWidth(60)
        latest_row.addWidget(lb_p)
        latest_row.addWidget(self._label_latest_套管压力)
        latest_row.addWidget(lb_q)
        latest_row.addWidget(self._label_latest_套管排量)
        latest_row.addWidget(lb_s)
        latest_row.addWidget(self._label_latest_砂比)
        latest_row.addWidget(lb_v)
        latest_row.addWidget(self._label_latest_粘度)
        latest_row.addStretch(1)
        left_layout.addLayout(latest_row)
        self.local_plot_widget = LocalPlotWidget(left_widget)
        left_layout.addWidget(self.local_plot_widget)
        button_layout = QHBoxLayout()
        self.btn_local_plot_refresh = QPushButton('刷新本地秒点曲线', left_widget)
        self.btn_y_axis_adjust = QPushButton('调整', left_widget)
        button_layout.addWidget(self.btn_local_plot_refresh)
        button_layout.addWidget(self.btn_y_axis_adjust)
        left_layout.addLayout(button_layout)
        self.btn_local_plot_refresh.clicked.connect(self.on_local_plot_refresh_clicked)
        self.btn_y_axis_adjust.clicked.connect(self._on_y_axis_adjust_clicked)
        main_layout.addWidget(left_widget, 3)
        # 每秒从当前 db 取最新一秒数据更新上端四组显示
        self._latest_data_timer = QTimer(self)
        self._latest_data_timer.setInterval(1000)
        self._latest_data_timer.timeout.connect(self._on_latest_data_timeout)
        self._latest_data_timer.start()
        # ========== 右侧：CSV 数据表格 ==========
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        # right_title_row = QHBoxLayout()
        # right_title = QLabel('由当前 db 转存的 CSV 数据（与左侧曲线同源）')
        # self.btn_save_plot_csv = QPushButton('保存csv文件', right_widget)
        # self.btn_save_plot_csv.setEnabled(False)
        # self.btn_save_plot_csv.clicked.connect(self._on_save_plot_csv_clicked)
        # right_title_row.addWidget(right_title)
        # right_title_row.addWidget(self.btn_save_plot_csv)
        # right_layout.addLayout(right_title_row)
        # self._plot_table = QTableWidget()
        right_title_row = QHBoxLayout()
        right_title = QLabel('由当前 db 转存的 CSV 数据（与左侧曲线同源）')
        # 保存csv按钮
        self.btn_save_plot_csv = QPushButton('保存csv文件', right_widget)
        self.btn_save_plot_csv.setEnabled(False)
        self.btn_save_plot_csv.clicked.connect(self._on_save_plot_csv_clicked)

        # 回到底部按钮：点击后表格滚动条滚到最下面，便于查看最新数据
        self.btn_scroll_plot_table_to_bottom = QPushButton('回到底部', right_widget)
        self.btn_scroll_plot_table_to_bottom.clicked.connect(self._on_scroll_plot_table_to_bottom_clicked)

        right_title_row.addWidget(right_title)
        right_title_row.addWidget(self.btn_save_plot_csv)
        right_title_row.addWidget(self.btn_scroll_plot_table_to_bottom)

        right_layout.addLayout(right_title_row)
        self._plot_table = QTableWidget()
        self._plot_table_processed_data = None  # (headers, rows) 供保存按钮使用
        self._plot_table.setAlternatingRowColors(True)
        # 前几列按内容自适应，最后一列拉伸占满右侧容器，消除空白
        # self._plot_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        # self._plot_table.horizontalHeader().setStretchLastSection(True)

        # 列宽：默认允许用户拖拽。最后一列仍拉伸填满剩余空间。
        header = self._plot_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)  # 所有列可横向拖拽
        header.setStretchLastSection(True)  # 最后一列自动拉伸

        # 标记：右侧 CSV 表只在首次填完数据后做一次“按内容自适应”列宽
        self._plot_table_resized_once = False

        right_layout.addWidget(self._plot_table)
        main_layout.addWidget(right_widget, 2)
        # 不再加入主窗口 tabWidget，改为放入弹窗“曲线绘制”
        self._plot_dialog = PlotDialog(self, plot_container)
        self.local_plot_widget.curve_data_updated.connect(self._on_curve_data_updated)
        self.ui.action_plot.triggered.connect(self.show_plot_dialog)
        # 历史曲线弹窗
        self._history_curve_dialog = HistoryCurveDialog(self)
        self.ui.action_history.triggered.connect(self.show_history_curve_dialog)

    # def _get_latest_four_values(self, db_path):
    #     """
    #     从 db 的 LogData 中取“最新一秒”的套管压力、套管排量、砂比、粘度，用于曲线上端实时显示。
    #
    #     规则（按秒级 Time / system_time）：
    #     - 若某秒只有秒点（Time 有值，无该秒的 system_time 粘度）：
    #       顶部显示该秒的套管压力/套管排量/砂比，粘度为 0。
    #     - 若某秒同时有秒点 + 粘度（Time 和 system_time 同一秒）：
    #       顶部显示该秒秒点 + 该秒粘度的真实值。
    #     - 若某秒只有粘度（无该秒秒点）：
    #       顶部仅粘度为真实值，其余为 0。
    #     - 若既无秒点也无粘度：四项返回 None（外层会显示 '--'）。
    #     """
    #     if not db_path or not str(db_path).strip():
    #         return (None, None, None, None)
    #     db_path = os.path.abspath(os.path.normpath(str(db_path).strip()))
    #     if not os.path.isfile(db_path):
    #         return (None, None, None, None)
    #     try:
    #         conn = sqlite3.connect(db_path, timeout=2)
    #         cursor = conn.cursor()
    #         cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='LogData'")
    #         if cursor.fetchone() is None:
    #             conn.close()
    #             return (None, None, None, None)
    #
    #         cursor.execute("PRAGMA table_info(LogData)")
    #         cols = [row[1] for row in cursor.fetchall()]
    #         has_pressure = '套管压力' in cols
    #         has_rate = '套管排量' in cols
    #         has_sand = '砂比' in cols
    #         visc_col = 'viscosity' if 'viscosity' in cols else ('粘度' if '粘度' in cols else None)
    #         if visc_col is None and not (has_pressure or has_rate or has_sand):
    #             conn.close()
    #             return (None, None, None, None)
    #
    #         # 工具：把 Time / system_time 统一转为 "HH:MM:SS" 字符串
    #         def _sec_str(v):
    #             if v is None:
    #                 return None
    #             s = str(v).strip()
    #             if not s:
    #                 return None
    #             # 如果是 "YYYY-MM-DD HH:MM:SS" 取最后 8 位；如果本身就是 "HH:MM:SS" 也适用
    #             if len(s) >= 8:
    #                 return s[-8:]
    #             return s
    #
    #         # 1）最新一条“有秒点”的 Time（可能为 None）
    #         latest_time_sec = None
    #         latest_p = latest_q = latest_s = None
    #         if has_pressure or has_rate or has_sand:
    #             cursor.execute(
    #                 "SELECT Time, 套管压力, 套管排量, 砂比 "
    #                 "FROM LogData WHERE Time IS NOT NULL ORDER BY ID DESC LIMIT 1"
    #             )
    #             row = cursor.fetchone()
    #             if row:
    #                 latest_time_sec = _sec_str(row[0])
    #                 latest_p = row[1] if has_pressure else None
    #                 latest_q = row[2] if has_rate else None
    #                 latest_s = row[3] if has_sand else None
    #
    #         # 2）最新一条粘度行的秒（可能为 None）
    #         latest_visc_sec = None
    #         latest_v = None
    #         if visc_col is not None:
    #             cursor.execute(
    #                 "SELECT system_time, {col} FROM LogData "
    #                 "WHERE {col} IS NOT NULL ORDER BY ID DESC LIMIT 1".format(col=visc_col)
    #             )
    #             row = cursor.fetchone()
    #             if row:
    #                 latest_visc_sec = _sec_str(row[0])
    #                 latest_v = row[1]
    #
    #         conn.close()
    #
    #         # 3）按规则决定当前秒 & 四个值
    #         cur_p = cur_q = cur_s = cur_v = None
    #
    #         if latest_time_sec is not None and latest_visc_sec is not None:
    #             if latest_time_sec == latest_visc_sec:
    #                 # 同一秒：秒点 + 粘度 全部显示
    #                 cur_p, cur_q, cur_s, cur_v = latest_p, latest_q, latest_s, latest_v
    #             else:
    #                 # 秒点和粘度不在同一秒：
    #                 # 视为“当前秒 = latest_time_sec”，该秒仅有秒点
    #                 cur_p, cur_q, cur_s = latest_p, latest_q, latest_s
    #                 cur_v = 0.0
    #         elif latest_time_sec is not None:
    #             # 只有秒点，没有任何粘度
    #             cur_p, cur_q, cur_s = latest_p, latest_q, latest_s
    #             cur_v = 0.0
    #         elif latest_visc_sec is not None:
    #             # 只有粘度，没有秒点
    #             cur_p = cur_q = cur_s = 0.0
    #             cur_v = latest_v
    #         else:
    #             # 秒点、粘度都没有
    #             return (None, None, None, None)
    #
    #         def _fmt(x):
    #             if x is None:
    #                 return '--'
    #             try:
    #                 # 数值保留两位小数，其它原样
    #                 return '{:.2f}'.format(float(x)) if isinstance(x, (int, float)) else str(x).strip() or '--'
    #             except Exception:
    #                 s = str(x).strip()
    #                 return s if s else '--'
    #
    #         return (_fmt(cur_p), _fmt(cur_q), _fmt(cur_s), _fmt(cur_v))
    #
    #     except Exception:
    #         return (None, None, None, None)

    def _get_latest_four_values(self, db_path):
        """
        从 db 的 LogData 中分别取：
        - 最新一条秒点记录的 套管压力、套管排量、砂比（按 Time IS NOT NULL 倒序）
        - 最新一条粘度记录的 粘度（按 viscosity/system_time 倒序）

        不再强制要求“秒点 Time 与粘度 system_time 属于同一秒”，
        也就是说：上方三项代表“最新秒点”，粘度代表“最新粘度”，两者时间可不同。
        无数据时返回 None（外层格式化为 '--'）。
        """
        if not db_path or not str(db_path).strip():
            return (None, None, None, None)
        db_path = os.path.abspath(os.path.normpath(str(db_path).strip()))
        if not os.path.isfile(db_path):
            return (None, None, None, None)

        try:
            conn = sqlite3.connect(db_path, timeout=2)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='LogData'")
            if cursor.fetchone() is None:
                conn.close()
                return (None, None, None, None)

            cursor.execute("PRAGMA table_info(LogData)")
            cols_info = cursor.fetchall()
            cols = [row[1] for row in cols_info]
            has_pressure = '套管压力' in cols
            has_rate = '套管排量' in cols
            has_sand = '砂比' in cols
            visc_col = 'viscosity' if 'viscosity' in cols else ('粘度' if '粘度' in cols else None)

            # 如果既没有秒点相关列，也没有粘度列，直接返回
            if visc_col is None and not (has_pressure or has_rate or has_sand):
                conn.close()
                return (None, None, None, None)

            # 1）最新一条“秒点”记录（Time 非空）
            latest_p = latest_q = latest_s = None
            if has_pressure or has_rate or has_sand:
                cursor.execute(
                    "SELECT Time, 套管压力, 套管排量, 砂比 "
                    "FROM LogData WHERE Time IS NOT NULL ORDER BY ID DESC LIMIT 1"
                )
                row = cursor.fetchone()
                if row:
                    latest_p = row[1] if has_pressure else None
                    latest_q = row[2] if has_rate else None
                    latest_s = row[3] if has_sand else None

            # 2）最新一条粘度记录（viscosity / 粘度 非空）
            latest_v = None
            if visc_col is not None:
                cursor.execute(
                    "SELECT system_time, {col} FROM LogData "
                    "WHERE {col} IS NOT NULL ORDER BY ID DESC LIMIT 1".format(col=visc_col)
                )
                row = cursor.fetchone()
                if row:
                    latest_v = row[1]

            conn.close()

            def _fmt(x):
                if x is None:
                    return '--'
                try:
                    # 数值保留两位小数，其它原样
                    return '{:.2f}'.format(float(x)) if isinstance(x, (int, float)) else str(x).strip() or '--'
                except Exception:
                    s = str(x).strip()
                    return s if s else '--'

            return (_fmt(latest_p), _fmt(latest_q), _fmt(latest_s), _fmt(latest_v))

        except Exception:
            return (None, None, None, None)

    # def _on_latest_data_timeout(self):
    #     """定时器：每秒用当前 db 最新一秒数据更新曲线上端四组显示。"""
    #     p, q, s, v = self._get_latest_four_values(self.file_path)
    #     if p is None:
    #         p = q = s = v = '--'
    #     self._label_latest_套管压力.setText(p)
    #     self._label_latest_套管排量.setText(q)
    #     self._label_latest_砂比.setText(s)
    #     self._label_latest_粘度.setText(v)
    def _on_latest_data_timeout(self):
        """定时器：每秒用当前 db 最新秒点 + 最新粘度更新上端四个显示。"""
        p, q, s, v = self._get_latest_four_values(self.file_path)
        # 兜底：若函数内部异常返回 None，则统一显示 '--'
        if p is None:
            p = '--'
        if q is None:
            q = '--'
        if s is None:
            s = '--'
        if v is None:
            v = '--'
        self._label_latest_套管压力.setText(p)
        self._label_latest_套管排量.setText(q)
        self._label_latest_砂比.setText(s)
        self._label_latest_粘度.setText(v)


    def show_plot_dialog(self):
        """点击 查看->绘图 时打开“曲线绘制”弹窗。"""
        self.update_local_plot_source()
        self._plot_dialog.show()
        self._plot_dialog.raise_()
        self._plot_dialog.activateWindow()

    def show_history_curve_dialog(self):
        """点击 查看->历史曲线 时打开“历史曲线”弹窗。"""
        self._history_curve_dialog.show()
        self._history_curve_dialog.raise_()
        self._history_curve_dialog.activateWindow()

    def show_csv_dialog(self):
        """点击 查看->csv 时打开“CSV文件”弹窗。"""
        self._csv_file_dialog.show()
        self._csv_file_dialog.raise_()
        self._csv_file_dialog.activateWindow()

    # 更新本地绘图控件当前使用的数据源路径及井段信息
    def update_local_plot_source(self):
        # 若本地绘图控件尚未创建，直接返回不执行任何操作
        if self.local_plot_widget is None:
            return
        # 获取当前界面选择的井号，用于拼接井段信息
        cur_well = self.ui.lineEdit_well.text()

        cur_frac_num = self.ui.lineEdit_frac_num.text()

        cur_layer = self.ui.lineEdit_layer.text()

        cur_period = self.ui.lineEdit_period.text()
        # 调用本地绘图控件的set_db_path方法，把当前db路径及井段信息传进去
        self.local_plot_widget.set_db_path(self.file_path, cur_well, cur_frac_num, cur_layer, cur_period)

    def _on_y_axis_adjust_clicked(self):
        """打开 Y 轴范围调整弹窗；确定后写入 config，下次刷新生效。"""
        dlg = YAxisRangeDialog(self)
        dlg.exec_()


    # 刷新本地秒点曲线按钮的槽函数，实现从当前db中读取数据并绘图，并用处理后的数据更新右侧表格
    def on_local_plot_refresh_clicked(self):
        try:
            self.update_local_plot_source()
            r = load_y_ranges_from_config()
            p_range = (r.get('pressure_min', 0.0), r.get('pressure_max', 100.0))
            rate_range = (r.get('rate_min', 0.0), r.get('rate_max', 50.0))
            sand_range = (r.get('sand_min', 0.0), r.get('sand_max', 100.0))
            v_range = (r.get('viscosity_min', 0.0), r.get('viscosity_max', 100.0))
            self.local_plot_widget.set_user_y_ranges(p_range, rate_range, sand_range, v_range)
            self.local_plot_widget.load_full_data()
            # 用处理后的数据（按 system_time 合并粘度）填充右侧表格，并供“保存csv文件”使用
            self._plot_table_processed_data = self._fill_plot_table_from_db(self.file_path)
            if self._plot_table_processed_data is not None:
                self.btn_save_plot_csv.setEnabled(True)
        except Exception as e:
            print(f'刷新本地秒点曲线时发生异常: {e}')

    def _on_curve_data_updated(self, db_path):
        """曲线（全量/增量）加载完成后调用，同步刷新右侧表格与保存用数据，使表格与曲线一样每 3 秒更新。"""
        if not db_path or not str(db_path).strip():
            return
        self._plot_table_processed_data = self._fill_plot_table_from_db(db_path, table_widget=None)
        if self._plot_table_processed_data is not None:
            self.btn_save_plot_csv.setEnabled(True)

    def _on_save_plot_csv_clicked(self):
        """将当前界面显示的处理后 CSV 数据保存到用户选择的文件。默认与当前 db 同路径、同主文件名。"""
        if getattr(self, '_plot_table_processed_data', None) is None:
            return
        headers, rows = self._plot_table_processed_data
        default_path = 'C:/a_transmission_data/data.csv'
        if self.file_path and str(self.file_path).strip():
            db_dir = os.path.dirname(os.path.abspath(self.file_path))
            base = os.path.splitext(os.path.basename(self.file_path))[0]
            if db_dir and base:
                default_path = os.path.join(db_dir, base + '.csv')
            elif db_dir:
                default_path = os.path.join(db_dir, 'data.csv')
        path, _ = QFileDialog.getSaveFileName(
            self, '保存 CSV 文件', default_path,
            'CSV (*.csv);;所有文件 (*)'
        )
        if not path:
            return
        try:
            write_processed_csv(headers, rows, path)
            self.ui.statusbar.showMessage('已保存: {}'.format(path))
        except Exception as e:
            QMessageBox.warning(self.centralwidget, '保存失败', '保存 CSV 失败: {}'.format(e))

    def _on_scroll_plot_table_to_bottom_clicked(self):
        """回到底部：将右侧 CSV 表格的滚动条滚到最下面，便于查看最新数据。"""
        table = getattr(self, '_plot_table', None)
        if table is not None:
            table.scrollToBottom()

    # 根据 db 填充右侧表格（可选传入 table_widget，供历史曲线弹窗使用）
    # def _fill_plot_table_from_db(self, db_path, table_widget=None):
    #     """右侧 CSV 表格：显示/保存均使用处理后的数据（按 system_time 合并粘度）。
    #     返回 (headers, rows)，失败返回 None。
    #     """
    #     table = table_widget if table_widget is not None else getattr(self, '_plot_table', None)
    #     if table is None:
    #         return None
    #
    #     # 必须在清空表格之前读取滚动条状态，否则清空后读到的永远是“在底部”
    #     vbar = table.verticalScrollBar()
    #     old_max = vbar.maximum()
    #     old_value = vbar.value()
    #     at_bottom_before = (old_max - old_value) <= 2
    #     scroll_ratio = (old_value / old_max) if (old_max > 0) else 0.0
    #
    #     # 水平滚动条：同样在清空前保存位置，刷新后按比例恢复
    #     hbar = table.horizontalScrollBar()
    #     old_h_max = hbar.maximum()
    #     old_h_value = hbar.value()
    #     h_scroll_ratio = (old_h_value / old_h_max) if (old_h_max > 0) else 0.0
    #
    #     # 仿照滚动条：在清空表格之前保存当前列宽（仅前 n-1 列，最后一列保持拉伸）
    #     current_cols_before = table.columnCount()
    #     if current_cols_before > 1:
    #         header_before = table.horizontalHeader()
    #         saved_col_widths = [header_before.sectionSize(i) for i in range(current_cols_before - 1)]
    #     else:
    #         saved_col_widths = []
    #
    #     table.setRowCount(0)
    #     table.setColumnCount(0)
    #
    #     if not db_path or not str(db_path).strip():
    #         table.setColumnCount(1)
    #         table.setRowCount(1)
    #         table.setHorizontalHeaderLabels(['提示'])
    #         table.setItem(0, 0, QTableWidgetItem('请先选择或创建 db 文件后点击刷新。'))
    #         return None
    #
    #     db_path = os.path.abspath(os.path.normpath(str(db_path).strip()))
    #     if not os.path.isfile(db_path):
    #         table.setColumnCount(1)
    #         table.setRowCount(1)
    #         table.setHorizontalHeaderLabels(['提示'])
    #         table.setItem(0, 0, QTableWidgetItem('数据库文件不存在。'))
    #         return None
    #
    #     try:
    #         headers, rows = get_processed_log_data(db_path)
    #         new_row_count = len(rows)
    #         new_col_count = len(headers)
    #
    #         current_rows = table.rowCount()
    #         current_cols = table.columnCount()
    #
    #         if current_cols != new_col_count:
    #             table.setColumnCount(new_col_count)
    #             table.setHorizontalHeaderLabels(headers)
    #         else:
    #             table.setHorizontalHeaderLabels(headers)
    #
    #         # 不再每次设置 ResizeToContents/Stretch，避免覆盖用户拖拽的列宽；列模式在 init 中已设为 Interactive + StretchLastSection
    #
    #         if new_row_count > current_rows:
    #             table.setRowCount(new_row_count)
    #         else:
    #             table.setRowCount(new_row_count)
    #
    #         out_rows = []
    #         start_row = max(0, current_rows)
    #         for i in range(start_row, new_row_count):
    #             row = rows[i]
    #             out_row = []
    #             for j in range(new_col_count):
    #                 cell = row[j] if j < len(row) else ''
    #                 if cell is None:
    #                     s = ''
    #                 else:
    #                     # 数值类型统一两位小数；非数值按原样显示
    #                     if isinstance(cell, (int, float)):
    #                         s = "{:.2f}".format(float(cell))
    #                     else:
    #                         s = str(cell).strip()
    #                         if s.lower() == 'none':
    #                             s = ''
    #                 table.setItem(i, j, QTableWidgetItem(s))
    #                 out_row.append(s)
    #             out_rows.append(out_row)
    #
    #         if start_row > 0:
    #             out_rows = []
    #             for r in rows:
    #                 one = []
    #                 for j in range(new_col_count):
    #                     cell = r[j] if j < len(r) else ''
    #                     s = '' if cell is None else str(cell).strip()
    #                     if s.lower() == 'none':
    #                         s = ''
    #                     one.append(s)
    #                 out_rows.append(one)
    #
    #         # 延后执行：恢复滚动条 + 恢复列宽（与滚动条同一逻辑，避免被表更新冲掉）
    #         def _restore_scroll_and_columns():
    #             t = table_widget if table_widget is not None else getattr(self, '_plot_table', None)
    #             if t is None:
    #                 return
    #             v = t.verticalScrollBar()
    #             if at_bottom_before:
    #                 t.scrollToBottom()
    #             else:
    #                 m = v.maximum()
    #                 v.setValue(int(scroll_ratio * m))
    #             # 水平滚动条：按刷新前保存的比例恢复
    #             h_sc = t.horizontalScrollBar()
    #             hm = h_sc.maximum()
    #             if hm > 0:
    #                 h_sc.setValue(int(h_scroll_ratio * hm))
    #             # 列宽恢复：仅当列数一致时恢复前 n-1 列，最后一列保持拉伸
    #             if saved_col_widths and new_col_count > 0 and len(saved_col_widths) == new_col_count - 1:
    #                 h = t.horizontalHeader()
    #                 for i in range(new_col_count - 1):
    #                     h.resizeSection(i, saved_col_widths[i])
    #
    #         if new_row_count:
    #             from PyQt5.QtCore import QTimer
    #             QTimer.singleShot(0, _restore_scroll_and_columns)
    #
    #         return (headers, out_rows)
    #
    #
    #
    #     except Exception as e:
    #         table.setColumnCount(1)
    #         table.setRowCount(1)
    #         table.setHorizontalHeaderLabels(['提示'])
    #         table.setItem(0, 0, QTableWidgetItem('加载表格数据失败: {}'.format(e)))
    #         return None

    def _fill_plot_table_from_db(self, db_path, table_widget=None):
        """右侧 CSV 表格：显示/保存均使用处理后的数据（按 system_time 合并粘度）。
        返回 (headers, rows)，失败返回 None。
        """
        table = table_widget if table_widget is not None else getattr(self, '_plot_table', None)
        if table is None:
            return None

        # 必须在清空表格之前读取滚动条状态，否则清空后读到的永远是“在底部”
        vbar = table.verticalScrollBar()
        old_max = vbar.maximum()
        old_value = vbar.value()
        at_bottom_before = (old_max - old_value) <= 2
        scroll_ratio = (old_value / old_max) if (old_max > 0) else 0.0

        # 水平滚动条：同样在清空前保存位置，刷新后按比例恢复
        hbar = table.horizontalScrollBar()
        old_h_max = hbar.maximum()
        old_h_value = hbar.value()
        h_scroll_ratio = (old_h_value / old_h_max) if (old_h_max > 0) else 0.0

        # 新增：是否已做过“首次列宽初始化”
        # cols_inited = bool(getattr(table, "_csv_cols_inited", False))
        #
        # # 仿照滚动条：在清空表格之前保存当前列宽（仅前 n-1 列，最后一列保持拉伸）
        # # 仅在“已经初始化过”后才保存/恢复用户列宽；首次进来不走保存恢复，避免继承到异常窄列宽
        # current_cols_before = table.columnCount()
        # if cols_inited and current_cols_before > 1:
        #     header_before = table.horizontalHeader()
        #     saved_col_widths = [header_before.sectionSize(i) for i in range(current_cols_before - 1)]
        # else:
        #     saved_col_widths = []

        # 新增：用户是否手动拖拽过列宽（拖拽过后才进入“用户优先”模式）
        user_resized = bool(getattr(table, "_csv_user_resized", False))

        # 在清空表格之前保存当前列宽（仅前 n-1 列，最后一列保持拉伸）
        # 只有当用户已手动拖拽过列宽时才保存/恢复；否则使用自动布局
        current_cols_before = table.columnCount()
        if user_resized and current_cols_before > 1:
            header_before = table.horizontalHeader()
            saved_col_widths = [header_before.sectionSize(i) for i in range(current_cols_before - 1)]
        else:
            saved_col_widths = []

        table.setRowCount(0)
        table.setColumnCount(0)

        if not db_path or not str(db_path).strip():
            table.setColumnCount(1)
            table.setRowCount(1)
            table.setHorizontalHeaderLabels(['提示'])
            table.setItem(0, 0, QTableWidgetItem('请先选择或创建 db 文件后点击刷新。'))
            return None

        db_path = os.path.abspath(os.path.normpath(str(db_path).strip()))
        if not os.path.isfile(db_path):
            table.setColumnCount(1)
            table.setRowCount(1)
            table.setHorizontalHeaderLabels(['提示'])
            table.setItem(0, 0, QTableWidgetItem('数据库文件不存在。'))
            return None

        try:
            headers, rows = get_processed_log_data(db_path)
            new_row_count = len(rows)
            new_col_count = len(headers)

            current_rows = table.rowCount()
            current_cols = table.columnCount()

            if current_cols != new_col_count:
                table.setColumnCount(new_col_count)
                table.setHorizontalHeaderLabels(headers)
            else:
                table.setHorizontalHeaderLabels(headers)

            # 不再每次设置 ResizeToContents/Stretch，避免覆盖用户拖拽的列宽；
            # 但“首次显示”会做一次默认列宽初始化（见下方 restore 回调）。

            table.setRowCount(new_row_count)

            out_rows = []
            start_row = max(0, current_rows)
            for i in range(start_row, new_row_count):
                row = rows[i]
                out_row = []
                for j in range(new_col_count):
                    cell = row[j] if j < len(row) else ''
                    if cell is None:
                        s = ''
                    else:
                        if isinstance(cell, (int, float)):
                            s = "{:.2f}".format(float(cell))
                        else:
                            s = str(cell).strip()
                            if s.lower() == 'none':
                                s = ''
                    table.setItem(i, j, QTableWidgetItem(s))
                    out_row.append(s)
                out_rows.append(out_row)

            if start_row > 0:
                out_rows = []
                for r in rows:
                    one = []
                    for j in range(new_col_count):
                        cell = r[j] if j < len(r) else ''
                        s = '' if cell is None else str(cell).strip()
                        if s.lower() == 'none':
                            s = ''
                        one.append(s)
                    out_rows.append(one)

            # 延后执行：恢复滚动条 +（首次）初始化列宽 /（后续）恢复用户列宽
            def _restore_scroll_and_columns():
                t = table_widget if table_widget is not None else getattr(self, '_plot_table', None)
                if t is None:
                    return

                # 1) 恢复竖向滚动条
                # v = t.verticalScrollBar()
                # if at_bottom_before:
                #     t.scrollToBottom()
                # else:
                #     m = v.maximum()
                #     v.setValue(int(scroll_ratio * m))
                try:
                    v = t.verticalScrollBar()
                    if at_bottom_before:
                        t.scrollToBottom()
                    else:
                        new_max = v.maximum()
                        v.setValue(min(old_value, new_max))
                except Exception:
                    # 回调里任何异常都吞掉，避免 Qt 直接闪退
                    return

                # 2) 恢复水平滚动条
                h_sc = t.horizontalScrollBar()
                hm = h_sc.maximum()
                if hm > 0:
                    h_sc.setValue(int(h_scroll_ratio * hm))

                # 3) 列宽策略：
                # - 首次显示：做一次默认初始化，让所有列都可见
                # - 后续刷新：恢复用户拖拽后的列宽（saved_col_widths）
                # first_time = not bool(getattr(t, "_csv_cols_inited", False))
                #
                # if first_time:
                #     # 默认列宽初始化：每列 ResizeToContents + 最小宽度钳制；最后一列保持拉伸
                #     h = t.horizontalHeader()
                #     try:
                #         # 先按内容自适应一次
                #         for i in range(new_col_count):
                #             h.setSectionResizeMode(i, QHeaderView.ResizeToContents)
                #         # 设置最小宽度，避免列被挤到看不见
                #         min_w = 80
                #         for i in range(new_col_count):
                #             w = h.sectionSize(i)
                #             if w < min_w:
                #                 h.resizeSection(i, min_w)
                #         # 最后一列拉伸占满剩余空间
                #         h.setStretchLastSection(True)
                #     except Exception:
                #         pass
                #
                #     # 标记已初始化（后续刷新就保留用户拖拽）
                #     setattr(t, "_csv_cols_inited", True)
                #
                # else:
                #     # 列宽恢复：仅当列数一致时恢复前 n-1 列，最后一列保持拉伸
                #     if saved_col_widths and new_col_count > 0 and len(saved_col_widths) == new_col_count - 1:
                #         h = t.horizontalHeader()
                #         for i in range(new_col_count - 1):
                #             h.resizeSection(i, saved_col_widths[i])
                # 列宽策略（优化版需求）：
                # - 用户未手动拖拽列宽：每次刷新都用“自动布局（内容自适应 + min/max 钳制）”，保证每列内容可见
                # - 用户一旦手动拖拽列宽：后续刷新不再自动布局，改为恢复用户列宽
                h = t.horizontalHeader()

                # 只连接一次：监听用户拖拽列宽
                if not bool(getattr(t, "_csv_header_resize_connected", False)):
                    def _on_section_resized(logicalIndex, oldSize, newSize):
                        # 程序自动布局期间产生的 resize 不算“用户拖拽”
                        if bool(getattr(t, "_csv_initing_cols", False)):
                            return
                        setattr(t, "_csv_user_resized", True)

                    try:
                        h.sectionResized.connect(_on_section_resized)
                        setattr(t, "_csv_header_resize_connected", True)
                    except Exception:
                        pass

                user_resized_now = bool(getattr(t, "_csv_user_resized", False))

                if not user_resized_now:
                    # 自动布局：内容自适应 + 宽度钳制
                    try:
                        setattr(t, "_csv_initing_cols", True)

                        # 先按内容自适应
                        for i in range(new_col_count):
                            h.setSectionResizeMode(i, QHeaderView.ResizeToContents)

                        # 再做 min/max 钳制，避免“某列过宽挤掉其它列”或“列太窄看不见”
                        min_w = 80
                        max_default = 260

                        # 按列名给更合理的上限（时间列更宽）
                        name_to_max = {
                            "时间": 240,
                            "system_time": 140,
                        }

                        for i in range(new_col_count):
                            col_name = ""
                            try:
                                col_name = str(h.model().headerData(i, Qt.Horizontal)).strip()
                            except Exception:
                                col_name = ""

                            w = h.sectionSize(i)
                            if w < min_w:
                                w = min_w

                            max_w = name_to_max.get(col_name, max_default)
                            if w > max_w:
                                w = max_w

                            h.resizeSection(i, w)

                        # 最后一列拉伸占满右侧
                        h.setStretchLastSection(True)

                    except Exception:
                        pass
                    finally:
                        setattr(t, "_csv_initing_cols", False)

                else:
                    # 用户已拖拽：恢复用户列宽（前 n-1 列），最后一列仍拉伸
                    if saved_col_widths and new_col_count > 0 and len(saved_col_widths) == new_col_count - 1:
                        for i in range(new_col_count - 1):
                            h.resizeSection(i, saved_col_widths[i])
                    h.setStretchLastSection(True)

            if new_row_count:
                from PyQt5.QtCore import QTimer
                QTimer.singleShot(0, _restore_scroll_and_columns)

            return (headers, out_rows)

        except Exception as e:
            table.setColumnCount(1)
            table.setRowCount(1)
            table.setHorizontalHeaderLabels(['提示'])
            table.setItem(0, 0, QTableWidgetItem('加载表格数据失败: {}'.format(e)))
            return None

    # 点击选项卡时，判断self.state_code是否为1002，若不是则禁用当前点击的选项卡，若是，则说明井信息上传成功
    def tab_clicked(self, index):
        if index == 1 and self.state_code != '1002':
            try:
                self.ui.tabWidget.setCurrentIndex(0)  # 如果条件不满足，留在tab1
                self.ui.tab_2.setEnabled(False)
                QMessageBox.warning(self.ui.centralwidget, '警告', '请先保存井信息！')
            except Exception as e:
                import traceback
                print("An error occurred:")
                # 完整的堆栈跟踪信息，包括触发异常的代码行，从而定位到错误出现的具体位置。
                traceback.print_exc()
                print(f'异常为：{e}')
        elif index == 2 and self.state_code != '1002':
            try:
                self.ui.tabWidget.setCurrentIndex(0)  # 如果条件不满足，留在tab1
                self.ui.tab_3.setEnabled(False)
                QMessageBox.warning(self.ui.centralwidget, '警告', '请先保存井信息！')
            except Exception as e:
                import traceback
                print("An error occurred:")
                # 完整的堆栈跟踪信息，包括触发异常的代码行，从而定位到错误出现的具体位置。
                traceback.print_exc()
                print(f'异常为：{e}')
        else:
            self.ui.tab_2.setEnabled(True)
            for item in self.dict_label_combox_db:
                label = item['label']
                comboBox = getattr(self, f'comboBox_{label}_')
                # 将当前选中的索引与槽函数关联
                comboBox.currentTextChanged.connect(self.handle_currentIndexChanged_)
            self.ui.tab_3.setEnabled(True)


    # 复选框发生变化时执行
    def handle_currentIndexChanged_(self):
        try:
            sender = self.ui.centralwidget.sender()
            # 遍历字典列表，找到对应的标签和下拉框
            for item in self.dict_label_combox_db:
                # print(label,combo_box)
                label = item['label']
                combo_box = item['combo_box']
                if sender == combo_box:
                    selected_option = combo_box.currentText()
                    # print(f"选择了 '{selected_option}'，与标签 '{label}' 对应")
                    item['value'] = selected_option
                    values_list = list(filter(lambda x: x['value'] != '', self.dict_label_combox_db))
                    values_list = [int(item['value']) for item in values_list]
                    print(values_list)
                    print(len(values_list))
                    print(len(set(values_list)))
                    if len(values_list) != len(set(values_list)):
                        combo_box.setCurrentIndex(-1)
                        item['value'] = ''
                        QMessageBox.warning(self.ui.centralwidget, '警告', '序号选择重复！')
        except Exception as e:
            import traceback
            print("An error occurred:")
            # 完整的堆栈跟踪信息，包括触发异常的代码行，从而定位到错误出现的具体位置。
            traceback.print_exc()

    # 结束按钮槽函数
    def end_upload(self):
        # 创建一个确认弹窗
        if self.receiver_thread is not None and self.receiver_thread.isRunning():
            QMessageBox.warning(self.ui.centralwidget, '警告', '请先停止接收数据！')
        else:
            reply = QMessageBox.question(self.ui.centralwidget, '确认', '确定要结束吗？',
                                         QMessageBox.Yes | QMessageBox.No,
                                         QMessageBox.No)
            if reply == QMessageBox.Yes:
                # 如果用户点击确认按钮，则退出程序
                try:
                    # 关闭客户端
                    # if self.worker_thread.client:
                    #     print('client存在')
                    #     self.worker_thread.client.close()
                    # time.sleep(1)
                    # 关闭socket连接
                    if self.worker_thread is not None and self.worker_thread.isRunning():
                        self.worker_thread.terminate()  # 终止线程
                        print('向服务器发送数据线程已关闭')

                    self.columns_info = ''
                    self.file_path = ''

                    self.btn_start.setEnabled(True)
                    self.btn_fileselect.setEnabled(True)
                    self.btn_getcolumn.setEnabled(True)

                    self.point_1 = 0
                    self.point_2 = 0
                    self.save_config()

                    cur_well = self.ui.lineEdit_well.text()
                    cur_frac_num = self.ui.lineEdit_frac_num.text()
                    cur_layer = self.ui.lineEdit_layer.text()
                    cur_period = self.ui.lineEdit_period.text()
                    well_info = cur_well + '第' + cur_frac_num + '次压裂' + cur_layer + '第' + cur_period + '段'
                    # state_code = self.base_API({'url': '/update_state_code', 'method': 'POST', 'data':{'well_info': well_info, 'code': '1006'}})

                    # 转存临时db文件到秒点数据库

                    for item in self.label_combo_dict:
                        label = item['label']
                        combobox_obj = getattr(self, f'comboBox_{label}')
                        combobox_obj.setCurrentIndex(-1)
                        item['combo_box'] = combobox_obj
                        item['value'] = ''
                except Exception as e:
                    print(f'ang={e}')
                self.ui.textEdit.append('已结束！！！')
            else:
                # 如果用户点击取消按钮，则忽略关闭事件
                pass

        # 结束按钮槽函数

    def end_upload_tab4(self):
        # 创建一个确认弹窗
        # if self.receiver_thread.isRunning():
        #     QMessageBox.warning(self.ui.centralwidget, '警告', '请停止接收秒点数据！')
        #     return
        # if self.receiver_viscosity_thread.isRunning():
        #     QMessageBox.warning(self.ui.centralwidget, '警告', '请先停止接收粘/密度数据！')
        #     return
        # if self.file_path == '':
        #     QMessageBox.warning(self.ui.centralwidget, '警告', '请开始接收！')
        #     return
        # else:
        reply = QMessageBox.question(self.ui.centralwidget, '确认', '确定要结束吗？', QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            # 如果用户点击确认按钮，则退出程序
            try:
                # 关闭socket连接
                if self.worker_thread is not None and self.worker_thread.isRunning():
                    self.worker_thread.stop()  # 终止线程
                    print('向服务器发送数据线程已关闭')
                # self.pushButton_start_upload.setEnabled(True)
                # self.pushButton_stop_upload.setEnabled(False)
                self.btn2_start_tab6.setEnabled(True)
                self.btn2_stop_tab6.setEnabled(False)
                self.point_1 = 0
                self.point_2 = 0
                self.file_path = ''
                self.save_config()
                cur_well = self.ui.lineEdit_well.text()
                cur_frac_num = self.ui.lineEdit_frac_num.text()
                cur_layer = self.ui.lineEdit_layer.text()
                cur_period = self.ui.lineEdit_period.text()
                well_info = cur_well + '第' + cur_frac_num + '次压裂' + cur_layer + '第' + cur_period + '段'
                # 更新状态码？？？
                response_data = self.base_API({'url': '/update_state_code', 'method': 'POST', 'data': {'well_info': well_info, 'code': '1006'}})
                print(response_data['state_code'])
                print(response_data['msg'])
                if response_data['state_code'] == '1006':
                    QMessageBox.information(self.ui.centralwidget, '提示', '转存成功！')
                '''
                    一、转存临时db文件到秒点数据库
                    传输井信息数据到后端，后端根据井信息数据找到临时的db文件，将db文件转成.csv文件，保存到秒点数据库
                '''
            except Exception as e:
                print(f'yichang={e}')
            self.ui.textEdit2.append('上传已结束！！！')
        else:
            # 如果用户点击取消按钮，则忽略关闭事件
            pass

    def end_upload_viscosity_data(self):
        # 创建一个确认弹窗
        if self.receiver_viscosity_thread is not None:
            print(self.receiver_viscosity_thread.isRunning())
        if self.receiver_viscosity_thread is not None and self.receiver_viscosity_thread.isRunning():
            QMessageBox.warning(self.ui.centralwidget, '警告', '请先停止接收粘/密度数据！')
        else:
            reply = QMessageBox.question(self.ui.centralwidget, '确认', '确定要结束吗？', QMessageBox.Yes | QMessageBox.No,
                                         QMessageBox.No)
            if reply == QMessageBox.Yes:
                # 如果用户点击确认按钮，则退出程序
                try:
                    # 关闭socket连接
                    if getattr(self, 'Upload_Viscosity_Thread', None) is not None and self.Upload_Viscosity_Thread.isRunning():
                        self.Upload_Viscosity_Thread.terminate()
                        print('向服务器发送数据线程已关闭')
                    self.btn2_start_tab6.setEnabled(True)
                    self.btn2_stop_tab6.setEnabled(False)
                    self.viscosity_point_1 = 0
                    self.viscosity_point_2 = 0
                    self.save_config()
                except Exception as e:
                    print(f'yichang={e}')
                self.ui.textEdit2.append('已结束！！！')
            else:
                # 如果用户点击取消按钮，则忽略关闭事件
                pass

    def closeEvent(self, event):
        if self.btn2_stop_tab6.isEnabled():
            # 创建一个确认弹窗
            reply = QMessageBox.warning(self.ui.centralwidget, '警告',
                                        '检测到有任务正在运行，请先点击"结束"按钮停止任务！\n  是否强制退出？',
                                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

            if reply == QMessageBox.Yes:
                reply2 = QMessageBox.warning(self.ui.centralwidget, '警告',
                                            '强制退出！退出后检查配置文件config.ini：\npoint_1 = 0\npoint_2 = 0',
                                            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if reply2 == QMessageBox.Yes:
                    self.point_1 = 0
                    self.point_2 = 0
                    self.save_config()
                    # 如果用户强制退出，则退出程序,修改配置文件
                    event.accept()
            else:
                # 如果用户取消，则忽略关闭事件
                event.ignore()
        else:
            # 创建一个确认弹窗
            reply = QMessageBox.question(self.ui.centralwidget, '确认', '确定要退出程序吗？', QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

            if reply == QMessageBox.Yes:
                # 如果用户点击确认按钮，则退出程序
                event.accept()
            else:
                # 如果用户点击取消按钮，则忽略关闭事件
                event.ignore()

    # 点击开始接收,首先会在D盘新建一个db数据库文件，用于存储串口发来的数据
    def start_receive(self):
        # 必须先保存井信息后才能开始秒点数据采集
        if getattr(self, 'state_code', None) != '1002':
            QMessageBox.warning(self.ui.centralwidget, '警告', '请先保存井信息后再进行秒点数据采集。')
            return
        if self.comboBox_port_tab3.currentText() == '':
            QMessageBox.warning(self.ui.centralwidget, '警告', '请选择传输秒点数据的串口！')
            return
        db_columns_names = [item['label'] for item in self.dict_label_combox_db]
        print(db_columns_names)
        db_columns = ', '.join([f"`{field}` FLOAT" for field in db_columns_names])
        print(db_columns)

        filtered_list = []
        for item in self.dict_label_combox_db:
            try:
                text = item['combo_box'].currentText().strip()
                if text != '':
                    filtered_list.append({'label': item['label'], 'value': int(text)})
            except (ValueError, TypeError):
                pass
        filtered_list = sorted(filtered_list, key=lambda x: x['value'])
        self.field_num = len(filtered_list)
        print(self.field_num)
        field_name = []
        field_index = []
        if self.field_num == 0:
            QMessageBox.warning(self.ui.centralwidget, '警告', '请选择创建的数据表的字段！')
            return
        for item in filtered_list:
            field_name.append(item['label'])
            field_index.append(item['value'])
        # 使用 join() 方法连接列表元素
        self.config_name_save = ', '.join(field_name)
        self.save_config()
        print(self.config_name_save)
        # columns = ', '.join([f"{field} FLOAT" for field in field_name])
        # print(columns)
        try:
            cur_well = self.ui.lineEdit_well.text()
            cur_frac_num = self.ui.lineEdit_frac_num.text()
            cur_layer = self.ui.lineEdit_layer.text()
            cur_period = self.ui.lineEdit_period.text()
            measuring_truck = self.ui.comboBox_measuring_truck.currentText()  # 仪表车厂家
            port_name = self.comboBox_port_tab3.currentText()
            # 创建的.db文件名
            file_name = cur_well + '第' + cur_frac_num + '次压裂' + cur_layer + '第' + cur_period + '段'
            # 文件夹路径 D盘 a_transmission_data 井号
            folder_path = 'C:/a_transmission_data/' + cur_well
            # folder_path = 'D:/a_transmission_data/' + cur_well

            # 检查文件夹是否存在，如果不存在则创建
            if not os.path.exists(folder_path):
                os.makedirs(folder_path)
            temp_file_path = folder_path + '/' + file_name + '.db'
            self.file_path = temp_file_path
            print('.db文件路径：' + self.file_path)
            # 检查文件是否存在
            if os.path.exists(temp_file_path):
                # 如果文件已存在，并且新创建的 db文件字段和原来的相同
                QMessageBox.information(None, '文件已存在', '文件已存在', QMessageBox.Ok)
            else:
                if measuring_truck == '杰瑞' or measuring_truck == '宏华' or measuring_truck == '四机厂':
                    # 弹出警告框，再次确认发送的字段数量
                    reply2 = QMessageBox.question(None, '提示', f'请确认，发送的数据依次是：时间,{self.config_name_save}，'
                                                              f'共{self.field_num + 1}个',
                                                              QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                    if reply2 == QMessageBox.Yes:
                        # 连接到数据库（如果不存在，则会自动创建）
                        conn = sqlite3.connect(temp_file_path)
                        # 创建一个游标对象，用于执行SQL语句
                        cursor = conn.cursor()
                        # 创建表（如果表已经存在，这行代码不会影响现有表）
                        cursor.execute(f'''
                            CREATE TABLE IF NOT EXISTS LogData (
                                ID INTEGER PRIMARY KEY AUTOINCREMENT,
                                Time DATETIME,
                                {db_columns},
                                viscosity FLOAT,
                                density FLOAT,
                                system_time DATETIME NOT NULL
                            )
                        ''')
                        conn.commit()
                        conn.close()

                        QMessageBox.information(None, '提示！', '数据库文件创建成功！', QMessageBox.Ok)
                    else:
                        # 用户选择"否"，直接取消，不做任何操作
                        QMessageBox.information(None, '操作已取消', '操作已取消。')
                        return None  # 返回 None 表示不做任何操作
                elif measuring_truck == '三一重工':
                    # 弹出警告框，再次确认发送的字段数量
                    reply2 = QMessageBox.question(None, '提示', f'请确认，需要保存的数据分别是：时间，{self.config_name_save}，'
                                                              f'共{self.field_num + 1}个',
                                                  QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                    if reply2 == QMessageBox.Yes:
                        # 连接到数据库（如果不存在，则会自动创建）
                        conn = sqlite3.connect(temp_file_path)
                        # 创建一个游标对象，用于执行SQL语句
                        cursor = conn.cursor()
                        # 创建表（如果表已经存在，这行代码不会影响现有表）
                        cursor.execute(f'''
                                    CREATE TABLE IF NOT EXISTS LogData (
                                        ID INTEGER PRIMARY KEY AUTOINCREMENT,
                                        Time DATETIME,
                                        {db_columns},
                                        viscosity FLOAT,
                                        density FLOAT,
                                        system_time DATETIME NOT NULL
                                    )
                                ''')
                        conn.commit()
                        conn.close()

                        QMessageBox.information(None, '提示！', '数据库文件创建成功！', QMessageBox.Ok)
                    else:
                        # 用户选择"否"，直接取消，不做任何操作
                        QMessageBox.information(None, '操作已取消', '操作已取消。')
                        return None  # 返回 None 表示不做任何操作
            # print(f'数据库文件创建成功，文件名为：{file_name}，请在D盘下查看')
            self.ui.textEdit2.append(f'数据库文件创建成功，文件名为：{file_name}')
            self.ui.textEdit2.append('正在等待串口发送数据')
            self.start_receive_thread(cur_well, cur_frac_num, cur_layer, cur_period, field_name, measuring_truck, field_index, port_name)
            self.pushButton_start_receive.setEnabled(False)
            self.pushButton_stop_receive.setEnabled(True)
            self.update_local_plot_source()
        except Exception as e:
            import traceback
            print("An error occurred:")
            # 完整的堆栈跟踪信息，包括触发异常的代码行，从而定位到错误出现的具体位置。
            traceback.print_exc()
            print(f'异常为：{e}')

    # 开始接收粘度、密度数据
    def receive_viscosity_data(self):
        # 必须先保存井信息后才能开始黏度数据采集
        if getattr(self, 'state_code', None) != '1002':
            QMessageBox.warning(self.ui.centralwidget, '警告', '请先保存井信息后再进行粘度数据采集。')
            return
        if self.comboBox_port_tab6.currentText() == '':
            QMessageBox.warning(self.ui.centralwidget, '警告', '请选择传输粘/密度数据的串口！')
            return
        if self.file_path == '':
            cur_well = self.ui.lineEdit_well.text()
            cur_frac_num = self.ui.lineEdit_frac_num.text()
            cur_layer = self.ui.lineEdit_layer.text()
            cur_period = self.ui.lineEdit_period.text()
            # 创建的.db文件名
            file_name = cur_well + '第' + cur_frac_num + '次压裂' + cur_layer + '第' + cur_period + '段'
            # 文件夹路径 D盘 a_transmission_data 井号
            folder_path = 'C:/a_transmission_data/' + cur_well
            # folder_path = 'D:/a_transmission_data/' + cur_well
            temp_file_path = folder_path + '/' + file_name + '.db'
            # 检查文件是否存在
            if os.path.exists(temp_file_path):
                self.file_path = temp_file_path
                port_name = self.comboBox_port_tab6.currentText()
                liuquid_style = self.comboBox_port_tab8.currentText()
                self.start_receive_viscosity_data_thread(port_name, liuquid_style)
                self.btn_start_tab6.setEnabled(False)
                self.btn_stop_tab6.setEnabled(True)
            else:
                QMessageBox.warning(self.ui.centralwidget, '警告', '请先开始接收秒点数据！')
                return
        else:
            port_name = self.comboBox_port_tab6.currentText()
            liuquid_style = self.comboBox_port_tab8.currentText()
            self.start_receive_viscosity_data_thread(port_name, liuquid_style)
            self.btn_start_tab6.setEnabled(False)
            self.btn_stop_tab6.setEnabled(True)


    # 开启接收数据线程，不断将数据存储到db中
    def start_receive_thread(self, cur_well, cur_frac_num, cur_layer, cur_period, field_name, measuring_truck, field_index, port_name):
        try:
            self.receiver_thread = ReceiverThread(cur_well, cur_frac_num, cur_layer, cur_period, field_name, measuring_truck, field_index, port_name)
            self.receiver_thread.start()
            self.receiver_thread.update_textEdit.connect(self.receiver_thread_finished)
            self.receiver_thread.update_textEdit_2.connect(self.update_textEdit_pointdata)
        except Exception as e:
            print(f'e={e}')


    def update_textEdit_pointdata(self, data):
        self.ui.textEdit2.append(f"{data}")

    # 开启接收粘度、密度数据的线程，存到表中
    def start_receive_viscosity_data_thread(self, port_name, liquid_style):
        try:
            self.receiver_viscosity_thread = ReceiverViscosityThread(self.file_path, port_name, liquid_style)
            self.receiver_viscosity_thread.start()
            self.receiver_viscosity_thread.update_textEdit.connect(self.update_textEdit_viscosity)
        except Exception as e:
            print(f'e={e}')

    def update_textEdit_viscosity(self, msg):
        # 黏度/密度接收的实时信息写入第三栏（黏度数据状态栏）
        self.ui.textEdit3.append(f"{msg}")

    def receiver_thread_finished(self, data):
        self.ui.textEdit2.append(f"{data}秒的数据已保存！")

    # 关闭接收数据线程
    def stop_receive(self):
        try:
            if self.receiver_thread is not None and self.receiver_thread.isRunning():
                self.receiver_thread.stop()
                self.receiver_thread.quit()
                print('接收数据线程已关闭')
            self.pushButton_start_receive.setEnabled(True)
            self.pushButton_stop_receive.setEnabled(False)
        except Exception as e:
            print(f'异常={e}')
        self.ui.textEdit2.append('已停止接收秒点数据！')

    # 关闭接收粘度、密度数据的线程
    def stop_receive_viscosity_data(self):
        try:
            if self.receiver_viscosity_thread is not None and self.receiver_viscosity_thread.isRunning():
                self.receiver_viscosity_thread.stop()
                self.receiver_viscosity_thread.quit()
                print('接收黏度/密度数据线程已关闭')
            if self.receiver_viscosity_thread is not None:
                print(self.receiver_viscosity_thread.isRunning())
            self.btn_start_tab6.setEnabled(True)
            self.btn_stop_tab6.setEnabled(False)
        except Exception as e:
            print(f'异常={e}')
        # 停止黏度/密度接收的提示也写入第三栏（黏度数据状态栏）
        self.ui.textEdit3.append('已停止接收黏度/密度数据')

