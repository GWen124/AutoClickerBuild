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

# 【全局异常可视化拦截】
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
        self.true_mouse_enabled = False # 新增防封安全变量

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
        self.last_periodic_trigger_time = None 

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

        self.stop_after_loop_cb = QCheckBox("⏳ 跑完本轮后自动停止")
        self.stop_after_loop_cb.setStyleSheet("color: #d35400; font-weight: bold; margin-top: 5px;")
        self.stop_after_loop_cb.toggled.connect(self.on_stop_after_loop_toggled)

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
        self.periodic_start_cb = QCheckBox("周期启动 (勾选后每隔分钟):")
        self.periodic_start_spin = QSpinBox()
        self.periodic_start_spin.setRange(1, 99999)
        self.periodic_start_spin.setValue(60)
        self.periodic_start_cb.stateChanged.connect(self.on_periodic_cb_changed)
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
        
        # 【新增功能】真机物理防封模式
        self.true_mouse_cb = QCheckBox("🛡️ 启用真机物理点击 (防封/防卡加载)")
        self.true_mouse_cb.setStyleSheet("color: #c0392b; font-weight: bold; margin-top: 5px;")
        self.true_mouse_cb.setToolTip("强力推荐：微信小程序等游戏会检测鼠标物理位置。开启此项将接管您的鼠标真实点击，杜绝【点击无反应/卡加载中】问题。")
        self.true_mouse_cb.stateChanged.connect(self.toggle_true_mouse)
        window_layout.addWidget(self.true_mouse_cb)
        
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

    def toggle_true_mouse(self, state):
        self.true_mouse_enabled = (state == Qt.Checked)
        if self.true_mouse_enabled:
            QMessageBox.information(self, "开启物理防封机制", "开启真机物理点击后：\n\n1. 工具将直接接管并移动您真实的系统鼠标。\n2. 此模式能100%防止微信小程序拦截后台点击。\n3. 执行期间请勿乱动鼠标，并确保游戏窗口不要被最小化或遮挡。")

    def on_periodic_cb_changed(self, state):
        if state == Qt.Checked:
            self.last_periodic_trigger_time = QDateTime.currentDateTime()
        else:
            self.last_periodic_trigger_time = None

    def on_stop_after_loop_toggled(self, checked):
        if hasattr(self, 'execution_thread'):
            self.execution_thread.stop_after_current = checked
            if self.is_running and not self.is_paused:
                self.on_step_completed(self.current_step_index, self.execution_thread.current_loop)

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

        if self.periodic_start_cb.isChecked() and self.last_periodic_trigger_time:
            elapsed_mins = self.last_periodic_trigger_time.secsTo(now_dt) / 60.0
            if elapsed_mins >= self.periodic_start_spin.value():
                self.last_periodic_trigger_time = self.last_periodic_trigger_time.addSecs(self.periodic_start_spin.value() * 60)
                if not self.is_running:
                    self.start_execution()
                else:
                    if hasattr(self, 'execution_thread'):
                        self.execution_thread.log("周期启动时间已到，但当前任务仍在运行，自动跳过本次触发避免冲突！", "WARNING")

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
            self.move_down_btn, self.save_btn, self.load_btn, self.select_window_btn,
            self.true_mouse_cb
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
        self.random_delay_checkbox.setEnabled(enabled)
        self.random_delay_min_spin.setEnabled(enabled)
        self.random_delay_max_spin.setEnabled(enabled)

    def setup_global_hotkey(self):
        try:
            if self.global_hotkey_listener:
                self.global_hotkey_listener.stop()
            keys = self.parse_hotkey_string(self.hotkey)
            self.global_hotkey_listener = KeyboardListener(
                on_press=lambda key: self.on_global_key_press(key, keys)
            )
            self.global_hotkey_listener.start()
        except Exception as e:
            pass

    def parse_hotkey_string(self, hotkey_str):
        keys = []
        parts = hotkey_str.lower().split('+')
        for part in parts:
            part = part.strip()
            if part == 'ctrl': keys.append(Key.ctrl)
            elif part == 'alt': keys.append(Key.alt)
            elif part == 'shift': keys.append(Key.shift)
            elif part.startswith('f') and part[1:].isdigit():
                keys.append(getattr(Key, f'f{part[1:]}'))
            elif len(part) == 1: keys.append(part)
        return keys

    def on_global_key_press(self, key, target_keys):
        try:
            if isinstance(target_keys[-1], str):
                if hasattr(key, 'char') and key.char and key.char.lower() == target_keys[-1].lower():
                    if all(
                        self.keyboard.ctrl_pressed if m == Key.ctrl else
                        self.keyboard.alt_pressed if m == Key.alt else
                        self.keyboard.shift_pressed
                        for m in target_keys[:-1]
                    ):
                        self.hotkey_triggered.emit()
            else:
                if key == target_keys[-1]:
                    if all(
                        self.keyboard.ctrl_pressed if m == Key.ctrl else
                        self.keyboard.alt_pressed if m == Key.alt else
                        self.keyboard.shift_pressed
                        for m in target_keys[:-1]
                    ):
                        self.hotkey_triggered.emit()
        except:
            pass
        return True

    def start_select_window_mode(self):
        self.is_selecting_window = True
        self.setWindowState(Qt.WindowMinimized)
        self.preview_label.setText("请将鼠标移动到目标窗口上并点击左键...\n按ESC取消")
        self.preview_label.setStyleSheet("border: 1px solid #ccc; background-color: #fff3cd; color: #856404;")
        self.mouse_listener = MouseListener(on_click=self.on_select_window_click)
        self.mouse_listener.start()
        self.keyboard_listener = KeyboardListener(on_press=self.on_select_window_cancel)
        self.keyboard_listener.start()

    def on_select_window_click(self, x, y, button, pressed):
        if pressed and button == Button.left:
            hwnd = win32gui.WindowFromPoint((x, y))
            while win32gui.GetParent(hwnd) != 0:
                hwnd = win32gui.GetParent(hwnd)
            window_title = win32gui.GetWindowText(hwnd)
            self.window_selected.emit(hwnd, window_title)
            self.stop_select_window_mode_signal.emit()
            return False
        return True
        
    def on_window_selected(self, hwnd, title):
        self.target_hwnd = hwnd
        self.window_title_edit.setText(f"{title} (HWND: {hwnd})")

    def on_select_window_cancel(self, key):
        if key == Key.esc:
            self.stop_select_window_mode_signal.emit()
            return False
        return True

    def stop_select_window_mode(self):
        self.is_selecting_window = False
        if self.mouse_listener:
            self.mouse_listener.stop()
            self.mouse_listener = None
        if self.keyboard_listener:
            self.keyboard_listener.stop()
            self.keyboard_listener = None
        self.showNormal()
        self.activateWindow()
        self.preview_label.setText("预览区域")
        self.preview_label.setStyleSheet("border: 1px solid #ccc; background-color: #f9f9f9;")

    def start_add_coordinate_mode(self):
        self.is_adding_coordinate = True
        self.setWindowState(Qt.WindowMinimized)
        self.preview_label.setText("请在屏幕任意位置点击要添加的坐标...\n按ESC或右键取消")
        self.preview_label.setStyleSheet("border: 1px solid #ccc; background-color: #fff3cd; color: #856404;")
        self.mouse_listener = MouseListener(on_click=self.on_global_mouse_click)
        self.mouse_listener.start()
        self.keyboard_listener = KeyboardListener(on_press=self.on_global_key_press_for_cancel)
        self.keyboard_listener.start()

    def on_global_mouse_click(self, x, y, button, pressed):
        if pressed:
            if button == Button.left:
                self.coordinate_captured.emit(x, y)
                return False
            elif button == Button.right:
                self.stop_coordinate_mode.emit()
                return False
        return True

    def on_global_key_press_for_cancel(self, key):
        if key == Key.esc:
            self.stop_coordinate_mode.emit()
            return False
        return True

    def stop_add_coordinate_mode(self):
        self.is_adding_coordinate = False
        if self.mouse_listener:
            self.mouse_listener.stop()
            self.mouse_listener = None
        if self.keyboard_listener:
            self.keyboard_listener.stop()
            self.keyboard_listener = None
        self.showNormal()
        self.activateWindow()
        self.preview_label.setText("预览区域")
        self.preview_label.setStyleSheet("border: 1px solid #ccc; background-color: #f9f9f9;")

    def add_image_step(self):
        self.is_adding_image = True
        self.setWindowState(Qt.WindowMinimized)
        self.screenshot_window = ScreenshotWindow(self)
        self.screenshot_window.image_captured.connect(self.on_image_captured)
        self.screenshot_window.closed.connect(self.on_screenshot_closed)
        self.screenshot_window.setWindowFlags(self.screenshot_window.windowFlags() | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.screenshot_window.show()
        self.screenshot_window.raise_()
        self.screenshot_window.activateWindow()

    def on_screenshot_closed(self):
        self.is_adding_image = False
        self.showNormal()
        self.activateWindow()

    def on_coordinate_captured(self, x, y):
        rel_x, rel_y = x, y
        if self.target_hwnd:
            left, top, _, _ = win32gui.GetWindowRect(self.target_hwnd)
            rel_x -= left
            rel_y -= top
        step = Step(
            step_type='coordinate', x=rel_x, y=rel_y, wait_time=1000, click_type='left',
            random_delay_enabled=self.random_delay_checkbox.isChecked(),
            random_delay_min=self.random_delay_min_spin.value(),
            random_delay_max=self.random_delay_max_spin.value()
        )
        self.steps.append(step)
        self.update_steps_table()
        self.stop_add_coordinate_mode()

    def toggle_offset(self, state):
        enabled = state == Qt.Checked
        self.offset_x_spin.setEnabled(enabled)
        self.offset_y_spin.setEnabled(enabled)

    def toggle_random_delay(self, state):
        enabled = state == Qt.Checked
        self.random_delay_min_spin.setEnabled(enabled)
        self.random_delay_max_spin.setEnabled(enabled)

    def on_hotkey_changed(self, text):
        self.hotkey = text.strip()
        self.setup_global_hotkey()

    def toggle_execution(self):
        if self.is_running: self.stop_execution()
        else: self.start_execution()

    def get_loop_count(self):
        return 999999 if self.radio_infinite.isChecked() else self.loop_spin.value()

    def start_execution(self):
        if not self.steps:
            QMessageBox.warning(self, "错误", "没有可执行的步骤")
            return
            
        self.stop_after_loop_cb.setChecked(False)
        self.execution_thread.stop_after_current = False
            
        self.update_all_settings()
        self.execution_start_time = QDateTime.currentDateTime()
        self.last_stop_time = None

        if self.is_paused:
            self.is_paused = False
            self.is_running = True
            self.execution_thread.resume()
            self.pause_btn.setText("⏸ 暂停执行")
            self.status_label.setText("执行进度: 已从暂停恢复")
        else:
            self.current_step_index = 0
            self.is_running = True
            self.is_paused = False
            loop_count = self.get_loop_count()
            self.execution_thread.set_params(loop_count, self.current_step_index)
            self.execution_thread.stop_after_current = self.stop_after_loop_cb.isChecked()
            self.execution_thread.start()
            self.status_label.setText("执行进度: 正在初始化...")

        self.set_controls_enabled(False)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.pause_btn.setEnabled(True)

    def stop_execution(self):
        self.is_running = False
        self.is_paused = False
        self.current_step_index = 0
        self.execution_thread.stop()
        
        self.set_controls_enabled(True)
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText("⏸ 暂停执行")
        
        self.stop_after_loop_cb.setChecked(False)

        self.last_stop_time = QDateTime.currentDateTime()
        self.status_label.setText("执行进度: 已停止")

    def pause_execution(self):
        if self.is_running and not self.is_paused:
            self.is_paused = True
            self.is_running = False
            self.execution_thread.pause()
            
            self.start_btn.setEnabled(True)
            self.pause_btn.setText("▶ 继续执行")
            self.status_label.setText("执行进度: 任务已暂停 (可修改左侧循环设置)")
            self.set_runtime_settings_enabled(True)
            
        elif self.is_paused:
            self.update_all_settings()
            
            new_loop_count = self.get_loop_count()
            if new_loop_count != 999999 and self.execution_thread.current_loop >= new_loop_count:
                self.execution_thread.current_loop = 0
                
            self.execution_thread.loop_count = new_loop_count

            self.is_paused = False
            self.is_running = True
            self.execution_thread.resume()
            
            self.start_btn.setEnabled(False)
            self.pause_btn.setText("⏸ 暂停执行")
            self.status_label.setText("执行进度: 任务已恢复")
            self.set_runtime_settings_enabled(False)

    def update_all_settings(self):
        for step in self.steps:
            step.random_delay_enabled = self.random_delay_checkbox.isChecked()
            step.random_delay_min = self.random_delay_min_spin.value()
            step.random_delay_max = self.random_delay_max_spin.value()
            
        self.offset_enabled = self.offset_checkbox.isChecked()
        self.offset_x = self.offset_x_spin.value()
        self.offset_y = self.offset_y_spin.value()
        self.log_enabled = self.log_checkbox.isChecked()
        self.true_mouse_enabled = self.true_mouse_cb.isChecked() # 同步安全变量

    def on_execution_finished(self):
        self.is_running = False
        self.is_paused = False
        self.current_step_index = 0
        
        self.set_controls_enabled(True)
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText("⏸ 暂停执行")
        
        self.stop_after_loop_cb.setChecked(False)

        self.last_stop_time = QDateTime.currentDateTime()
        self.status_label.setText("执行进度: 任务执行完毕")

    def on_execution_error(self, error_msg):
        self.is_running = False
        self.is_paused = False
        self.current_step_index = 0
        
        self.set_controls_enabled(True)
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText("⏸ 暂停执行")
        
        self.stop_after_loop_cb.setChecked(False)
        
        self.last_stop_time = QDateTime.currentDateTime()
        self.status_label.setText("执行进度: 发生错误而停止")
        QMessageBox.critical(self, "错误", f"执行出错: {error_msg}")

    def on_step_completed(self, step_index, current_loop):
        self.current_step_index = step_index
        self.steps_table.selectRow(step_index)
        
        status_text = f"执行进度: [第 {current_loop} 轮] 正在执行第 {step_index + 1} 步"
        if getattr(self.execution_thread, 'stop_after_current', False):
            status_text += "  ⏳(将在本轮结束后停止)"
            
        self.status_label.setText(status_text)

    def on_image_captured(self, image_path):
        if self.target_hwnd:
            left, top, right, bottom = win32gui.GetWindowRect(self.target_hwnd)
            bbox = (left, top, right, bottom)
            screen_image = ImageGrab.grab(bbox)
            template_path = os.path.join(self.screenshot_dir, f"template_{int(time.time())}.png")
            screen_image.save(template_path)
            image_path = template_path
        step = Step(
            step_type='image', image_path=image_path, wait_time=1000, similarity=0.8, click_type='left',
            random_delay_enabled=self.random_delay_checkbox.isChecked(),
            random_delay_min=self.random_delay_min_spin.value(),
            random_delay_max=self.random_delay_max_spin.value()
        )
        self.steps.append(step)
        self.update_steps_table()

    def delete_step(self):
        current_row = self.steps_table.currentRow()
        if current_row >= 0:
            del self.steps[current_row]
            self.update_steps_table()

    def move_step_up(self):
        current_row = self.steps_table.currentRow()
        if current_row > 0:
            self.steps[current_row], self.steps[current_row - 1] = self.steps[current_row - 1], self.steps[current_row]
            self.update_steps_table()
            self.steps_table.selectRow(current_row - 1)

    def move_step_down(self):
        current_row = self.steps_table.currentRow()
        if current_row < len(self.steps) - 1:
            self.steps[current_row], self.steps[current_row + 1] = self.steps[current_row + 1], self.steps[current_row]
            self.update_steps_table()
            self.steps_table.selectRow(current_row + 1)

    def update_steps_table(self):
        self.steps_table.setRowCount(len(self.steps))
        for i, step in enumerate(self.steps):
            step_item = QTableWidgetItem(f"{i + 1}")
            step_item.setTextAlignment(Qt.AlignCenter)
            self.steps_table.setItem(i, 0, step_item)

            type_item = QTableWidgetItem("图像识别" if step.step_type == 'image' else "坐标点击")
            type_item.setTextAlignment(Qt.AlignCenter)
            self.steps_table.setItem(i, 1, type_item)

            click_combo = QComboBox()
            click_combo.addItems(["左键单击", "右键单击", "双击", "跳转"])
            click_combo.setCurrentIndex(0 if step.click_type == 'left' else 1 if step.click_type == 'right' else 2 if step.click_type == 'double' else 3)
            click_combo.currentTextChanged.connect(lambda text, row=i: self.update_step_click_type(row, text))
            self.steps_table.setCellWidget(i, 2, click_combo)

            wait_spin = QSpinBox()
            wait_spin.setRange(0, 3600000)
            wait_spin.setValue(step.wait_time)
            wait_spin.valueChanged.connect(lambda value, row=i: self.update_step_wait_time(row, value))
            self.steps_table.setCellWidget(i, 3, wait_spin)

            if step.step_type == 'image':
                similarity_spin = QDoubleSpinBox()
                similarity_spin.setRange(0.1, 1.0)
                similarity_spin.setSingleStep(0.05)
                similarity_spin.setValue(step.similarity)
                similarity_spin.setDecimals(2)
                similarity_spin.valueChanged.connect(lambda value, row=i: self.update_step_similarity(row, value))
                self.steps_table.setCellWidget(i, 4, similarity_spin)
            else:
                similarity_item = QTableWidgetItem("-")
                similarity_item.setTextAlignment(Qt.AlignCenter)
                self.steps_table.setItem(i, 4, similarity_item)

            offset_checkbox = QCheckBox()
            offset_checkbox.setStyleSheet("QCheckBox { margin-left: auto; margin-right: auto; }")
            offset_checkbox.setChecked(step.accept_offset)
            offset_checkbox.stateChanged.connect(lambda state, row=i: self.update_step_accept_offset(row, state))
            self.steps_table.setCellWidget(i, 5, offset_checkbox)

            random_delay_checkbox = QCheckBox()
            random_delay_checkbox.setStyleSheet("QCheckBox { margin-left: auto; margin-right: auto; }")
            random_delay_checkbox.setChecked(step.accept_random_delay)
            random_delay_checkbox.stateChanged.connect(lambda state, row=i: self.update_step_accept_random_delay(row, state))
            self.steps_table.setCellWidget(i, 6, random_delay_checkbox)

            jump_combo = QComboBox()
            jump_combo.addItem("无跳转", -1)
            for j in range(len(self.steps)):
                jump_combo.addItem(f"步骤 {j + 1}", j)
            if step.jump_to is not None and step.jump_to < len(self.steps):
                jump_combo.setCurrentIndex(step.jump_to + 1)
            jump_combo.currentIndexChanged.connect(lambda index, row=i: self.update_step_jump_to(row, index))
            
            if step.step_type == 'image' and step.click_type == 'jump':
                jump_combo.setEnabled(True)
            else:
                jump_combo.setEnabled(False)
                jump_combo.setCurrentIndex(0)
                if step.step_type == 'coordinate':
                    step.click_type = 'left'
                    step.jump_to = None
            self.steps_table.setCellWidget(i, 7, jump_combo)

    def update_step_jump_to(self, row, index):
        if row < len(self.steps):
            combo = self.steps_table.cellWidget(row, 7)
            if combo:
                jump_to = combo.itemData(index)
                self.steps[row].jump_to = jump_to if jump_to != -1 else None

    def update_step_accept_offset(self, row, state):
        if row < len(self.steps): self.steps[row].accept_offset = (state == Qt.Checked)

    def update_step_accept_random_delay(self, row, state):
        if row < len(self.steps): self.steps[row].accept_random_delay = (state == Qt.Checked)

    def update_step_click_type(self, row, text):
        if row < len(self.steps):
            if text == "左键单击": self.steps[row].click_type = 'left'
            elif text == "右键单击": self.steps[row].click_type = 'right'
            elif text == "双击": self.steps[row].click_type = 'double'
            elif text == "跳转": self.steps[row].click_type = 'jump'
            jump_combo = self.steps_table.cellWidget(row, 7)
            if jump_combo:
                if text == "跳转" and self.steps[row].step_type == 'image': jump_combo.setEnabled(True)
                else:
                    jump_combo.setEnabled(False)
                    self.steps[row].jump_to = None
                    jump_combo.setCurrentIndex(0)

    def update_step_wait_time(self, row, value):
        if row < len(self.steps): self.steps[row].wait_time = value

    def update_step_similarity(self, row, value):
        if row < len(self.steps): self.steps[row].similarity = value

    def on_step_selected_from_table(self, row, column):
        if row < len(self.steps):
            step = self.steps[row]
            if step.step_type == 'image' and step.image_path and os.path.exists(step.image_path):
                pixmap = QPixmap(step.image_path)
                self.preview_label.setPixmap(pixmap.scaled(300, 150, Qt.KeepAspectRatio))
            else:
                self.preview_label.setText(f"坐标: ({step.x}, {step.y})")

    def save_config(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "保存配置", "", "JSON文件 (*.json)")
        if not file_path: return
        config = {
            "steps": [], "hotkey": self.hotkey, "loop_type": self.loop_type_group.checkedId(),
            "loop_count": self.loop_spin.value(), "offset_enabled": self.offset_checkbox.isChecked(),
            "offset_x": self.offset_x_spin.value(), "offset_y": self.offset_y_spin.value(),
            "random_delay_enabled": self.random_delay_checkbox.isChecked(),
            "random_delay_min": self.random_delay_min_spin.value(),
            "random_delay_max": self.random_delay_max_spin.value(),
            "schedule_start_enabled": self.schedule_start_cb.isChecked(),
            "schedule_start_time": self.schedule_start_time.time().toString("HH:mm:ss"),
            "schedule_stop_enabled": self.schedule_stop_cb.isChecked(),
            "schedule_stop_mins": self.schedule_stop_spin.value(),
            "periodic_start_enabled": self.periodic_start_cb.isChecked(),
            "periodic_start_mins": self.periodic_start_spin.value(),
            "true_mouse_enabled": self.true_mouse_cb.isChecked() # 保存防封设置
        }
        config_dir = os.path.dirname(file_path)
        for step in self.steps:
            step_data = {
                "step_type": step.step_type, "image_path": step.image_path, "x": step.x, "y": step.y,
                "click_type": step.click_type, "wait_time": step.wait_time, "similarity": step.similarity,
                "jump_to": step.jump_to, "random_delay_enabled": step.random_delay_enabled,
                "random_delay_min": step.random_delay_min, "random_delay_max": step.random_delay_max,
                "accept_offset": step.accept_offset, "accept_random_delay": step.accept_random_delay
            }
            if step.step_type == "image" and step.image_path:
                src_path = step.image_path
                if os.path.isabs(src_path):
                    dst_path = os.path.join(config_dir, "screenshots", os.path.basename(src_path))
                    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
                    import shutil
                    shutil.copy2(src_path, dst_path)
                    step_data["image_path"] = os.path.relpath(dst_path, config_dir)
            config["steps"].append(step_data)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        self.config_name_label.setText(f"当前配置: {os.path.basename(file_path)}")
        QMessageBox.information(self, "成功", "配置保存成功！")

    def load_config(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "加载配置", "", "JSON文件 (*.json)")
        if not file_path: return
        with open(file_path, 'r', encoding='utf-8') as f: config = json.load(f)
        self.steps.clear()
        self.current_step_index = 0
        self.is_running = False
        self.is_paused = False
        self.target_hwnd = None
        self.window_title_edit.clear()
        config_dir = os.path.dirname(file_path)
        for step_data in config["steps"]:
            if step_data["step_type"] == "image" and step_data["image_path"]:
                path = step_data["image_path"]
                if os.path.isabs(path): final_path = path
                else:
                    config_path = os.path.join(config_dir, path)
                    base_path = os.path.join(self.base_dir, path)
                    base_screenshots_path = os.path.join(self.base_dir, "screenshots", os.path.basename(path))
                    config_screenshots_path = os.path.join(config_dir, "screenshots", os.path.basename(path))
                    if os.path.exists(config_path): final_path = config_path
                    elif os.path.exists(base_path): final_path = base_path
                    elif os.path.exists(base_screenshots_path): final_path = base_screenshots_path
                    elif os.path.exists(config_screenshots_path): final_path = config_screenshots_path
                    else: final_path = config_path
                step_data["image_path"] = final_path
            step = Step(**step_data)
            self.steps.append(step)
        self.hotkey = config.get("hotkey", "F12")
        self.hotkey_preset.setCurrentText(self.hotkey)
        self.setup_global_hotkey()
        loop_type = config.get("loop_type", 0)
        if loop_type == 0: self.radio_infinite.setChecked(True)
        else: self.radio_count.setChecked(True)
        self.loop_spin.setValue(config.get("loop_count", 1000))
        offset_enabled = config.get("offset_enabled", False)
        self.offset_checkbox.setChecked(offset_enabled)
        self.offset_x_spin.setValue(config.get("offset_x", 5))
        self.offset_y_spin.setValue(config.get("offset_y", 5))
        self.toggle_offset(Qt.Checked if offset_enabled else Qt.Unchecked)
        random_delay_enabled = config.get("random_delay_enabled", False)
        self.random_delay_checkbox.setChecked(random_delay_enabled)
        self.random_delay_min_spin.setValue(config.get("random_delay_min", 100))
        self.random_delay_max_spin.setValue(config.get("random_delay_max", 1000))
        self.toggle_random_delay(Qt.Checked if random_delay_enabled else Qt.Unchecked)

        self.schedule_start_cb.setChecked(config.get("schedule_start_enabled", False))
        if "schedule_start_time" in config:
            self.schedule_start_time.setTime(QTime.fromString(config["schedule_start_time"], "HH:mm:ss"))
        self.schedule_stop_cb.setChecked(config.get("schedule_stop_enabled", False))
        self.schedule_stop_spin.setValue(config.get("schedule_stop_mins", 60))
        self.periodic_start_cb.setChecked(config.get("periodic_start_enabled", False))
        self.periodic_start_spin.setValue(config.get("periodic_start_mins", 60))
        
        self.true_mouse_cb.setChecked(config.get("true_mouse_enabled", False))

        self.update_steps_table()
        
        config_name = os.path.basename(file_path)
        self.config_name_label.setText(f"当前配置: {config_name}")
        self.status_label.setText("执行进度: 配置已加载，准备就绪")
        
        QMessageBox.information(self, "成功", "配置加载成功！")

    def closeEvent(self, event):
        self.stop_execution()
        if self.global_hotkey_listener: self.global_hotkey_listener.stop()
        if self.mouse_listener: self.mouse_listener.stop()
        if self.keyboard_listener: self.keyboard_listener.stop()
        event.accept()

class ScreenshotWindow(QWidget):
    image_captured = pyqtSignal(str)
    closed = pyqtSignal()
    def __init__(self, parent=None):
        super().__init__()
        self.parent = parent
        self.setWindowTitle("截图")
        self.setWindowState(Qt.WindowFullScreen)
        self.setWindowOpacity(0.3)
        self.setMouseTracking(True)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.start_pos = None
        self.end_pos = None
        self.is_selecting = False
        self.shortcut_esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self.shortcut_esc.activated.connect(self.cancel_screenshot)

    def cancel_screenshot(self):
        self.close()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start_pos = event.pos()
            self.is_selecting = True
        elif event.button() == Qt.RightButton:
            self.cancel_screenshot()

    def mouseMoveEvent(self, event):
        if self.is_selecting:
            self.end_pos = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_selecting:
            self.is_selecting = False
            self.end_pos = event.pos()
            x = min(self.start_pos.x(), self.end_pos.x())
            y = min(self.start_pos.y(), self.end_pos.y())
            width = abs(self.start_pos.x() - self.end_pos.x())
            height = abs(self.start_pos.y() - self.end_pos.y())
            screen = QApplication.primaryScreen()
            pixmap = screen.grabWindow(0, x, y, width, height)
            image_path = os.path.join(self.parent.screenshot_dir, f"screenshot_{int(time.time())}.png")
            pixmap.save(image_path)
            self.image_captured.emit(image_path)
            self.close()

    def paintEvent(self, event):
        if self.is_selecting and self.start_pos and self.end_pos:
            painter = QPainter(self)
            painter.setPen(QPen(Qt.red, 2, Qt.DashLine))
            x = min(self.start_pos.x(), self.end_pos.x())
            y = min(self.start_pos.y(), self.end_pos.y())
            width = abs(self.start_pos.x() - self.end_pos.x())
            height = abs(self.start_pos.y() - self.end_pos.y())
            painter.drawRect(x, y, width, height)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape: self.cancel_screenshot()

    def closeEvent(self, event):
        self.closed.emit()
        event.accept()

class ExecutionThread(QThread):
    finished = pyqtSignal()
    error = pyqtSignal(str)
    step_completed = pyqtSignal(int, int)

    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self.loop_count = 1
        self.current_step_index = 0
        self.is_stopped = False
        self.is_paused = False
        self.current_loop = 0
        
        self.last_hwnd = None
        self.last_pos = None
        self.stop_after_current = False

    def set_params(self, loop_count, start_index=0):
        self.loop_count = loop_count
        self.current_step_index = start_index
        self.current_loop = 0
        self.is_stopped = False
        self.is_paused = False

    def emergency_release(self):
        if hasattr(self, 'last_hwnd') and self.last_hwnd and hasattr(self, 'last_pos') and self.last_pos:
            try:
                x, y = self.last_pos
                lparam = win32api.MAKELONG(int(x), int(y))
                win32gui.PostMessage(self.last_hwnd, win32con.WM_LBUTTONUP, 0, lparam)
                win32gui.PostMessage(self.last_hwnd, win32con.WM_RBUTTONUP, 0, lparam)
            except:
                pass

    def stop(self): 
        self.is_stopped = True
        self.emergency_release()

    def pause(self): 
        self.is_paused = True
        self.emergency_release()

    def resume(self):
        self.is_paused = False

    def log(self, message, level="INFO"):
        if getattr(self.parent, 'log_enabled', False):
            if level == "INFO":
                self.parent.logger.info(message)
            elif level == "DEBUG":
                self.parent.logger.debug(message)
            elif level == "ERROR":
                self.parent.logger.error(message)
            elif level == "WARNING":
                self.parent.logger.warning(message)
            print(f"[{level}] {message}")

    def run(self):
        try:
            if not self.parent.steps:
                self.log("步骤列表为空，退出执行", "ERROR")
                self.finished.emit()
                return
                
            self.log(f"=== 开始总任务，设定循环总数: {self.loop_count} ===")
            
            while (self.current_loop < self.loop_count or self.loop_count == 999999) and not self.is_stopped:
                self.current_loop += 1
                self.log(f"\n--- 进入第 {self.current_loop} 轮循环 ---")
                
                while self.current_step_index < len(self.parent.steps) and not self.is_stopped:
                    while self.is_paused and not self.is_stopped: 
                        time.sleep(0.1)
                        
                    if self.is_stopped or self.current_step_index >= len(self.parent.steps): 
                        break
                    
                    self.step_completed.emit(self.current_step_index, self.current_loop)

                    step = self.parent.steps[self.current_step_index]
                    self.log(f"[第 {self.current_loop} 轮] 准备执行 步骤 {self.current_step_index + 1} (类型: {step.step_type})")
                    
                    target_pos = None
                    if step.step_type == 'image':
                        self.log(f"开始查找图片: {step.image_path} (相似度要求: {step.similarity})", "DEBUG")
                        target_pos = self.find_image(step.image_path, step.similarity)
                        if target_pos:
                            self.log(f"图片匹配成功，找到相对坐标: {target_pos}", "DEBUG")
                            if self.parent.target_hwnd:
                                left, top, _, _ = win32gui.GetWindowRect(self.parent.target_hwnd)
                                target_pos = (target_pos[0] + left, target_pos[1] + top)
                                self.log(f"换算为绝对坐标: {target_pos}", "DEBUG")
                        else:
                            self.log("图片匹配失败，未找到目标", "DEBUG")
                    else:
                        target_pos = (step.x, step.y)
                        self.log(f"使用固定坐标: {target_pos}", "DEBUG")
                        if self.parent.target_hwnd:
                            left, top, _, _ = win32gui.GetWindowRect(self.parent.target_hwnd)
                            target_pos = (target_pos[0] + left, target_pos[1] + top)

                    total_wait = step.wait_time
                    if step.accept_random_delay and step.random_delay_enabled:
                        rand_extra = random.randint(step.random_delay_min, step.random_delay_max)
                        total_wait += rand_extra
                        self.log(f"叠加随机延迟: +{rand_extra}ms，总等待时长为: {total_wait}ms", "DEBUG")
                    else:
                        self.log(f"设定等待时长为: {total_wait}ms", "DEBUG")

                    if step.step_type == 'image' and step.click_type == 'jump':
                        if target_pos is not None and step.jump_to is not None:
                            self.log(f"执行跳转逻辑 -> 跳转至步骤 {step.jump_to + 1}")
                            self.current_step_index = step.jump_to
                            self._sleep_interruptible(total_wait / 1000.0)
                            continue

                    if target_pos is not None and step.click_type != 'jump':
                        self.log(f"发起点击操作 -> 坐标 {target_pos}，类型: {step.click_type}")
                        self.click_target(target_pos, step)
                    elif target_pos is None and step.click_type != 'jump':
                        self.log(f"⚠️ 步骤 {self.current_step_index + 1}: 目标不存在，直接跳过点击环节", "WARNING")

                    self.log(f"开始休眠等待 {total_wait}ms...")
                    self._sleep_interruptible(total_wait / 1000.0)

                    if step.click_type != 'jump' or (step.click_type == 'jump' and target_pos is None):
                        self.log(f"步骤 {self.current_step_index + 1} 执行完毕。")
                        self.current_step_index += 1
                    
                if not self.is_stopped:
                    self.log(f"--- 第 {self.current_loop} 轮循环执行完毕 ---")
                    self.current_step_index = 0
                    
                    if self.stop_after_current:
                        self.log("已触发【跑完本轮后停止】，安全结束任务。", "INFO")
                        break
                    
                    if self.current_loop < self.loop_count or self.loop_count == 999999:
                        pass
                        
            self.log("=== 总任务全部完成 ===")
            self.finished.emit()
        except Exception as e:
            self.log(f"发生崩溃级异常: {str(e)}", "ERROR")
            self.error.emit(str(e))

    def _sleep_interruptible(self, seconds):
        target_time = time.perf_counter() + seconds
        while time.perf_counter() < target_time:
            if self.is_stopped:
                break
                
            if self.is_paused:
                pause_start = time.perf_counter()
                while self.is_paused and not self.is_stopped:
                    time.sleep(0.1)
                target_time += (time.perf_counter() - pause_start)
                
            time.sleep(0.02) 

    def find_image(self, image_path, similarity=0.8):
        if not os.path.exists(image_path): return None
        try:
            img_array = np.fromfile(image_path, dtype=np.uint8)
            template = cv2.imdecode(img_array, cv2.IMREAD_GRAYSCALE)
        except: return None
        if template is None: return None

        if self.parent.target_hwnd:
            left, top, right, bottom = win32gui.GetWindowRect(self.parent.target_hwnd)
            if right - left <= 0 or bottom - top <= 0: return None
            bbox = (left, top, right, bottom)
            screen_image = ImageGrab.grab(bbox)
        else:
            screen_image = ImageGrab.grab()

        screenshot = cv2.cvtColor(np.array(screen_image), cv2.COLOR_RGB2GRAY)

        if screenshot.shape[0] < template.shape[0] or screenshot.shape[1] < template.shape[1]: return None
        result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val >= similarity:
            h, w = template.shape[:2]
            return (max_loc[0] + w // 2, max_loc[1] + h // 2)
        return None

    def click_target(self, target_pos, step):
        x, y = target_pos
        if step.accept_offset and getattr(self.parent, 'offset_enabled', False):
            x += random.randint(-getattr(self.parent, 'offset_x', 5), getattr(self.parent, 'offset_x', 5))
            y += random.randint(-getattr(self.parent, 'offset_y', 5), getattr(self.parent, 'offset_y', 5))
            self.log(f"应用坐标偏移，最终点击绝对坐标: ({x}, {y})", "DEBUG")
            
        # 【核心分支】：如果启用了真机物理点击
        if getattr(self.parent, 'true_mouse_enabled', False):
            self.log(f"🛡️ 使用真机物理鼠标点击...", "DEBUG")
            
            # 计算屏幕绝对坐标 (如果绑定了窗口，需加上窗口偏移量)
            abs_x, abs_y = x, y
            if self.parent.target_hwnd:
                left, top, _, _ = win32gui.GetWindowRect(self.parent.target_hwnd)
                abs_x += left
                abs_y += top
                
            self.parent.mouse.position = (abs_x, abs_y)
            time.sleep(0.08) # 模拟手移动到位后的短暂停留
            
            if step.click_type == 'left':
                self.parent.mouse.press(Button.left)
                time.sleep(random.uniform(0.05, 0.12)) # 模拟人手点击耗时
                self.parent.mouse.release(Button.left)
            elif step.click_type == 'right':
                self.parent.mouse.press(Button.right)
                time.sleep(random.uniform(0.05, 0.12))
                self.parent.mouse.release(Button.right)
            elif step.click_type == 'double':
                self.parent.mouse.click(Button.left, 2)
            
            self.log(f"真机物理点击执行完毕", "DEBUG")
            return # 执行完物理点击后直接返回，不走下方的后台静默代码
            
        # 【原有分支】：后台静默点击
        if self.parent.target_hwnd:
            left, top, _, _ = win32gui.GetWindowRect(self.parent.target_hwnd)
            rel_x, rel_y = x - left, y - top
            self.log(f"向句柄发送后台静默指令 -> 相对坐标: ({rel_x}, {rel_y})", "DEBUG")
            
            if step.click_type == 'left': down_msg, up_msg = win32con.WM_LBUTTONDOWN, win32con.WM_LBUTTONUP
            elif step.click_type == 'right': down_msg, up_msg = win32con.WM_RBUTTONDOWN, win32con.WM_RBUTTONUP
            elif step.click_type == 'double':
                self.click_target_backend(self.parent.target_hwnd, rel_x, rel_y, win32con.WM_LBUTTONDOWN, win32con.WM_LBUTTONUP)
                time.sleep(0.05)
                self.click_target_backend(self.parent.target_hwnd, rel_x, rel_y, win32con.WM_LBUTTONDOWN, win32con.WM_LBUTTONUP)
                return
            else: return
            self.click_target_backend(self.parent.target_hwnd, rel_x, rel_y, down_msg, up_msg)
        else:
            self.parent.mouse.position = (x, y)
            time.sleep(0.05)
            if step.click_type == 'left': self.parent.mouse.click(Button.left)
            elif step.click_type == 'right': self.parent.mouse.click(Button.right)
            elif step.click_type == 'double':
                self.parent.mouse.click(Button.left)
                time.sleep(0.05)
                self.parent.mouse.click(Button.left)

    def click_target_backend(self, hwnd, x, y, down_msg, up_msg):
        self.last_hwnd = hwnd
        self.last_pos = (x, y)
        
        try:
            lparam = win32api.MAKELONG(int(x), int(y))
            win32gui.PostMessage(hwnd, win32con.WM_MOUSEMOVE, 0, lparam)
            time.sleep(0.03) 
            win32gui.PostMessage(hwnd, down_msg, win32con.MK_LBUTTON, lparam)
            time.sleep(0.08) 
            win32gui.PostMessage(hwnd, up_msg, 0, lparam)
            time.sleep(0.02)
        except Exception as e:
            self.log(f"PostMessage 发送失败: {str(e)}", "ERROR")
            self.emergency_release()

if __name__ == "__main__":
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    window = AutoClickerApp()
    window.show()
    sys.exit(app.exec_())
