import sys
import cv2
import numpy as np
import json
import os
import time
import random
import ctypes
import win32gui
import win32con
import win32api
import logging
import traceback
from PIL import ImageGrab
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from pynput.mouse import Controller as MouseController, Listener as MouseListener, Button
from pynput.keyboard import Controller as KeyboardController, Listener as KeyboardListener, Key

# 【终极防闪退】：全局异常可视化拦截
def global_exception_handler(exc_type, exc_value, exc_tb):
    try:
        with open("autoclicker_crash.txt", "w", encoding="utf-8") as f:
            f.write("=== AutoClicker 发生严重崩溃 ===\n")
            traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
        
        app = QApplication.instance()
        if app:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Critical)
            msg.setWindowTitle("致命错误拦截")
            msg.setText(f"程序发生崩溃，但已被拦截！\n\n错误类型: {exc_type.__name__}\n错误详情: {exc_value}\n\n详细崩溃日志已保存至同目录下")
            msg.exec_()
    except:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)

sys.excepthook = global_exception_handler

# 设置 DPI 感知 (Windows 专属)
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except:
        pass

class Step:
    def __init__(self, step_type, image_path=None, x=None, y=None,
                 click_type='left', wait_time=1000, similarity=0.8,
                 jump_to=None, random_delay_enabled=False, random_delay_min=100, random_delay_max=1000,
                 accept_offset=True, accept_random_delay=True):
        self.step_type = step_type
        self.image_path = image_path
        self.x = x
        self.y = y
        self.click_type = click_type
        self.wait_time = wait_time
        self.similarity = similarity
        self.jump_to = jump_to
        self.random_delay_enabled = random_delay_enabled
        self.random_delay_min = random_delay_min
        self.random_delay_max = random_delay_max
        self.accept_offset = accept_offset
        self.accept_random_delay = accept_random_delay

