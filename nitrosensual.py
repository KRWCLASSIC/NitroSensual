from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout,
    QSlider, QPushButton, QGroupBox, QDialog, QComboBox, QSpinBox, QScrollArea, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QRect, QPoint, QSize
from PyQt5.QtGui import QPainter, QColor
from elevate import elevate
import pywintypes
import win32file
import winreg
import struct
import json
import sys
import os

LHM_DLL_PATH = None

elevate()

def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

APP_DIR = get_app_dir()
CONFIG_FILE = os.path.join(APP_DIR, "config.json")

DEFAULT_CONFIG = {
    "auto_fan_config": [
        {"min": 0, "max": 39, "speed": 0},
        {"min": 40, "max": 49, "speed": 20},
        {"min": 50, "max": 59, "speed": 35},
        {"min": 60, "max": 69, "speed": 50},
        {"min": 70, "max": 79, "speed": 70},
        {"min": 80, "max": 89, "speed": 85},
        {"min": 90, "max": 100, "speed": 100},
    ],
    "mode": "Custom",
    "custom_cpu": 50,
    "custom_gpu": 50,
}

def load_config():
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, "r") as f:
            data = json.load(f)
        for k, v in DEFAULT_CONFIG.items():
            if k not in data:
                data[k] = v
        return data
    except Exception:
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()

def save_config(config):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print("Failed to save config:", e)

# Helper to read current fan percentage from registry
def read_fan_percentage(fan_type: str) -> int:
    key_path = r"SOFTWARE\\OEM\\NitroSense\\FanControl"
    value_name = "CPUFanPercentage" if fan_type == "cpu" else "GPU1FanPercentage"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            value, _ = winreg.QueryValueEx(key, value_name)
            return int(value)
    except Exception:
        return -1  # Could not read

# Helper to write fan percentage to registry
def write_registry(fan_type: str, percent: int):
    key_path = r"SOFTWARE\\OEM\\NitroSense\\FanControl"
    value_name = "CPUFanPercentage" if fan_type == "cpu" else "GPU1FanPercentage"
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as key:
        winreg.SetValueEx(key, value_name, 0, winreg.REG_DWORD, percent)

# Helper to apply fan speed via named pipe
def apply_fan_speed(fan_type: str, percent: int):
    fan_group_type = 1 if fan_type == "cpu" else 4
    data = (percent << 8) | fan_group_type
    packet = struct.pack("<HBIQ", 16, 1, 8, data)
    try:
        handle = win32file.CreateFile(
            r"\\.\pipe\PredatorSense_service_namedpipe",
            win32file.GENERIC_READ | win32file.GENERIC_WRITE,
            0,
            None,
            win32file.OPEN_EXISTING,
            0,
            None
        )
        win32file.WriteFile(handle, packet)
        resp = win32file.ReadFile(handle, 9)[1]
        win32file.CloseHandle(handle)
        return True, resp.hex()
    except Exception as e:
        return False, str(e)

def unblock_file_if_needed(filepath):
    # Unblock file if it has a zone identifier (Windows only)
    if os.name == 'nt' and os.path.exists(filepath):
        ads = filepath + ":Zone.Identifier"
        if os.path.exists(ads):
            try:
                os.remove(ads)
            except Exception as e:
                print(f"Could not remove Zone.Identifier: {e}")

class ProgressDialog(QDialog):
    def __init__(self, message):
        super().__init__()
        self.setWindowTitle("Please Wait")
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        layout = QVBoxLayout()
        label = QLabel(message)
        layout.addWidget(label)
        self.setLayout(layout)
        self.setFixedSize(350, 80)

SYSTEM_HEALTH_INDEXES = {
    1: "CPU_Temperature",
    2: "CPU_Fan_Speed",
    6: "GPU_Fan_Speed",
    10: "GPU1_Temperature",
}

