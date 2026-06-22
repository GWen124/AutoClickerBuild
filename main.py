import sys
import cv2
import numpy as np
import json
import os
import time
import random
import ctypes
import datetime
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
# 设置 DPI 感知：防止界面挤压模糊
# ==========================================
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
        self.base_title = "自动点击工具 V1.1 - 定时多开与动态修改版"
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
        self.execution_thread.info_msg.connect(self.on_info_msg) 
        self.execution_thread.step_completed.connect(self.on_step_completed)
        self.execution_thread.waiting_update.connect(self.on_waiting_update) 

        self.coordinate_captured.connect(self.on_coordinate_captured)
        self.stop_coordinate_mode.connect(self.stop_add_coordinate_mode)
        self.stop_select_window_mode_signal.connect(self.stop_select_window_mode)
        self.screenshot_closed.connect(self.on_screenshot_closed)
        
        self.statusBar().showMessage("✨ 准备就绪，支持多开并允许在暂停时修改执行策略")

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
        left_widget.setMinimumWidth(340) # 稍微加宽一点保证网格不拥挤

        # 1. 流程控制组
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

        # 2. 目标窗口组
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

        # 3. 文件操作组
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

        # =================【重点重构：网格排版的循环与定时设置】=================
        loop_group = QGroupBox("循环与定时策略 (暂停时可修改)")
        lt_layout = QGridLayout()
        lt_layout.setSpacing(8)
        
        # Row 0: 循环模式
        self.loop_type_group = QButtonGroup()
        self.radio_infinite = QRadioButton("无限循环")
        self.radio_count = QRadioButton("次数循环")
        self.radio_infinite.setChecked(True)
        self.loop_type_group.addButton(self.radio_infinite, 0)
        self.loop_type_group.addButton(self.radio_count, 1)
        lt_layout.addWidget(self.radio_infinite, 0, 0)
        lt_layout.addWidget(self.radio_count, 0, 1)
        
        # Row 1: 循环次数
        lt_layout.addWidget(QLabel("循环设定次数:"), 1, 0)
        self.loop_spin = QSpinBox()
        self.loop_spin.setRange(1, 99999)
        self.loop_spin.setValue(1000)
        lt_layout.addWidget(self.loop_spin, 1, 1)
        
        # Row 2: 定时启动
        self.timer_start_checkbox = QCheckBox("定时启动(每天):")
        self.timer_start_edit = QTimeEdit()
        self.timer_start_edit.setDisplayFormat("HH:mm:ss")
        self.timer_start_edit.setTime(QTime.currentTime())
        self.timer_start_edit.setEnabled(False)
        self.timer_start_checkbox.stateChanged.connect(lambda state: self.timer_start_edit.setEnabled(state == Qt.Checked))
        lt_layout.addWidget(self.timer_start_checkbox, 2, 0)
        lt_layout.addWidget(self.timer_start_edit, 2, 1)

        # Row 3: 定时停止
        self.timer_stop_checkbox = QCheckBox("定时停止(运行后):")
        self.timer_stop_spin = QSpinBox()
        self.timer_stop_spin.setRange(1, 99999)
        self.timer_stop_spin.setValue(60)
        self.timer_stop_spin.setSuffix(" 分钟")
        self.timer_stop_spin.setEnabled(False)
        self.timer_stop_checkbox.stateChanged.connect(lambda state: self.timer_stop_spin.setEnabled(state == Qt.Checked))
        lt_layout.addWidget(self.timer_stop_checkbox, 3, 0)
        lt_layout.addWidget(self.timer_stop_spin, 3, 1)
        
        loop_group.setLayout(lt_layout)
        left_layout.addWidget(loop_group)
        # =========================================================

        # 5. 偏移设置组
        offset_group = QGroupBox("坐标偏移防封设置")
        offset_layout = QGridLayout()
        self.offset_checkbox = QCheckBox("启用随机偏移")
        self.offset_checkbox.setChecked(False)
        self.offset_checkbox.stateChanged.connect(self.toggle_offset)
        offset_layout.addWidget(self.offset_checkbox, 0, 0, 1, 2)
        
        offset_layout.addWidget(QLabel("X轴(像):"), 1, 0)
        self.offset_x_spin = QSpinBox()
        self.offset_x_spin.setRange(0, 50)
        self.offset_x_spin.setValue(5)
        offset_layout.addWidget(self.offset_x_spin, 1, 1)
        
        offset_layout.addWidget(QLabel("Y轴(像):"), 2, 0)
        self.offset_y_spin = QSpinBox()
        self.offset_y_spin.setRange(0, 50)
        self.offset_y_spin.setValue(5)
        offset_layout.addWidget(self.offset_y_spin, 2, 1)
        
        offset_group.setLayout(offset_layout)
        left_layout.addWidget(offset_group)

        # 6. 全局热键
        hotkey_group = QGroupBox("快捷键")
        hotkey_layout = QVBoxLayout()
        self.hotkey_preset = QComboBox()
        self.hotkey_preset.addItems([
            "F12", "F11", "F10", "F9", "F8",
            "Ctrl+A", "Ctrl+S", "Ctrl+Shift+F",
            "Alt+F4", "Shift+F12", "Ctrl+F5"
        ])
        self.hotkey_preset.setCurrentText("F12")
        self.hotkey_preset.currentTextChanged.connect(self.on_hotkey_changed)
        hotkey_layout.addWidget(self.hotkey_preset)
        hotkey_group.setLayout(hotkey_layout)
        left_layout.addWidget(hotkey_group)

        left_layout.addStretch()
        left_widget.setLayout(left_layout)

        # ---------------- 右侧主区域 ----------------
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

        steps_group = QGroupBox("执行步骤列表")
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
            QTableWidget { gridline-color: #ddd; font-size: 11px; border: 1px solid #ccc; border-radius: 3px; }
            QTableWidget::item { padding: 6px 4px; min-height: 20px; text-align: center; }
            QTableWidget::item:selected { background-color: #e3f2fd; }
            QHeaderView::section { background-color: #f0f0f0; padding: 6px; border: 1px solid #ddd; font-weight: bold; text-align: center; }
        """)
        self.steps_table.verticalHeader().setDefaultSectionSize(35)
        self.steps_table.verticalHeader().setVisible(False)
        self.steps_table.cellClicked.connect(self.on_step_selected_from_table)
        steps_layout.addWidget(self.steps_table)
        steps_group.setLayout(steps_layout)
        right_layout.addWidget(steps_group)
        right_widget.setLayout(right_layout)

        main_splitter.addWidget(left_widget)
        main_splitter.addWidget(right_widget)
        main_splitter.setSizes([340, 860])

        main_layout.addWidget(main_splitter)
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)

    def clear_target_window(self):
        self.target_hwnd = None
        self.window_title_edit.clear()
        QMessageBox.information(self, "提示", "已清除目标窗口")

    def set_controls_enabled(self, enabled):
        controls = [
            self.radio_infinite, self.radio_count, self.loop_spin,
            self.timer_start_checkbox, self.timer_start_edit,
            self.timer_stop_checkbox, self.timer_stop_spin,
            self.offset_checkbox, self.offset_x_spin, self.offset_y_spin,
            self.hotkey_preset, self.steps_table, self.add_image_btn,
            self.add_coordinate_btn, self.delete_btn, self.move_up_btn,
            self.move_down_btn, self.save_btn, self.load_btn, self.select_window_btn
        ]
        for control in controls:
            control.setEnabled(enabled)

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
                    if all(self.keyboard.ctrl_pressed if m == Key.ctrl else self.keyboard.alt_pressed if m == Key.alt else self.keyboard.shift_pressed for m in target_keys[:-1]):
                        QTimer.singleShot(0, self.toggle_execution)
            else:
                if key == target_keys[-1]:
                    if all(self.keyboard.ctrl_pressed if m == Key.ctrl else self.keyboard.alt_pressed if m == Key.alt else self.keyboard.shift_pressed for m in target_keys[:-1]):
                        QTimer.singleShot(0, self.toggle_execution)
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
            self.target_hwnd = hwnd
            window_title = win32gui.GetWindowText(hwnd)
            self.window_title_edit.setText(f"{window_title} (HWND: {hwnd})")
            self.stop_select_window_mode_signal.emit()
            return False
        return True

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
            random_delay_enabled=False,
            random_delay_min=100,
            random_delay_max=1000
        )
        self.steps.append(step)
        self.update_steps_table()
        self.stop_add_coordinate_mode()

    def toggle_offset(self, state):
        enabled = state == Qt.Checked
        self.offset_x_spin.setEnabled(enabled)
        self.offset_y_spin.setEnabled(enabled)

    def toggle_random_delay(self, state):
        # 兼容旧代码遗留逻辑，但此处界面已不再控制全步骤的随机
        pass

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

        self.update_all_settings()

        timer_start_enabled = self.timer_start_checkbox.isChecked()
        timer_start_time = self.timer_start_edit.time().toString("HH:mm:ss")
        timer_stop_enabled = self.timer_stop_checkbox.isChecked()
        timer_stop_minutes = self.timer_stop_spin.value()

        if self.is_paused:
            # =================【暂停后继续的逻辑处理】=================
            self.is_paused = False
            self.is_running = True
            
            # 在恢复执行时，强行把面板上最新的【循环、定时停止】设置传递给后台！
            self.execution_thread.loop_count = self.get_loop_count()
            self.execution_thread.timer_stop_enabled = self.timer_stop_checkbox.isChecked()
            self.execution_thread.timer_stop_minutes = self.timer_stop_spin.value()
            
            self.execution_thread.resume()
            
            # 将控件重新锁死
            self.radio_infinite.setEnabled(False)
            self.radio_count.setEnabled(False)
            self.loop_spin.setEnabled(False)
            self.timer_stop_checkbox.setEnabled(False)
            self.timer_stop_spin.setEnabled(False)
            
            self.start_btn.setEnabled(False)
            self.pause_btn.setText("⏸ 暂停执行")
            self.statusBar().showMessage("▶ 恢复执行...")
            # =========================================================
        else:
            self.current_step_index = 0
            self.is_running = True
            self.is_paused = False
            loop_count = self.get_loop_count()
            self.execution_thread.set_params(loop_count, self.current_step_index, timer_start_enabled, timer_start_time, timer_stop_enabled, timer_stop_minutes)
            self.execution_thread.start()
            
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
        self.statusBar().showMessage("⏹ 任务已被手动停止")

    def pause_execution(self):
        if self.is_running and not self.is_paused:
            # =================【点击暂停时的处理】=================
            self.is_paused = True
            self.is_running = False
            self.execution_thread.pause()
            
            self.start_btn.setEnabled(True)
            self.pause_btn.setText("▶ 继续执行")
            self.statusBar().showMessage("⏸ 任务已暂停 (您可以修改上方的【循环/停止】策略)")
            
            # 解锁循环与定时停止组件，允许用户中途改变心意！
            self.radio_infinite.setEnabled(True)
            self.radio_count.setEnabled(True)
            self.loop_spin.setEnabled(True)
            self.timer_stop_checkbox.setEnabled(True)
            if self.timer_stop_checkbox.isChecked():
                self.timer_stop_spin.setEnabled(True)
            # =========================================================
            
        elif self.is_paused:
            # 兼容通过快捷键恢复执行的逻辑
            self.start_execution()

    def update_all_settings(self):
        for step in self.steps:
            # 此处省略随机延迟设置批量更新，交由各步骤自有配置决定
            pass

    def on_waiting_update(self, countdown_str):
        self.statusBar().showMessage(f"⏳ 等待定时启动... 倒计时: {countdown_str}")

    def on_execution_finished(self):
        self.is_running = False
        self.is_paused = False
        self.current_step_index = 0
        self.set_controls_enabled(True)
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText("⏸ 暂停执行")
        self.statusBar().showMessage("✅ 任务已正常结束！")

    def on_info_msg(self, msg):
        self.statusBar().showMessage(f"✅ {msg}")
        QMessageBox.information(self, "执行提醒", msg)

    def on_execution_error(self, error_msg):
        self.is_running = False
        self.is_paused = False
        self.current_step_index = 0
        self.set_controls_enabled(True)
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText("⏸ 暂停执行")
        self.statusBar().showMessage(f"❌ 发生错误: {error_msg}")
        QMessageBox.critical(self, "错误", f"执行出错: {error_msg}")

    def on_step_completed(self, step_index):
        self.current_step_index = step_index
        self.steps_table.selectRow(step_index)

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
            self.steps_table.blockSignals(True)
            step_item = QTableWidgetItem(f"{i + 1}")
            step_item.setTextAlignment(Qt.AlignCenter)
            self.steps_table.setItem(i, 0, step_item)

            type_item = QTableWidgetItem("图像识别" if step.step_type == 'image' else "坐标点击")
            type_item.setTextAlignment(Qt.AlignCenter)
            self.steps_table.setItem(i, 1, type_item)

            click_combo = QComboBox()
            click_combo.blockSignals(True)
            click_combo.addItems(["左键单击", "右键单击", "双击", "跳转"])
            if step.click_type == 'left': click_combo.setCurrentIndex(0)
            elif step.click_type == 'right': click_combo.setCurrentIndex(1)
            elif step.click_type == 'double': click_combo.setCurrentIndex(2)
            elif step.click_type == 'jump': click_combo.setCurrentIndex(3)
            click_combo.currentTextChanged.connect(lambda text, row=i: self.update_step_click_type(row, text))
            click_combo.blockSignals(False)
            self.steps_table.setCellWidget(i, 2, click_combo)

            wait_spin = QSpinBox()
            wait_spin.blockSignals(True)
            wait_spin.setRange(0, 3600000)
            wait_spin.setValue(step.wait_time)
            wait_spin.valueChanged.connect(lambda value, row=i: self.update_step_wait_time(row, value))
            wait_spin.blockSignals(False)
            self.steps_table.setCellWidget(i, 3, wait_spin)

            if step.step_type == 'image':
                similarity_spin = QDoubleSpinBox()
                similarity_spin.blockSignals(True)
                similarity_spin.setRange(0.1, 1.0)
                similarity_spin.setSingleStep(0.05)
                similarity_spin.setValue(step.similarity)
                similarity_spin.setDecimals(2)
                similarity_spin.valueChanged.connect(lambda value, row=i: self.update_step_similarity(row, value))
                similarity_spin.blockSignals(False)
                self.steps_table.setCellWidget(i, 4, similarity_spin)
            else:
                similarity_item = QTableWidgetItem("-")
                similarity_item.setTextAlignment(Qt.AlignCenter)
                self.steps_table.setItem(i, 4, similarity_item)

            offset_checkbox = QCheckBox()
            offset_checkbox.blockSignals(True)
            offset_checkbox.setStyleSheet("QCheckBox { margin-left: auto; margin-right: auto; }")
            offset_checkbox.setChecked(step.accept_offset)
            offset_checkbox.stateChanged.connect(lambda state, row=i: self.update_step_accept_offset(row, state))
            offset_checkbox.blockSignals(False)
            self.steps_table.setCellWidget(i, 5, offset_checkbox)

            random_delay_checkbox = QCheckBox()
            random_delay_checkbox.blockSignals(True)
            random_delay_checkbox.setStyleSheet("QCheckBox { margin-left: auto; margin-right: auto; }")
            random_delay_checkbox.setChecked(step.accept_random_delay)
            random_delay_checkbox.stateChanged.connect(lambda state, row=i: self.update_step_accept_random_delay(row, state))
            random_delay_checkbox.blockSignals(False)
            self.steps_table.setCellWidget(i, 6, random_delay_checkbox)

            jump_combo = QComboBox()
            jump_combo.blockSignals(True)
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
                if step.step_type == 'coordinate' and step.click_type == 'jump':
                    step.click_type = 'left'
                    step.jump_to = None
            jump_combo.blockSignals(False)
            self.steps_table.setCellWidget(i, 7, jump_combo)
            self.steps_table.blockSignals(False)

    def update_step_jump_to(self, row, index):
        if row < len(self.steps):
            combo = self.steps_table.cellWidget(row, 7)
            if combo:
                jump_to = combo.itemData(index)
                self.steps[row].jump_to = jump_to if jump_to != -1 else None

    def update_step_accept_offset(self, row, state):
        if row < len(self.steps):
            self.steps[row].accept_offset = (state == Qt.Checked)

    def update_step_accept_random_delay(self, row, state):
        if row < len(self.steps):
            self.steps[row].accept_random_delay = (state == Qt.Checked)

    def update_step_click_type(self, row, text):
        if row < len(self.steps):
            if text == "左键单击": self.steps[row].click_type = 'left'
            elif text == "右键单击": self.steps[row].click_type = 'right'
            elif text == "双击": self.steps[row].click_type = 'double'
            elif text == "跳转": self.steps[row].click_type = 'jump'

            jump_combo = self.steps_table.cellWidget(row, 7)
            if jump_combo:
                if text == "跳转" and self.steps[row].step_type == 'image':
                    jump_combo.setEnabled(True)
                else:
                    jump_combo.setEnabled(False)
                    self.steps[row].jump_to = None
                    jump_combo.setCurrentIndex(0)

    def update_step_wait_time(self, row, value):
        if row < len(self.steps):
            self.steps[row].wait_time = value

    def update_step_similarity(self, row, value):
        if row < len(self.steps):
            self.steps[row].similarity = value

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
        if not file_path:
            return
        config = {
            "steps": [],
            "hotkey": self.hotkey,
            "loop_type": self.loop_type_group.checkedId(),
            "loop_count": self.loop_spin.value(),
            "offset_enabled": self.offset_checkbox.isChecked(),
            "offset_x": self.offset_x_spin.value(),
            "offset_y": self.offset_y_spin.value(),
            "timer_start_enabled": self.timer_start_checkbox.isChecked(),
            "timer_start_time": self.timer_start_edit.time().toString("HH:mm:ss"),
            "timer_stop_enabled": self.timer_stop_checkbox.isChecked(),
            "timer_stop_minutes": self.timer_stop_spin.value()
        }
        config_dir = os.path.dirname(file_path)
        for step in self.steps:
            step_data = {
                "step_type": step.step_type,
                "image_path": step.image_path,
                "x": step.x,
                "y": step.y,
                "click_type": step.click_type,
                "wait_time": step.wait_time,
                "similarity": step.similarity,
                "jump_to": step.jump_to,
                "accept_offset": step.accept_offset,
                "accept_random_delay": step.accept_random_delay
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
            
        self.setWindowTitle(f"{self.base_title} - [{os.path.basename(file_path)}]")
        QMessageBox.information(self, "成功", "配置保存成功！")

    def load_config(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "加载配置", "", "JSON文件 (*.json)")
        if not file_path:
            return
        with open(file_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

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
                if os.path.isabs(path):
                    final_path = path
                else:
                    config_path = os.path.join(config_dir, path)
                    base_path = os.path.join(self.base_dir, path)
                    base_screenshots_path = os.path.join(self.base_dir, "screenshots", os.path.basename(path))
                    config_screenshots_path = os.path.join(config_dir, "screenshots", os.path.basename(path))
                    if os.path.exists(config_path):
                        final_path = config_path
                    elif os.path.exists(base_path):
                        final_path = base_path
                    elif os.path.exists(base_screenshots_path):
                        final_path = base_screenshots_path
                    elif os.path.exists(config_screenshots_path):
                        final_path = config_screenshots_path
                    else:
                        final_path = config_path
                step_data["image_path"] = final_path

            # 为了兼容旧配置，剥离被去除的旧属性
            if "random_delay_enabled" in step_data: del step_data["random_delay_enabled"]
            if "random_delay_min" in step_data: del step_data["random_delay_min"]
            if "random_delay_max" in step_data: del step_data["random_delay_max"]

            step = Step(**step_data)
            self.steps.append(step)

        self.hotkey = config.get("hotkey", "F12")
        self.hotkey_preset.setCurrentText(self.hotkey)
        self.setup_global_hotkey()

        loop_type = config.get("loop_type", 0)
        if loop_type == 0:
            self.radio_infinite.setChecked(True)
        else:
            self.radio_count.setChecked(True)

        self.loop_spin.setValue(config.get("loop_count", 1000))

        offset_enabled = config.get("offset_enabled", False)
        self.offset_checkbox.setChecked(offset_enabled)
        self.offset_x_spin.setValue(config.get("offset_x", 5))
        self.offset_y_spin.setValue(config.get("offset_y", 5))
        self.toggle_offset(Qt.Checked if offset_enabled else Qt.Unchecked)

        # 还原定时配置
        self.timer_start_checkbox.setChecked(config.get("timer_start_enabled", False))
        if "timer_start_time" in config:
            self.timer_start_edit.setTime(QTime.fromString(config["timer_start_time"], "HH:mm:ss"))
        self.timer_stop_checkbox.setChecked(config.get("timer_stop_enabled", False))
        self.timer_stop_spin.setValue(config.get("timer_stop_minutes", 60))

        self.update_steps_table()
        self.setWindowTitle(f"{self.base_title} - [{os.path.basename(file_path)}]")
        QMessageBox.information(self, "成功", "配置加载成功！")

    def closeEvent(self, event):
        self.stop_execution()
        if self.global_hotkey_listener:
            self.global_hotkey_listener.stop()
        if self.mouse_listener:
            self.mouse_listener.stop()
        if self.keyboard_listener:
            self.keyboard_listener.stop()
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
        if event.key() == Qt.Key_Escape:
            self.cancel_screenshot()

    def closeEvent(self, event):
        self.closed.emit()
        event.accept()

class ExecutionThread(QThread):
    finished = pyqtSignal()
    error = pyqtSignal(str)
    info_msg = pyqtSignal(str)
    step_completed = pyqtSignal(int)
    waiting_update = pyqtSignal(str)

    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self.loop_count = 1
        self.current_step_index = 0
        self.is_stopped = False
        self.is_paused = False
        self.current_loop = 0
        
        self.timer_start_enabled = False
        self.timer_start_time_str = ""
        self.timer_stop_enabled = False
        self.timer_stop_minutes = 0
        self.actual_start_time = 0
        self.pause_start_time = 0

    def set_params(self, loop_count, start_index=0, timer_start_enabled=False, timer_start_time_str="", timer_stop_enabled=False, timer_stop_minutes=0):
        self.loop_count = loop_count
        self.current_step_index = start_index
        self.current_loop = 0
        self.is_stopped = False
        self.is_paused = False
        
        self.timer_start_enabled = timer_start_enabled
        self.timer_start_time_str = timer_start_time_str
        self.timer_stop_enabled = timer_stop_enabled
        self.timer_stop_minutes = timer_stop_minutes

    def stop(self):
        self.is_stopped = True

    def pause(self):
        self.is_paused = True
        self.pause_start_time = time.time()

    def resume(self):
        self.is_paused = False
        if self.actual_start_time > 0:
            self.actual_start_time += (time.time() - self.pause_start_time)

    def run(self):
        try:
            if not self.parent.steps:
                self.finished.emit()
                return

            if self.timer_start_enabled:
                now = datetime.datetime.now()
                target_time = QTime.fromString(self.timer_start_time_str, "HH:mm:ss")
                target_dt = now.replace(hour=target_time.hour(), minute=target_time.minute(), second=target_time.second(), microsecond=0)
                
                if target_dt <= now:
                    target_dt += datetime.timedelta(days=1)
                    
                while not self.is_stopped:
                    now = datetime.datetime.now()
                    time_left = (target_dt - now).total_seconds()
                    
                    if time_left <= 0:
                        break 
                        
                    hours, remainder = divmod(int(time_left), 3600)
                    minutes, seconds = divmod(remainder, 60)
                    countdown_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                    self.waiting_update.emit(countdown_str)
                    
                    self._sleep_interruptible(1.0)
                    
                if self.is_stopped:
                    self.finished.emit()
                    return

            self.actual_start_time = time.time()

            # 此处判断逻辑会自动兼容由于用户中途在暂停时修改产生的 self.loop_count 变动
            while (self.current_loop < self.loop_count or self.loop_count == 999999) and not self.is_stopped:
                
                if self.timer_stop_enabled:
                    elapsed_minutes = (time.time() - self.actual_start_time) / 60.0
                    if elapsed_minutes >= self.timer_stop_minutes:
                        self.info_msg.emit(f"已达到设定的运行时间 ({self.timer_stop_minutes} 分钟)，任务自动结束！")
                        self.stop()
                        break

                self.current_loop += 1

                while self.current_step_index < len(self.parent.steps) and not self.is_stopped:
                    while self.is_paused and not self.is_stopped:
                        time.sleep(0.1)

                    if self.is_stopped:
                        break

                    if self.current_step_index >= len(self.parent.steps):
                        break

                    step = self.parent.steps[self.current_step_index]
                    target_pos = None

                    if step.step_type == 'image':
                        target_pos = self.find_image(step.image_path, step.similarity)
                        if target_pos and self.parent.target_hwnd:
                            left, top, _, _ = win32gui.GetWindowRect(self.parent.target_hwnd)
                            target_pos = (target_pos[0] + left, target_pos[1] + top)
                    else:
                        target_pos = (step.x, step.y)
                        if self.parent.target_hwnd:
                            left, top, _, _ = win32gui.GetWindowRect(self.parent.target_hwnd)
                            target_pos = (target_pos[0] + left, target_pos[1] + top)

                    # 基础步骤耗时
                    total_wait = step.wait_time

                    if step.step_type == 'image' and step.click_type == 'jump':
                        if target_pos is not None and step.jump_to is not None:
                            self.current_step_index = step.jump_to
                            self.step_completed.emit(self.current_step_index)
                            self._sleep_interruptible(total_wait / 1000.0)
                            continue

                    if target_pos is not None and step.click_type != 'jump':
                        self.click_target(target_pos, step)

                    self._sleep_interruptible(total_wait / 1000.0)

                    if step.click_type != 'jump' or (step.click_type == 'jump' and target_pos is None):
                        self.current_step_index += 1

                    self.step_completed.emit(self.current_step_index)

                if not self.is_stopped:
                    self.current_step_index = 0

            self.finished.emit()

        except Exception as e:
            self.error.emit(str(e))

    def _sleep_interruptible(self, seconds):
        iterations = int(seconds * 10)
        for _ in range(iterations):
            if self.is_stopped: break
            time.sleep(0.1)

    def find_image(self, image_path, similarity=0.8):
        if not os.path.exists(image_path):
            return None
        try:
            img_array = np.fromfile(image_path, dtype=np.uint8)
            template = cv2.imdecode(img_array, cv2.IMREAD_GRAYSCALE)
        except:
            return None
            
        if template is None:
            return None

        if self.parent.target_hwnd:
            left, top, right, bottom = win32gui.GetWindowRect(self.parent.target_hwnd)
            if right - left <= 0 or bottom - top <= 0:
                return None
            bbox = (left, top, right, bottom)
            # 使用 PIL 防止子线程调用 Qt 原生抓屏发生锁死崩溃
            screen_image = ImageGrab.grab(bbox)
        else:
            screen_image = ImageGrab.grab()

        screenshot = cv2.cvtColor(np.array(screen_image), cv2.COLOR_RGB2GRAY)

        if screenshot.shape[0] < template.shape[0] or screenshot.shape[1] < template.shape[1]:
            return None

        result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val >= similarity:
            h, w = template.shape[:2]
            return (max_loc[0] + w // 2, max_loc[1] + h // 2)

        return None

    def click_target(self, target_pos, step):
        x, y = target_pos

        if step.accept_offset and self.parent.offset_checkbox.isChecked():
            x += random.randint(-self.parent.offset_x_spin.value(), self.parent.offset_x_spin.value())
            y += random.randint(-self.parent.offset_y_spin.value(), self.parent.offset_y_spin.value())

        if self.parent.target_hwnd:
            left, top, _, _ = win32gui.GetWindowRect(self.parent.target_hwnd)
            rel_x, rel_y = x - left, y - top

            if step.click_type == 'left':
                down_msg, up_msg = win32con.WM_LBUTTONDOWN, win32con.WM_LBUTTONUP
            elif step.click_type == 'right':
                down_msg, up_msg = win32con.WM_RBUTTONDOWN, win32con.WM_RBUTTONUP
            elif step.click_type == 'double':
                self.click_target_backend(self.parent.target_hwnd, rel_x, rel_y, win32con.WM_LBUTTONDOWN, win32con.WM_LBUTTONUP)
                time.sleep(0.05)
                self.click_target_backend(self.parent.target_hwnd, rel_x, rel_y, win32con.WM_LBUTTONDOWN, win32con.WM_LBUTTONUP)
                return
            else:
                return
            self.click_target_backend(self.parent.target_hwnd, rel_x, rel_y, down_msg, up_msg)
        else:
            self.parent.mouse.position = (x, y)
            time.sleep(0.05)
            if step.click_type == 'left':
                self.parent.mouse.click(Button.left)
            elif step.click_type == 'right':
                self.parent.mouse.click(Button.right)
            elif step.click_type == 'double':
                self.parent.mouse.click(Button.left)
                time.sleep(0.05)
                self.parent.mouse.click(Button.left)

    def click_target_backend(self, hwnd, x, y, down_msg, up_msg):
        # V1.1 纯净回退版：最高效率的原生 SendMessage，绝对稳定
        lparam = win32api.MAKELONG(x, y)
        win32gui.SendMessage(hwnd, down_msg, win32con.MK_LBUTTON, lparam)
        time.sleep(0.01)
        win32gui.SendMessage(hwnd, up_msg, 0, lparam)

if __name__ == "__main__":
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        
    app = QApplication(sys.argv)
    window = AutoClickerApp()
    window.show()
    sys.exit(app.exec_())