class AutoClickerApp(QMainWindow):
    coordinate_captured = pyqtSignal(int, int)
    stop_coordinate_mode = pyqtSignal()
    stop_select_window_mode_signal = pyqtSignal()
    window_selected = pyqtSignal(int, str)
    screenshot_closed = pyqtSignal()
    hotkey_triggered = pyqtSignal()

    def get_base_path(self):
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        else:
            return os.path.dirname(os.path.abspath(__file__))

    def __init__(self):
        super().__init__()
        self.setWindowTitle("AutoClicker V1.3")
        self.setMinimumSize(1000, 700)
        self.resize(1200, 800)

        self.steps = []
        self.current_step_index = 0
        self.is_running = False
        self.is_paused = False
        self.is_adding_coordinate = False
        self.is_selecting_window = False
        self.is_adding_image = False
        
        self.offset_enabled = False
        self.offset_x = 5
        self.offset_y = 5
        self.log_enabled = False

        self.base_dir = self.get_base_path()
        self.screenshot_dir = os.path.join(self.base_dir, "screenshots")
        os.makedirs(self.screenshot_dir, exist_ok=True)

        self.setup_logger()

        self.mouse_listener = None
        self.keyboard_listener = None
        self.global_hotkey_listener = None
        self.target_hwnd = None

        self.mouse = MouseController()
        self.keyboard = KeyboardController()
        self.hotkey = "F12"

        self.execution_start_time = None
        self.last_stop_time = None

        # 先实例化线程，因为 init_ui 里绑定信号需要用到它
        self.execution_thread = ExecutionThread(self)
        self.execution_thread.finished.connect(self.on_execution_finished)
        self.execution_thread.error.connect(self.on_execution_error)
        self.execution_thread.step_completed.connect(self.on_step_completed)

        self.init_ui()
        self.setup_global_hotkey()

        self.coordinate_captured.connect(self.on_coordinate_captured)
        self.stop_coordinate_mode.connect(self.stop_add_coordinate_mode)
        self.stop_select_window_mode_signal.connect(self.stop_select_window_mode)
        self.window_selected.connect(self.on_window_selected)
        self.screenshot_closed.connect(self.on_screenshot_closed)
        self.hotkey_triggered.connect(self.toggle_execution)

        self.master_timer = QTimer(self)
        self.master_timer.timeout.connect(self.on_master_timer_tick)
        self.master_timer.start(1000)

    def setup_logger(self):
        self.logger = logging.getLogger("AutoClicker")
        self.logger.setLevel(logging.DEBUG)
        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)
        self.log_file = os.path.join(self.base_dir, "autoclicker_debug.log")
        fh = logging.FileHandler(self.log_file, encoding='utf-8')
        fh.setFormatter(logging.Formatter('%(asctime)s - [%(levelname)s] - %(message)s'))
        self.logger.addHandler(fh)

    def init_ui(self):
        font = QFont("Microsoft YaHei", 10)
        self.setFont(font)

        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        main_splitter = QSplitter(Qt.Horizontal)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setMinimumWidth(380)
        left_scroll.setFrameShape(QFrame.NoFrame)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setSpacing(10)

        status_group = QGroupBox("当前状态")
        status_layout = QVBoxLayout()
        self.config_name_label = QLabel("当前配置: 未加载")
        self.config_name_label.setStyleSheet("color: #0056b3; font-weight: bold;")
        self.status_label = QLabel("执行进度: 空闲")
        self.status_label.setStyleSheet("color: #28a745; font-weight: bold;")
        status_layout.addWidget(self.config_name_label)
        status_layout.addWidget(self.status_label)
        status_group.setLayout(status_layout)
        left_layout.addWidget(status_group)

        control_group = QGroupBox("流程控制")
        control_layout = QVBoxLayout()
        self.start_btn = QPushButton("▶ 开始执行")
        self.start_btn.clicked.connect(self.start_execution)
        self.stop_btn = QPushButton("⏹ 停止执行")
        self.stop_btn.clicked.connect(self.stop_execution)
        self.stop_btn.setEnabled(False)
        self.pause_btn = QPushButton("⏸ 暂停执行")
        self.pause_btn.clicked.connect(self.pause_execution)
        self.pause_btn.setEnabled(False)

        # 【新增】：跑完本轮后停止开关
        self.stop_after_loop_cb = QCheckBox("⏳ 跑完本轮后自动停止")
        self.stop_after_loop_cb.setStyleSheet("color: #d35400; font-weight: bold; margin-top: 5px;")
        self.stop_after_loop_cb.stateChanged.connect(lambda state: setattr(self.execution_thread, 'stop_after_current', state == Qt.Checked))

        control_layout.addWidget(self.start_btn)
        stop_pause_layout = QHBoxLayout()
        stop_pause_layout.addWidget(self.pause_btn)
        stop_pause_layout.addWidget(self.stop_btn)
        control_layout.addLayout(stop_pause_layout)
        control_layout.addWidget(self.stop_after_loop_cb)
        control_group.setLayout(control_layout)
        left_layout.addWidget(control_group)

        timing_group = QGroupBox("定时与周期任务 (自动停止/启动)")
        timing_layout = QVBoxLayout()

        sched_start_layout = QHBoxLayout()
        self.schedule_start_cb = QCheckBox("定时启动:")
        self.schedule_start_time = QTimeEdit()
        self.schedule_start_time.setDisplayFormat("HH:mm:ss")
        self.schedule_start_time.setTime(QTime.currentTime())
        sched_start_layout.addWidget(self.schedule_start_cb)
        sched_start_layout.addWidget(self.schedule_start_time)
        timing_layout.addLayout(sched_start_layout)

        sched_stop_layout = QHBoxLayout()
        self.schedule_stop_cb = QCheckBox("定时关闭 (执行满分钟):")
        self.schedule_stop_spin = QSpinBox()
        self.schedule_stop_spin.setRange(1, 99999)
        self.schedule_stop_spin.setValue(60)
        sched_stop_layout.addWidget(self.schedule_stop_cb)
        sched_stop_layout.addWidget(self.schedule_stop_spin)
        timing_layout.addLayout(sched_stop_layout)

        periodic_start_layout = QHBoxLayout()
        self.periodic_start_cb = QCheckBox("周期启动 (结束后分钟):")
        self.periodic_start_spin = QSpinBox()
        self.periodic_start_spin.setRange(1, 99999)
        self.periodic_start_spin.setValue(60)
        periodic_start_layout.addWidget(self.periodic_start_cb)
        periodic_start_layout.addWidget(self.periodic_start_spin)
        timing_layout.addLayout(periodic_start_layout)

        timing_group.setLayout(timing_layout)
        left_layout.addWidget(timing_group)

        window_group = QGroupBox("目标窗口设置 (后台执行关键)")
        window_layout = QVBoxLayout()
        self.window_title_edit = QLineEdit()
        self.window_title_edit.setPlaceholderText("点击下方按钮选择目标窗口")
        self.window_title_edit.setReadOnly(True)
        self.select_window_btn = QPushButton("🎯 选取窗口")
        self.select_window_btn.clicked.connect(self.start_select_window_mode)
        self.clear_window_btn = QPushButton("❌ 清除窗口")
        self.clear_window_btn.clicked.connect(self.clear_target_window)
        window_layout.addWidget(self.window_title_edit)
        window_layout.addWidget(self.select_window_btn)
        window_layout.addWidget(self.clear_window_btn)
        window_group.setLayout(window_layout)
        left_layout.addWidget(window_group)

        file_group = QGroupBox("文件操作")
        file_layout = QHBoxLayout()
        self.save_btn = QPushButton("💾 保存配置")
        self.save_btn.clicked.connect(self.save_config)
        self.load_btn = QPushButton("📂 加载配置")
        self.load_btn.clicked.connect(self.load_config)
        file_layout.addWidget(self.save_btn)
        file_layout.addWidget(self.load_btn)
        file_group.setLayout(file_layout)
        left_layout.addWidget(file_group)

        loop_group = QGroupBox("循环设置")
        loop_layout = QVBoxLayout()
        self.loop_type_group = QButtonGroup()
        self.radio_infinite = QRadioButton("无限循环")
        self.radio_count = QRadioButton("次数循环")
        self.radio_infinite.setChecked(True)
        self.loop_type_group.addButton(self.radio_infinite, 0)
        self.loop_type_group.addButton(self.radio_count, 1)
        loop_layout.addWidget(self.radio_infinite)
        loop_layout.addWidget(self.radio_count)
        count_layout = QHBoxLayout()
        count_layout.addWidget(QLabel("次数:"))
        self.loop_spin = QSpinBox()
        self.loop_spin.setRange(1, 99999)
        self.loop_spin.setValue(1000)
        count_layout.addWidget(self.loop_spin)
        loop_layout.addLayout(count_layout)
        loop_group.setLayout(loop_layout)
        left_layout.addWidget(loop_group)

        offset_group = QGroupBox("偏移设置（X轴和Y轴点击偏移量）")
        offset_layout = QVBoxLayout()
        self.offset_checkbox = QCheckBox("启用偏移")
        self.offset_checkbox.setChecked(False)
        self.offset_checkbox.stateChanged.connect(self.toggle_offset)
        x_layout = QHBoxLayout()
        x_layout.addWidget(QLabel("X轴偏移:"))
        self.offset_x_spin = QSpinBox()
        self.offset_x_spin.setRange(0, 50)
        self.offset_x_spin.setValue(5)
        x_layout.addWidget(self.offset_x_spin)
        y_layout = QHBoxLayout()
        y_layout.addWidget(QLabel("Y轴偏移:"))
        self.offset_y_spin = QSpinBox()
        self.offset_y_spin.setRange(0, 50)
        self.offset_y_spin.setValue(5)
        y_layout.addWidget(self.offset_y_spin)
        offset_layout.addWidget(self.offset_checkbox)
        offset_layout.addLayout(x_layout)
        offset_layout.addLayout(y_layout)
        offset_group.setLayout(offset_layout)
        left_layout.addWidget(offset_group)

        random_delay_group = QGroupBox("启动随机延迟（1秒等于1000毫秒）")
        random_delay_layout = QVBoxLayout()
        self.random_delay_checkbox = QCheckBox("启动随机延迟")
        self.random_delay_checkbox.setChecked(False)
        self.random_delay_checkbox.stateChanged.connect(self.toggle_random_delay)
        min_layout = QHBoxLayout()
        min_layout.addWidget(QLabel("最低值(毫秒):"))
        self.random_delay_min_spin = QSpinBox()
        self.random_delay_min_spin.setRange(0, 10000)
        self.random_delay_min_spin.setValue(100)
        min_layout.addWidget(self.random_delay_min_spin)
        max_layout = QHBoxLayout()
        max_layout.addWidget(QLabel("最高值(毫秒):"))
        self.random_delay_max_spin = QSpinBox()
        self.random_delay_max_spin.setRange(0, 10000)
        self.random_delay_max_spin.setValue(1000)
        max_layout.addWidget(self.random_delay_max_spin)
        random_delay_layout.addWidget(self.random_delay_checkbox)
        random_delay_layout.addLayout(min_layout)
        random_delay_layout.addLayout(max_layout)
        random_delay_group.setLayout(random_delay_layout)
        left_layout.addWidget(random_delay_group)

        hotkey_group = QGroupBox("热键设置")
        hotkey_layout = QVBoxLayout()
        self.hotkey_preset = QComboBox()
        self.hotkey_preset.addItems([
            "F12", "F11", "F10", "F9", "F8",
            "Ctrl+A", "Ctrl+S", "Ctrl+Shift+F",
            "Alt+F4", "Shift+F12", "Ctrl+F5"
        ])
        self.hotkey_preset.setCurrentText("F12")
        self.hotkey_preset.currentTextChanged.connect(self.on_hotkey_changed)
        hotkey_layout.addWidget(QLabel("启动/停止热键:"))
        hotkey_layout.addWidget(self.hotkey_preset)
        hotkey_group.setLayout(hotkey_layout)
        left_layout.addWidget(hotkey_group)

        debug_group = QGroupBox("调试与日志")
        debug_layout = QHBoxLayout()
        self.log_checkbox = QCheckBox("📝 启用运行日志")
        self.log_checkbox.setChecked(False)
        self.log_checkbox.stateChanged.connect(lambda state: setattr(self, 'log_enabled', state == Qt.Checked))
        self.open_log_btn = QPushButton("📂 打开日志文件")
        self.open_log_btn.clicked.connect(self.open_log_file)
        debug_layout.addWidget(self.log_checkbox)
        debug_layout.addWidget(self.open_log_btn)
        debug_group.setLayout(debug_layout)
        left_layout.addWidget(debug_group)

        left_layout.addStretch()
        
        left_scroll.setWidget(left_widget)

        right_widget = QWidget()
        right_layout = QVBoxLayout()
        right_layout.setSpacing(10)

        top_widget = QWidget()
        top_layout = QHBoxLayout()
        top_layout.setSpacing(10)

        step_ops_group = QGroupBox("步骤操作")
        step_ops_layout = QGridLayout()
        self.add_image_btn = QPushButton("📸 添加图像")
        self.add_image_btn.clicked.connect(self.add_image_step)
        self.add_coordinate_btn = QPushButton("🎯 添加坐标")
        self.add_coordinate_btn.clicked.connect(self.start_add_coordinate_mode)
        self.delete_btn = QPushButton("🗑️ 删除")
        self.delete_btn.clicked.connect(self.delete_step)
        self.move_up_btn = QPushButton("⬆️ 上移")
        self.move_up_btn.clicked.connect(self.move_step_up)
        self.move_down_btn = QPushButton("⬇️ 下移")
        self.move_down_btn.clicked.connect(self.move_step_down)
        step_ops_layout.addWidget(self.add_image_btn, 0, 0)
        step_ops_layout.addWidget(self.add_coordinate_btn, 0, 1)
        step_ops_layout.addWidget(self.move_up_btn, 1, 0)
        step_ops_layout.addWidget(self.move_down_btn, 1, 1)
        step_ops_layout.addWidget(self.delete_btn, 2, 0, 1, 2)
        step_ops_group.setLayout(step_ops_layout)
        top_layout.addWidget(step_ops_group)

        preview_group = QGroupBox("预览区域")
        preview_layout = QVBoxLayout()
        self.preview_label = QLabel("预览区域")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(150)
        self.preview_label.setMaximumHeight(150)
        self.preview_label.setStyleSheet(
            "border: 1px solid #ccc; border-radius: 3px; "
            "background-color: #f9f9f9; font-size: 11px; padding: 5px;"
        )
        preview_layout.addWidget(self.preview_label)
        preview_group.setLayout(preview_layout)
        top_layout.addWidget(preview_group)

        top_widget.setLayout(top_layout)
        right_layout.addWidget(top_widget)

        steps_group = QGroupBox("步骤列表")
        steps_layout = QVBoxLayout()
        self.steps_table = QTableWidget()
        self.steps_table.setColumnCount(8)
        self.steps_table.setHorizontalHeaderLabels([
            "步骤", "类型", "点击类型", "等待（毫秒）",
            "相似度", "接受偏移", "接受随机延迟", "跳转设置"
        ])

        header = self.steps_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.Stretch)

        self.steps_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.steps_table.setAlternatingRowColors(True)
        self.steps_table.setStyleSheet("""
            QTableWidget {
                gridline-color: #ddd; font-size: 11px;
                border: 1px solid #ccc; border-radius: 3px;
            }
            QTableWidget::item { padding: 6px 4px; min-height: 20px; text-align: center; }
            QTableWidget::item:selected { background-color: #e3f2fd; }
            QHeaderView::section {
                background-color: #f0f0f0; padding: 6px;
                border: 1px solid #ddd; font-weight: bold; text-align: center;
            }
        """)
        self.steps_table.verticalHeader().setDefaultSectionSize(35)
        self.steps_table.verticalHeader().setVisible(False)
        self.steps_table.cellClicked.connect(self.on_step_selected_from_table)
        steps_layout.addWidget(self.steps_table)
        steps_group.setLayout(steps_layout)
        right_layout.addWidget(steps_group)
        right_widget.setLayout(right_layout)

        main_splitter.addWidget(left_scroll)
        main_splitter.addWidget(right_widget)
        main_splitter.setSizes([380, 820])

        main_layout.addWidget(main_splitter)
        self.setCentralWidget(main_widget)

    def open_log_file(self):
        if os.path.exists(self.log_file):
            os.startfile(self.log_file)
        else:
            QMessageBox.information(self, "提示", "尚未生成日志文件！请先勾选日志开关并执行一次工具。")

    def on_master_timer_tick(self):
        now_dt = QDateTime.currentDateTime()
        now_time = now_dt.time()

        if self.schedule_start_cb.isChecked() and not self.is_running:
            target_time = self.schedule_start_time.time()
            if now_time.hour() == target_time.hour() and now_time.minute() == target_time.minute() and now_time.second() == target_time.second():
                self.schedule_start_cb.setChecked(False) 
                self.start_execution()

        if self.schedule_stop_cb.isChecked() and self.is_running and self.execution_start_time:
            elapsed_mins = self.execution_start_time.secsTo(now_dt) / 60.0
            if elapsed_mins >= self.schedule_stop_spin.value():
                self.stop_execution()
                self.status_label.setText("执行进度: 因到达【定时关闭】时间而停止")

        if self.periodic_start_cb.isChecked() and not self.is_running and self.last_stop_time:
            elapsed_mins = self.last_stop_time.secsTo(now_dt) / 60.0
            if elapsed_mins >= self.periodic_start_spin.value():
                self.last_stop_time = None  
                self.start_execution()

    def clear_target_window(self):
        self.target_hwnd = None
        self.window_title_edit.clear()
        QMessageBox.information(self, "提示", "已清除目标窗口")

    def set_controls_enabled(self, enabled):
        controls = [
            self.radio_infinite, self.radio_count, self.loop_spin,
            self.offset_checkbox, self.offset_x_spin, self.offset_y_spin,
            self.random_delay_checkbox, self.random_delay_min_spin, self.random_delay_max_spin,
            self.hotkey_preset, self.steps_table, self.add_image_btn,
            self.add_coordinate_btn, self.delete_btn, self.move_up_btn,
            self.move_down_btn, self.save_btn, self.load_btn, self.select_window_btn
        ]
        for control in controls:
            control.setEnabled(enabled)

    def set_runtime_settings_enabled(self, enabled):
        self.radio_infinite.setEnabled(enabled)
        self.radio_count.setEnabled(enabled)
        self.loop_spin.setEnabled(enabled)
        self.offset_checkbox.setEnabled(enabled)
        self.offset_x_spin.setEnabled(enabled)
        self.offset_y_spin.setEnabled(enabled)
        self.random_delay