def send_command_by_named_pipe(pipe, cmd_code: int, args: list):
    message = bytearray()
    message += struct.pack("<H", cmd_code)
    message += struct.pack("<B", len(args))
    for arg in args:
        message += struct.pack("<I", len(arg))
        message += arg
    win32file.WriteFile(pipe, message)
    win32file.FlushFileBuffers(pipe)

def get_acer_gaming_system_info(index: int):
    input_code = 1 | (index << 8)
    arg = struct.pack("<I", input_code)
    try:
        pipe = win32file.CreateFile(
            r"\\.\pipe\PredatorSense_service_namedpipe",
            win32file.GENERIC_READ | win32file.GENERIC_WRITE,
            0, None, win32file.OPEN_EXISTING, 0, None
        )
        send_command_by_named_pipe(pipe, 13, [arg])
        _, raw = win32file.ReadFile(pipe, 13)
        result = struct.unpack_from("<Q", raw, 5)[0]
        win32file.CloseHandle(pipe)
        return result
    except (pywintypes.error, Exception):
        return None

def decode_result(result):
    if result is None:
        return None
    if result & 0xFF == 0:
        return (result >> 8) & 0xFFFF
    return None

def get_cpu_gpu_temp_and_rpm():
    cpu_temp_raw = get_acer_gaming_system_info(1)
    cpu_rpm_raw = get_acer_gaming_system_info(2)
    gpu_temp_raw = get_acer_gaming_system_info(10)
    gpu_rpm_raw = get_acer_gaming_system_info(6)
    cpu_temp = decode_result(cpu_temp_raw)
    cpu_rpm = decode_result(cpu_rpm_raw)
    gpu_temp = decode_result(gpu_temp_raw)
    gpu_rpm = decode_result(gpu_rpm_raw)
    return cpu_temp, cpu_rpm, gpu_temp, gpu_rpm

class FanControlWidget(QWidget):
    def __init__(self, fan_type: str, refresh_callback=None):
        super().__init__()
        self.fan_type = fan_type
        self.refresh_callback = refresh_callback
        self.init_ui()
        self.last_custom_value = self.slider.value()  # Track last custom value

    def init_ui(self):
        layout = QHBoxLayout()
        self.label = QLabel(f"{self.fan_type.upper()} Fan Speed:")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(read_fan_percentage(self.fan_type))
        self.value_label = QLabel(f"{self.slider.value()}%")
        self.slider.valueChanged.connect(self.on_slider_changed)
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.clicked.connect(lambda: self.apply_fan_speed())
        layout.addWidget(self.label)
        layout.addWidget(self.slider)
        layout.addWidget(self.value_label)
        layout.addWidget(self.apply_btn)
        self.setLayout(layout)

    def on_slider_changed(self, v):
        self.value_label.setText(f"{v}%")
        self.last_custom_value = v  # Update last custom value
        # Only update in-memory config, do NOT save to disk here!
        main = self.parentWidget()
        while main and not isinstance(main, MainWindow):
            main = main.parentWidget()
        if main and main.current_mode == "Custom":
            if self.fan_type == "cpu":
                main.config["custom_cpu"] = v
            elif self.fan_type == "gpu":
                main.config["custom_gpu"] = v

    def set_custom_mode(self, enabled: bool):
        self.slider.setEnabled(enabled)
        self.apply_btn.setEnabled(enabled)
        if enabled:
            # Restore last custom value to slider
            self.slider.setValue(self.last_custom_value)

    def set_fan_speed(self, percent: int):
        self.slider.setValue(percent)
        self.apply_fan_speed()
        self.last_custom_value = percent  # Update last custom value

    def apply_fan_speed(self):
        percent = self.slider.value()
        try:
            write_registry(self.fan_type, percent)
            apply_fan_speed(self.fan_type, percent)
            if self.refresh_callback:
                self.refresh_callback()
            # Save config to disk when Apply is clicked
            main = self.parentWidget()
            while main and not isinstance(main, MainWindow):
                main = main.parentWidget()
            if main and main.current_mode == "Custom":
                if self.fan_type == "cpu":
                    main.config["custom_cpu"] = percent
                elif self.fan_type == "gpu":
                    main.config["custom_gpu"] = percent
                save_config(main.config)
        except Exception:
            pass

    def apply_fan_speed_direct(self, percent):
        """Set fan speed without changing slider or last_custom_value."""
        try:
            write_registry(self.fan_type, percent)
            apply_fan_speed(self.fan_type, percent)
            if self.refresh_callback:
                self.refresh_callback()
        except Exception:
            pass

