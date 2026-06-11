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
from PIL import ImageGrab
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from pynput.mouse import Controller as MouseController, Listener as MouseListener, Button
from pynput.keyboard import Controller as KeyboardController, Listener as KeyboardListener, Key

# 设置 DPI 感知
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
    screenshot_closed = pyqtSignal()

    def get_base_path(self):
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        else:
            return os.path.dirname(os.path.abspath(__file__))

    def __init__(self):
        super().__init__()
        self.base_title = "自动点击工具 V1.3 - 防卡死最终版"
        self.setWindowTitle(self.base_title)
        self.setMinimumSize(1000, 700)
        self.resize(1200, 800)

        self.steps = []
        self.current_step_index = 0
        self.is_running = False
        self.is_paused = False
        self.is_adding_coordinate = False
        self.is_selecting_window = False
        self.is_adding_image = False
        
        self.base_dir = self.get_base_path()
        self.screenshot_dir = os.path.join(self.base_dir, "screenshots")
        os.makedirs(self.screenshot_dir, exist_ok=True)

        self.mouse_listener = None
        self.keyboard_listener = None
        self.global_hotkey_listener = None
        self.target_hwnd = None

        self.mouse = MouseController()
        self.keyboard = KeyboardController()
        self.hotkey = "F12"

        self.init_ui()
        self.setup_global_hotkey()

        self.execution_thread = ExecutionThread(self)
        self.execution_thread.finished.connect(self.on_execution_finished)
        self.execution_thread.error.connect(self.on_execution_error)
        self.execution_thread.step_completed.connect(self.on_step_completed)

        self.coordinate_captured.connect(self.on_coordinate_captured)
        self.stop_coordinate_mode.connect(self.stop_add_coordinate_mode)
        self.stop_select_window_mode_signal.connect(self.stop_select_window_mode)
        self.screenshot_closed.connect(self.on_screenshot_closed)

    def init_ui(self):
        font = QFont("Microsoft YaHei", 10)
        self.setFont(font)
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        main_splitter = QSplitter(Qt.Horizontal)

        left_widget = QWidget()
        left_layout = QVBoxLayout()
        left_layout.setSpacing(10)
        left_widget.setMinimumWidth(320)

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
        control_layout.addWidget(self.start_btn)
        stop_pause_layout = QHBoxLayout()
        stop_pause_layout.addWidget(self.pause_btn)
        stop_pause_layout.addWidget(self.stop_btn)
        control_layout.addLayout(stop_pause_layout)
        control_group.setLayout(control_layout)
        left_layout.addWidget(control_group)

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

        offset_group = QGroupBox("偏移设置")
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

        random_delay_group = QGroupBox("启动随机延迟")
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
        self.hotkey_preset.addItems(["F12", "F11", "F10", "F9", "F8", "Ctrl+A", "Ctrl+S", "Ctrl+Shift+F", "Alt+F4", "Shift+F12", "Ctrl+F5"])
        self.hotkey_preset.setCurrentText("F12")
        self.hotkey_preset.currentTextChanged.connect(self.on_hotkey_changed)
        hotkey_layout.addWidget(QLabel("启动/停止热键:"))
        hotkey_layout.addWidget(self.hotkey_preset)
        hotkey_group.setLayout(hotkey_layout)
        left_layout.addWidget(hotkey_group)
        left_layout.addStretch()
        left_widget.setLayout(left_layout)

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
