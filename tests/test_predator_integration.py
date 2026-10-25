import os
import sys
import types
import unittest
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.modules['elevate'] = types.SimpleNamespace(elevate=lambda: None)
import nitrosensual


class PredatorAppIntegrationTests(unittest.TestCase):
    def test_predator_routes_sensor_and_duty_without_legacy_pipe_or_registry(self):
        class FakeBackend:
            def __init__(self):
                self.calls = []
            def get_sensor(self, index):
                self.calls.append(('sensor', index))
                return index + 40
            def get_percent(self, fan):
                self.calls.append(('percent', fan))
                return 60
            def set_custom(self, fan, percent):
                self.calls.append(('custom', fan, percent))

        backend = FakeBackend()
        with patch.object(nitrosensual, 'IS_PREDATOR', True), patch.object(nitrosensual, 'PREDATOR_BACKEND', backend), patch.object(nitrosensual.win32file, 'CreateFile', side_effect=AssertionError('legacy pipe')), patch.object(nitrosensual.winreg, 'CreateKeyEx', side_effect=AssertionError('registry write')):
            self.assertEqual(nitrosensual.read_fan_percentage('cpu'), 60)
            self.assertEqual(nitrosensual.get_acer_gaming_system_info(1), 41 << 8)
            success, _ = nitrosensual.apply_fan_speed('gpu', 50)
            self.assertTrue(success)
        self.assertEqual(backend.calls, [('percent', 'cpu'), ('sensor', 1), ('custom', 'gpu', 50)])

    def test_missing_temperature_does_not_issue_auto_duty(self):
        class FakeFan:
            def apply_fan_speed_direct(self, value):
                raise AssertionError('cannot set fan duty without a temperature')
        window = types.SimpleNamespace()
        window.cpu_temp = None
        window.gpu_temp = None
        window.cpu_fan_widget = FakeFan()
        window.gpu_fan_widget = FakeFan()
        window.auto_fan_config = []
        class FakeBackend:
            def __init__(self):
                self.modes = []
            def set_native_mode(self, mode):
                self.modes.append(mode)
        backend = FakeBackend()
        with patch.object(nitrosensual, 'IS_PREDATOR', True), patch.object(nitrosensual, 'PREDATOR_BACKEND', backend):
            nitrosensual.MainWindow.apply_auto_fan_speeds(window)
        self.assertEqual(backend.modes, ['auto'])

    def test_failed_duty_attempts_firmware_auto(self):
        class FakeBackend:
            def __init__(self):
                self.calls = []
            def set_custom(self, fan, percent):
                self.calls.append(('custom', fan, percent))
                raise RuntimeError('firmware rejected command')
            def set_native_mode(self, mode):
                self.calls.append(('mode', mode))
        backend = FakeBackend()
        with patch.object(nitrosensual, 'IS_PREDATOR', True), patch.object(nitrosensual, 'PREDATOR_BACKEND', backend):
            success, reason = nitrosensual.apply_fan_speed('gpu', 50)
        self.assertFalse(success)
        self.assertIn('rejected', reason)
        self.assertEqual(backend.calls, [('custom', 'gpu', 50), ('mode', 'auto')])

    def test_failed_read_does_not_initialize_manual_slider_to_zero(self):
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        with patch.object(nitrosensual, 'read_fan_percentage', return_value=-1):
            widget = nitrosensual.FanControlWidget('cpu')
            self.assertEqual(widget.slider.value(), 50)
        widget.deleteLater()

    def test_closing_app_restores_firmware_auto(self):
        backend = types.SimpleNamespace(modes=[])
        backend.set_native_mode = lambda mode: backend.modes.append(mode)
        window = types.SimpleNamespace(
            config=nitrosensual.DEFAULT_CONFIG.copy(),
            mode_combo=types.SimpleNamespace(findText=lambda mode: -1),
            cpu_fan_widget=types.SimpleNamespace(slider=types.SimpleNamespace(setValue=lambda _: None)),
            gpu_fan_widget=types.SimpleNamespace(slider=types.SimpleNamespace(setValue=lambda _: None)),
        )
        event = types.SimpleNamespace(accept=lambda: None)
        with patch.object(nitrosensual, 'IS_PREDATOR', True), patch.object(nitrosensual, 'PREDATOR_BACKEND', backend), patch.object(nitrosensual, 'load_config', return_value=nitrosensual.DEFAULT_CONFIG.copy()):
            nitrosensual.MainWindow.closeEvent(window, event)
        self.assertEqual(backend.modes, ['auto'])

    def test_predator_manual_slider_never_offers_zero(self):
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        with patch.object(nitrosensual, 'IS_PREDATOR', True), patch.object(nitrosensual, 'read_fan_percentage', return_value=50):
            widget = nitrosensual.FanControlWidget('cpu')
            self.assertEqual(widget.slider.minimum(), 1)
        widget.deleteLater()

    def test_failed_max_restores_auto_and_reconciles_ui(self):
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        class FakeBackend:
            def __init__(self):
                self.modes = []
            def set_native_mode(self, mode):
                self.modes.append(mode)
                if mode == 'max':
                    raise RuntimeError('max rejected')
        backend = FakeBackend()
        with patch.object(nitrosensual, 'IS_PREDATOR', True), patch.object(nitrosensual, 'PREDATOR_BACKEND', backend), patch.object(nitrosensual, 'load_config', return_value=nitrosensual.DEFAULT_CONFIG.copy()), patch.object(nitrosensual, 'save_config'), patch.object(nitrosensual, 'read_fan_percentage', return_value=50), patch.object(nitrosensual.MainWindow, 'start_temp_worker'):
            window = nitrosensual.MainWindow()
            window.timer.stop()
            window.mode_combo.setCurrentText('Max')
            self.assertEqual(backend.modes, ['max', 'auto'])
            self.assertEqual(window.mode_combo.currentText(), 'Firmware Auto')
            self.assertIn('max rejected', window.hardware_status.text())
        window.deleteLater()

    def test_failed_firmware_auto_does_not_escape_timer_callback(self):
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        class FakeBackend:
            def set_native_mode(self, mode):
                raise RuntimeError('auto rejected')
        with patch.object(nitrosensual, 'IS_PREDATOR', True), patch.object(nitrosensual, 'PREDATOR_BACKEND', FakeBackend()), patch.object(nitrosensual, 'load_config', return_value=nitrosensual.DEFAULT_CONFIG.copy()), patch.object(nitrosensual, 'save_config'), patch.object(nitrosensual, 'read_fan_percentage', return_value=50), patch.object(nitrosensual.MainWindow, 'start_temp_worker'):
            window = nitrosensual.MainWindow()
            window.timer.stop()
            window.current_mode = 'Auto'
            window.apply_auto_fan_speeds()
            self.assertEqual(window.current_mode, 'Error')
            self.assertIn('auto rejected', window.hardware_status.text())
        window.deleteLater()
    def test_close_failure_stays_visible_and_does_not_accept_event(self):
        class FakeBackend:
            def set_native_mode(self, mode):
                raise RuntimeError('restore denied')
        status = types.SimpleNamespace(text='', setText=lambda text: setattr(status, 'text', text))
        window = types.SimpleNamespace(
            mode_combo=types.SimpleNamespace(findText=lambda _: -1),
            cpu_fan_widget=types.SimpleNamespace(slider=types.SimpleNamespace(setValue=lambda _: None)),
            gpu_fan_widget=types.SimpleNamespace(slider=types.SimpleNamespace(setValue=lambda _: None)),
            hardware_status=status,
        )
        event = types.SimpleNamespace(accepted=False, ignored=False,
            accept=lambda: setattr(event, 'accepted', True),
            ignore=lambda: setattr(event, 'ignored', True))
        with patch.object(nitrosensual, 'IS_PREDATOR', True), patch.object(nitrosensual, 'PREDATOR_BACKEND', FakeBackend()), patch.object(nitrosensual, 'load_config', return_value=nitrosensual.DEFAULT_CONFIG.copy()):
            nitrosensual.MainWindow.closeEvent(window, event)
        self.assertTrue(event.ignored)
        self.assertFalse(event.accepted)
        self.assertIn('restore denied', status.text)
    def test_close_does_not_reapply_saved_custom_mode(self):
        calls = []
        backend = types.SimpleNamespace(set_native_mode=lambda mode: calls.append(('mode', mode)))
        window = types.SimpleNamespace(
            timer=types.SimpleNamespace(stop=lambda: calls.append(('timer', 'stop'))),
            mode_combo=types.SimpleNamespace(findText=lambda _: 0,
                setCurrentIndex=lambda _: calls.append(('unexpected', 'reselected saved mode'))),
        )
        event = types.SimpleNamespace(accept=lambda: calls.append(('event', 'accept')))
        with patch.object(nitrosensual, 'IS_PREDATOR', True), patch.object(nitrosensual, 'PREDATOR_BACKEND', backend), patch.object(nitrosensual, 'load_config', return_value=nitrosensual.DEFAULT_CONFIG.copy()):
            nitrosensual.MainWindow.closeEvent(window, event)
        self.assertEqual(calls, [('timer', 'stop'), ('mode', 'auto'), ('event', 'accept')])

    def test_failed_auto_selection_can_be_retried_in_dropdown(self):
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        class FakeBackend:
            def __init__(self):
                self.attempts = 0
            def set_native_mode(self, mode):
                self.attempts += 1
                if self.attempts <= 2:
                    raise RuntimeError('auto refused')
        backend = FakeBackend()
        with patch.object(nitrosensual, 'IS_PREDATOR', True), patch.object(nitrosensual, 'PREDATOR_BACKEND', backend), patch.object(nitrosensual, 'load_config', return_value=nitrosensual.DEFAULT_CONFIG.copy()), patch.object(nitrosensual, 'save_config'), patch.object(nitrosensual, 'read_fan_percentage', return_value=50), patch.object(nitrosensual.MainWindow, 'start_temp_worker'):
            window = nitrosensual.MainWindow()
            window.timer.stop()
            window.mode_combo.setCurrentText('Firmware Auto')
            self.assertEqual(window.mode_combo.currentIndex(), -1)
            self.assertEqual(window.current_mode, 'Error')
            window.mode_combo.setCurrentText('Firmware Auto')
            self.assertEqual(backend.attempts, 3)
            self.assertEqual(window.current_mode, 'Firmware Auto')
        window.deleteLater()


if __name__ == '__main__':
    unittest.main()