class RangeSlider(QSlider):
    rangeChanged = pyqtSignal(int, int)
    PADDING = 32  # pixels on each side

    def __init__(self, orientation=Qt.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self._low = self.minimum()
        self._high = self.maximum()
        self._drag = None
        self.setTickPosition(QSlider.NoTicks)
        self.setTickInterval(5)
        self.setMinimumHeight(32)
        self.setMaximumHeight(32)

    def low(self):
        return self._low

    def high(self):
        return self._high

    def setLow(self, value):
        value = min(max(self.minimum(), value), self._high)
        if value != self._low:
            self._low = value
            self.update()
            self.rangeChanged.emit(self._low, self._high)

    def setHigh(self, value):
        value = max(min(self.maximum(), value), self._low)
        if value != self._high:
            self._high = value
            self.update()
            self.rangeChanged.emit(self._low, self._high)

    def setRange(self, low, high):
        self.setLow(low)
        self.setHigh(high)

    def mousePressEvent(self, event):
        pos = event.pos().x() if self.orientation() == Qt.Horizontal else event.pos().y()
        low_pos = self._value_to_pos(self._low)
        high_pos = self._value_to_pos(self._high)
        if abs(pos - low_pos) < 12:
            self._drag = 'low'
        elif abs(pos - high_pos) < 12:
            self._drag = 'high'
        else:
            self._drag = None

    def mouseMoveEvent(self, event):
        if self._drag is None:
            return
        pos = event.pos().x() if self.orientation() == Qt.Horizontal else event.pos().y()
        value = self._pos_to_value(pos)
        if self._drag == 'low':
            self.setLow(value)
        elif self._drag == 'high':
            self.setHigh(value)

    def mouseReleaseEvent(self, event):
        self._drag = None

    def _value_to_pos(self, value):
        minv, maxv = self.minimum(), self.maximum()
        w = self.width() - 2 * self.PADDING
        return int(self.PADDING + (value - minv) / (maxv - minv) * (w - 1))

    def _pos_to_value(self, pos):
        minv, maxv = self.minimum(), self.maximum()
        w = self.width() - 2 * self.PADDING
        pos = max(self.PADDING, min(pos, self.width() - self.PADDING))
        value = int((pos - self.PADDING) / (w - 1) * (maxv - minv) + minv)
        return min(max(value, minv), maxv)

    def paintEvent(self, event):
        painter = QPainter(self)
        groove_rect = QRect(self.PADDING, self.height() // 2 - 3, self.width() - 2 * self.PADDING, 6)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(200, 200, 200))
        painter.drawRect(groove_rect)
        low_pos = self._value_to_pos(self._low)
        high_pos = self._value_to_pos(self._high)
        sel_rect = QRect(low_pos, self.height() // 2 - 5, high_pos - low_pos, 10)
        painter.setBrush(QColor(100, 180, 255, 180))
        painter.drawRect(sel_rect)
        for value, color in [(self._low, QColor(50, 120, 255)), (self._high, QColor(255, 80, 80))]:
            pos = self._value_to_pos(value)
            painter.setPen(Qt.black)
            painter.setBrush(color)
            painter.drawEllipse(QPoint(pos, self.height() // 2), 8, 8)

    def sizeHint(self):
        return QSize(200, 32)

class RangeSliderWidget(QWidget):
    def __init__(self, min_temp, max_temp, speed, min_limit, max_limit, parent=None):
        super().__init__(parent)
        self.min_limit = min_limit
        self.max_limit = max_limit

        layout = QHBoxLayout()
        self.min_slider = RangeSlider(Qt.Horizontal)
        self.min_slider.setRange(min_limit, max_limit)
        self.min_slider.setValue(min_temp)
        self.min_slider.rangeChanged.connect(self.on_range_changed)

        self.max_slider = RangeSlider(Qt.Horizontal)
        self.max_slider.setRange(min_limit, max_limit)
        self.max_slider.setValue(max_temp)
        self.max_slider.rangeChanged.connect(self.on_range_changed)

        self.speed_spin = QSpinBox()
        self.speed_spin.setRange(0, 100)
        self.speed_spin.setValue(speed)
        self.speed_spin.setSuffix("%")
        self.speed_spin.setFixedWidth(60)

        self.label = QLabel(self._label_text())
        self.label.setFixedWidth(110)

        layout.addWidget(self.label)
        layout.addWidget(QLabel("Min:"))
        layout.addWidget(self.min_slider)
        layout.addWidget(QLabel("Max:"))
        layout.addWidget(self.max_slider)
        layout.addWidget(QLabel("Speed:"))
        layout.addWidget(self.speed_spin)
        self.setLayout(layout)

    def on_range_changed(self):
        self.label.setText(self._label_text())

    def _label_text(self):
        return f"{self.min_slider.low()}–{self.max_slider.high()}°C"

    def get_values(self):
        return {
            "min": self.min_slider.low(),
            "max": self.max_slider.high(),
            "speed": self.speed_spin.value()
        }

class TempWorker(QThread):
    temps_updated = pyqtSignal(object, object, object, object)  # cpu_temp, cpu_rpm, gpu_temp, gpu_rpm

    def __init__(self, poll_interval=2):
        super().__init__()
        self.poll_interval = poll_interval
        self._running = True

    def run(self):
        import time
        while self._running:
            cpu_temp, cpu_rpm, gpu_temp, gpu_rpm = get_cpu_gpu_temp_and_rpm()
            self.temps_updated.emit(cpu_temp, cpu_rpm, gpu_temp, gpu_rpm)
            time.sleep(self.poll_interval)

    def stop(self):
        self._running = False

class AutoFanConfigDialog(QDialog):
    configChanged = pyqtSignal(list)

    def __init__(self, parent=None, config=None):
        super().__init__(parent)
        self.setWindowTitle("Auto Mode Fan Configuration")
        self.setModal(True)
        self.resize(700, 400)

        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        self.rows = []

        label = QLabel("Set fan speed for each temperature range:")
        self.layout.addWidget(label)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.rules_container = QWidget()
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setContentsMargins(0, 0, 0, 0)
        self.rules_layout.addStretch(1)
        self.rules_container.setLayout(self.rules_layout)
        self.scroll_area.setWidget(self.rules_container)
        self.layout.addWidget(self.scroll_area)

        if config is None:
            config = [
                {"min": 0, "max": 39, "speed": 0},
                {"min": 40, "max": 49, "speed": 20},
                {"min": 50, "max": 59, "speed": 35},
                {"min": 60, "max": 69, "speed": 50},
                {"min": 70, "max": 79, "speed": 70},
                {"min": 80, "max": 89, "speed": 85},
                {"min": 90, "max": 100, "speed": 100},
            ]
        for entry in config:
            self.add_row(entry["min"], entry["max"], entry["speed"])

        add_btn = QPushButton("Add Range")
        add_btn.setFocusPolicy(Qt.NoFocus)
        add_btn.clicked.connect(self.add_row)
        self.layout.addWidget(add_btn)

        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.setFocusPolicy(Qt.NoFocus)
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFocusPolicy(Qt.NoFocus)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        self.layout.addLayout(btn_layout)

    def add_row(self, minv=None, maxv=None, speed=50):
        row_widget = QWidget()
        row_widget.setMinimumHeight(48)
        row_widget.setMaximumHeight(48)
        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_widget.setLayout(row_layout)

        # --- Default to 99-100 for new rows if not specified ---
        if minv is None or maxv is None:
            # Find the highest max in current rows
            if self.rows:
                last_max = self.rows[-1]["slider"].high()
                minv = min(last_max + 1, 99)
                maxv = 100
            else:
                minv, maxv = 99, 100

        slider = RangeSlider(Qt.Horizontal)
        slider.setMinimum(0)
        slider.setMaximum(100)
        if maxv <= minv:
            maxv = minv + 1
        slider.setLow(minv)
        slider.setHigh(maxv)
        slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        min_label = QLabel()
        min_label.setFixedWidth(56)
        min_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        max_label = QLabel()
        max_label.setFixedWidth(56)
        max_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        def update_labels():
            idx = None
            for i, row in enumerate(self.rows):
                if row["slider"] is slider:
                    idx = i
                    break
            low = slider.low()
            high = slider.high()
            if idx == 0:
                min_label.setText("≤0°C")
            else:
                min_label.setText(f"{low}°C")
            if high == 100:
                max_label.setText("100+°C")
            else:
                max_label.setText(f"{high}°C")

        slider.rangeChanged.connect(lambda low, high: update_labels())

        speed_spin = QSpinBox()
        speed_spin.setRange(0, 100)
        speed_spin.setValue(speed)
        speed_spin.setSuffix("%")

        remove_btn = QPushButton("Remove")
        remove_btn.setFocusPolicy(Qt.NoFocus)  # Add this line
        remove_btn.setFixedWidth(60)

        def update_remove_buttons():
            enable = len(self.rows) > 1
            for row in self.rows:
                row["remove_btn"].setEnabled(enable)

        def remove():
            self.rules_layout.removeWidget(row_widget)
            row_widget.setParent(None)
            row_widget.deleteLater()
            # Remove from rows, then renormalize
            self.rows = [r for r in self.rows if r["widget"] != row_widget]
            self.renormalize_ranges()
            self.rules_layout.update()
            # Update all labels after removal
            for row in self.rows:
                row["update_labels"]()
            update_remove_buttons()

        remove_btn.clicked.connect(remove)

        row_layout.addWidget(QLabel("Range:"))
        row_layout.addWidget(min_label)
        row_layout.addWidget(slider, stretch=1)
        row_layout.addWidget(max_label)
        row_layout.addWidget(QLabel("Speed:"))
        row_layout.addWidget(speed_spin)
        row_layout.addWidget(remove_btn)

        self.rules_layout.insertWidget(self.rules_layout.count() - 1, row_widget)
        # Store update_labels so we can call it after row removal
        self.rows.append({
            "widget": row_widget,
            "slider": slider,
            "speed": speed_spin,
            "min_label": min_label,
            "max_label": max_label,
            "update_labels": update_labels,
            "remove_btn": remove_btn,
        })

        def on_range_changed(low, high, slider=slider):
            for i, row in enumerate(self.rows):
                if row["slider"] is slider:
                    self.push_neighbors(i, low, high)
                    break
            self.emit_config()
            # Update all labels after a change
            for row in self.rows:
                row["update_labels"]()
        slider.rangeChanged.connect(on_range_changed)

        speed_spin.valueChanged.connect(self.emit_config)

        # Initial label update
        update_labels()

        update_remove_buttons()

    def renormalize_ranges(self):
        """Ensure all ranges are contiguous, min=0, max=100, and at least 1 unit wide."""
        n = len(self.rows)
        if n == 0:
            self.emit_config()
            return
        # Evenly distribute the available range
        min_val = 0
        available = 101  # 0..100 inclusive
        widths = []
        # Try to keep previous widths, but at least 1
        for row in self.rows:
            slider = row["slider"]
            width = max(slider.high() - slider.low(), 1)
            widths.append(width)
        total_width = sum(widths)
        # Scale widths to fit exactly 101 units
        if total_width != available:
            scale = available / total_width
            widths = [max(1, int(round(w * scale))) for w in widths]
            # Fix rounding errors
            while sum(widths) > available:
                for i in range(len(widths)):
                    if widths[i] > 1 and sum(widths) > available:
                        widths[i] -= 1
            while sum(widths) < available:
                for i in range(len(widths)):
                    if sum(widths) < available:
                        widths[i] += 1
        # Now set the sliders
        for i, row in enumerate(self.rows):
            slider = row["slider"]
            slider.setLow(min_val)
            max_val = min_val + widths[i] - 1
            if i == n - 1:
                max_val = 100
            slider.setHigh(max_val)
            min_val = max_val + 1
        self.emit_config()

    def push_neighbors(self, idx, low, high):
        # Enforce: first min is 0, last max is 100, and min < max for all, and no gaps, and at least 1 unit wide
        # Push right neighbor if overlap or gap
        if idx < len(self.rows) - 1:
            next_slider = self.rows[idx+1]["slider"]
            # Always set next min to our max+1 (magnetic, at least 1 unit wide)
            new_min = min(high + 1, 99)  # 99 so next max can be at least new_min+1
            if new_min > next_slider.high() - 1:
                next_slider.setHigh(min(new_min + 1, 100))
            if next_slider.low() != new_min:
                next_slider.setLow(new_min)
                self.push_neighbors(idx+1, next_slider.low(), next_slider.high())
        else:
            # Last max always 100, and at least 1 unit wide
            if high > 99:
                self.rows[idx]["slider"].setHigh(100)
                if self.rows[idx]["slider"].low() > 99:
                    self.rows[idx]["slider"].setLow(99)
            else:
                if self.rows[idx]["slider"].high() != 100:
                    self.rows[idx]["slider"].setHigh(100)
        # Push left neighbor if overlap or gap
        if idx > 0:
            prev_slider = self.rows[idx-1]["slider"]
            # Always set prev max to our min-1 (magnetic, at least 1 unit wide)
            new_max = max(low - 1, 1)  # 1 so prev min can be at most new_max-1
            if new_max < prev_slider.low() + 1:
                prev_slider.setLow(max(new_max - 1, 0))
            if prev_slider.high() != new_max:
                prev_slider.setHigh(new_max)
                self.push_neighbors(idx-1, prev_slider.low(), prev_slider.high())
        else:
            # First min always 0, and at least 1 unit wide
            if low < 1:
                self.rows[idx]["slider"].setLow(0)
                if self.rows[idx]["slider"].high() < 1:
                    self.rows[idx]["slider"].setHigh(1)
            else:
                if self.rows[idx]["slider"].low() != 0:
                    self.rows[idx]["slider"].setLow(0)

    def get_config(self):
        config = []
        for row in self.rows:
            config.append({
                "min": row["slider"].low(),
                "max": row["slider"].high(),
                "speed": row["speed"].value()
            })
        return config

    def emit_config(self):
        self.configChanged.emit(self.get_config())

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.cpu_temp = None
        self.cpu_rpm = None
        self.gpu_temp = None
        self.gpu_rpm = None
        self.auto_fan_config = self.config.get("auto_fan_config", DEFAULT_CONFIG["auto_fan_config"])
        self.current_mode = self.config.get("mode", "Custom")
        self.init_ui()
        self.start_temp_worker()

    def init_ui(self):
        self.setWindowTitle("NitroSensual 1.2")
        self.layout = QVBoxLayout()

        # Mode dropdown and graph button
        mode_layout = QHBoxLayout()
        mode_label = QLabel("Mode:")
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Custom", "Max", "Auto"])
        self.mode_combo.currentTextChanged.connect(self.on_mode_changed)
        mode_layout.addWidget(mode_label)
        mode_layout.addWidget(self.mode_combo)

        mode_layout.addStretch()  # Pushes the button to the right

        self.graph_btn = QPushButton("📈")
        self.graph_btn.setFixedWidth(32)
        self.graph_btn.setToolTip("Configure Auto Mode")
        self.graph_btn.clicked.connect(self.open_auto_config)
        mode_layout.addWidget(self.graph_btn)

        self.layout.addLayout(mode_layout)

        self.cpu_temp_label = QLabel("CPU Temp: ?")
        self.gpu_temp_label = QLabel("GPU Temp: ?")
        self.cpu_speed_label = QLabel()
        self.gpu_speed_label = QLabel()
        self.layout.addWidget(self.cpu_temp_label)
        self.layout.addWidget(self.gpu_temp_label)
        self.layout.addWidget(self.cpu_speed_label)
        self.layout.addWidget(self.gpu_speed_label)

        notice = QLabel(
            '<b>Notice:</b> Please enable <span style="color:red">"Custom"</span> mode in NitroSense for fan control to work!'
        )
        notice.setWordWrap(True)
        self.layout.addWidget(notice)

        cpu_group = QGroupBox("CPU Fan")
        cpu_layout = QVBoxLayout()
        self.cpu_fan_widget = FanControlWidget("cpu", refresh_callback=self.refresh_speeds)
        cpu_layout.addWidget(self.cpu_fan_widget)
        cpu_group.setLayout(cpu_layout)
        self.layout.addWidget(cpu_group)

        gpu_group = QGroupBox("GPU Fan")
        gpu_layout = QVBoxLayout()
        self.gpu_fan_widget = FanControlWidget("gpu", refresh_callback=self.refresh_speeds)
        gpu_layout.addWidget(self.gpu_fan_widget)
        gpu_group.setLayout(gpu_layout)
        self.layout.addWidget(gpu_group)

        self.setLayout(self.layout)
        self.resize(400, 200)

        # Timer for refreshing current speeds and temperature
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_speeds)
        self.timer.start(1000)
        self.refresh_speeds()

        # Set dropdown state
        idx = self.mode_combo.findText(self.current_mode)
        if idx != -1:
            self.mode_combo.setCurrentIndex(idx)
        # Set custom slider values
        self.cpu_fan_widget.slider.setValue(self.config.get("custom_cpu", 50))
        self.gpu_fan_widget.slider.setValue(self.config.get("custom_gpu", 50))

    def start_temp_worker(self):
        self.temp_worker = TempWorker()
        self.temp_worker.temps_updated.connect(self.on_temps_updated)
        self.temp_worker.start()

    def on_temps_updated(self, cpu_temp, cpu_rpm, gpu_temp, gpu_rpm):
        self.cpu_temp = cpu_temp
        self.cpu_rpm = cpu_rpm
        self.gpu_temp = gpu_temp
        self.gpu_rpm = gpu_rpm
        self.update_temp_labels()
        if getattr(self, "current_mode", None) == "Auto":
            self.apply_auto_fan_speeds()

    def update_temp_labels(self):
        cpu_temp_text = f"CPU Temp: {self.cpu_temp if self.cpu_temp is not None else '?'}°C"
        gpu_temp_text = f"GPU Temp: {self.gpu_temp if self.gpu_temp is not None else '?'}°C"
        self.cpu_temp_label.setText(cpu_temp_text)
        self.gpu_temp_label.setText(gpu_temp_text)

    def on_mode_changed(self, mode):
        self.current_mode = mode  # Track current mode
        self.config["mode"] = mode
        # Save custom values if in custom mode
        if mode == "Custom":
            self.cpu_fan_widget.set_custom_mode(True)
            self.gpu_fan_widget.set_custom_mode(True)
            self.cpu_fan_widget.apply_fan_speed()
            self.gpu_fan_widget.apply_fan_speed()
            self.config["custom_cpu"] = self.cpu_fan_widget.slider.value()
            self.config["custom_gpu"] = self.gpu_fan_widget.slider.value()
        elif mode == "Max":
            self.cpu_fan_widget.set_custom_mode(False)
            self.gpu_fan_widget.set_custom_mode(False)
            self.cpu_fan_widget.apply_fan_speed_direct(100)
            self.gpu_fan_widget.apply_fan_speed_direct(100)
        elif mode == "Auto":
            self.cpu_fan_widget.set_custom_mode(False)
            self.gpu_fan_widget.set_custom_mode(False)
            self.apply_auto_fan_speeds()
        save_config(self.config)

    def refresh_speeds(self):
        cpu_percent = read_fan_percentage("cpu")
        gpu_percent = read_fan_percentage("gpu")
        cpu_rpm = self.cpu_rpm if self.cpu_rpm is not None else '?'
        gpu_rpm = self.gpu_rpm if self.gpu_rpm is not None else '?'
        cpu_text = f"CPU Fan Current Speed: {cpu_percent if cpu_percent >= 0 else '?'}% ({cpu_rpm} RPM)"
        gpu_text = f"GPU Fan Current Speed: {gpu_percent if gpu_percent >= 0 else '?'}% ({gpu_rpm} RPM)"
        self.cpu_speed_label.setText(cpu_text)
        self.gpu_speed_label.setText(gpu_text)

    def open_auto_config(self):
        # Backup current config for possible revert
        backup_config = [dict(x) for x in self.auto_fan_config]
        dialog = AutoFanConfigDialog(self, config=[dict(x) for x in self.auto_fan_config])
        dialog.configChanged.connect(self.on_auto_config_live_update)
        result = dialog.exec_()
        if result:  # Save pressed
            self.auto_fan_config = dialog.get_config()
            self.config["auto_fan_config"] = self.auto_fan_config
            save_config(self.config)
        else:  # Cancel or X pressed
            self.auto_fan_config = backup_config
            if self.current_mode == "Auto":
                self.apply_auto_fan_speeds()

    def on_auto_config_live_update(self, config):
        self.auto_fan_config = config
        if self.current_mode == "Auto":
            self.apply_auto_fan_speeds()

    def closeEvent(self, event):
        # Reload config from disk to discard unsaved in-memory changes
        self.config = load_config()
        self.auto_fan_config = self.config.get("auto_fan_config", DEFAULT_CONFIG["auto_fan_config"])
        self.current_mode = self.config.get("mode", "Custom")
        # Optionally, reset UI to match config (not strictly needed on close)
        if hasattr(self, 'temp_worker'):
            self.temp_worker.stop()
            self.temp_worker.wait()
        # Reset dropdown and sliders to config values
        idx = self.mode_combo.findText(self.current_mode)
        if idx != -1:
            self.mode_combo.setCurrentIndex(idx)
        self.cpu_fan_widget.slider.setValue(self.config.get("custom_cpu", 50))
        self.gpu_fan_widget.slider.setValue(self.config.get("custom_gpu", 50))
        event.accept()

    def get_auto_fan_speed(self, temp, config=None):
        if temp is None:
            return 50  # fallback if temp is not available
        if config is None:
            config = self.auto_fan_config
        if not config:
            return 50  # fallback
        # First rule: match temp <= max
        if temp <= config[0]["max"]:
            return config[0]["speed"]
        # Middle rules: min <= temp <= max
        for entry in config[1:-1]:
            if entry["min"] <= temp <= entry["max"]:
                return entry["speed"]
        # Last rule: match temp >= min
        if temp >= config[-1]["min"]:
            return config[-1]["speed"]
        # Fallback (should never happen)
        return 50

    def apply_auto_fan_speeds(self):
        # Use the config for both CPU and GPU, or you can split if you want
        cpu_speed = self.get_auto_fan_speed(self.cpu_temp, self.auto_fan_config)
        gpu_speed = self.get_auto_fan_speed(self.gpu_temp, self.auto_fan_config)
        self.cpu_fan_widget.apply_fan_speed_direct(cpu_speed)
        self.gpu_fan_widget.apply_fan_speed_direct(gpu_speed)

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
