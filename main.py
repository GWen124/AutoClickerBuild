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

# ==========================================
# 设置 DPI 感知：解决 Windows 下高分屏/缩放导致的界面模糊和坐标偏移问题
# ==========================================
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except:
        pass

# ==========================================
# 核心类：步骤数据结构 (存储每一步的关键开关与配置)
# ==========================================
class Step:
    def __init__(self, step_type, image_path=None, x=None, y=None,
                 click_type='left', wait_time=1000, similarity=0.8,
                 jump_to=None, random_delay_enabled=False, random_delay_min=100, random_delay_max=1000,
                 accept_offset=True, accept_random_delay=True):
        self.step_type = step_type             # 步骤类型：'image'（图像识别） 或 'coordinate'（坐标点击）
        self.image_path = image_path           # 图像识别所需的模板图片路径
        self.x = x                             # 坐标点击的 X 轴位置
        self.y = y                             # 坐标点击的 Y 轴位置
        self.click_type = click_type           # 点击方式：'left', 'right', 'double', 'jump'
        self.wait_time = wait_time             # 执行完此步骤后的基础等待时间（毫秒）
        self.similarity = similarity           # 图像识别的匹配容错率（0.1~1.0）
        self.jump_to = jump_to                 # 条件跳转的目标步骤索引（仅图像识别可用）
        self.random_delay_enabled = random_delay_enabled # 全局开关：是否启用随机延迟
        self.random_delay_min = random_delay_min         # 随机延迟下限（毫秒）
        self.random_delay_max = random_delay_max         # 随机延迟上限（毫秒）
        self.accept_offset = accept_offset               # 步骤级开关：该步骤是否接受坐标防封偏移
        self.accept_random_delay = accept_random_delay   # 步骤级开关：该步骤是否接受随机延迟

class AutoClickerApp(QMainWindow):
    # 定义跨线程通信信号，防止 UI 线程阻塞
    coordinate_captured = pyqtSignal(int, int)
    stop_coordinate_mode = pyqtSignal()
    stop_select_window_mode_signal = pyqtSignal()
    screenshot_closed = pyqtSignal()

    def get_base_path(self):
        # 获取应用程序的运行目录（核心兼容逻辑：兼容源码运行和打包成exe后的运行环境）
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        else:
            return os.path.dirname(os.path.abspath(__file__))

    def __init__(self):
        super().__init__()
        self.base_title = "自动点击工具 V1.4 - 循环进度显示版"
        self.setWindowTitle(self.base_title)
        
        # 界面防挤压处理：设置最小尺寸，防止组件重叠
        self.setMinimumSize(1000, 700)
        self.resize(1200, 800)

        # 核心状态变量初始化
        self.steps = []
        self.current_step_index = 0
        self.is_running = False
        self.is_paused = False
        self.is_adding_coordinate = False
        self.is_selecting_window = False
        self.is_adding_image = False
        
        # 目录初始化：确保截图文件夹跟随主程序生成
        self.base_dir = self.get_base_path()
        self.screenshot_dir = os.path.join(self.base_dir, "screenshots")
        os.makedirs(self.screenshot_dir, exist_ok=True)

        self.mouse_listener = None
        self.keyboard_listener = None
        self.global_hotkey_listener = None
        self.target_hwnd = None # 目标窗口句柄，后台执行的核心凭据

        self.mouse = MouseController()
        self.keyboard = KeyboardController()
        self.hotkey = "F12"

        self.init_ui()
        self.setup_global_hotkey()

        # 初始化后台执行线程
        self.execution_thread = ExecutionThread(self)
        self.execution_thread.finished.connect(self.on_execution_finished)
        self.execution_thread.error.connect(self.on_execution_error)
        self.execution_thread.step_completed.connect(self.on_step_completed)
        
        # 【新增】接收执行线程发来的循环更新信号
        self.execution_thread.loop_updated.connect(self.on_loop_updated)

        self.coordinate_captured.connect(self.on_coordinate_captured)
        self.stop_coordinate_mode.connect(self.stop_add_coordinate_mode)
        self.stop_select_window_mode_signal.connect(self.stop_select_window_mode)
        self.screenshot_closed.connect(self.on_screenshot_closed)
        
        # 【新增】初始化底部状态栏
        self.statusBar().showMessage("✨ 准备就绪，请添加步骤或加载配置")

    # ---------------- UI 渲染区域 ----------------
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
        left_widget.setMinimumWidth(320) # 保证左侧面板文字不被截断

        # 控制台组
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

        # 窗口绑定组 (后台运行的基础)
        window_group = QGroupBox("目标窗口设置 (后台执行关键)")
        window_layout = QVBoxLayout()
        self.window_title_edit =
