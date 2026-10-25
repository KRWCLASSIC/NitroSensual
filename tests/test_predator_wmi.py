import unittest

from predator_wmi import PredatorWmiBackend, is_supported_predator


class PredatorWmiTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.outputs = {}

        def invoke(method, value):
            self.calls.append((method, value))
            return self.outputs.get(method, 0)

        self.backend = PredatorWmiBackend(invoke)

    def test_only_supported_predator_model_is_selected(self):
        self.assertTrue(is_supported_predator('Acer', 'Predator PHN16S-71'))
        self.assertFalse(is_supported_predator('Acer', 'Nitro AN515-58'))
        self.assertFalse(is_supported_predator('Other', 'Predator PHN16S-71'))

    def test_custom_mode_precedes_cpu_and_gpu_commands(self):
        self.outputs['GetGamingFanBehavior'] = 0x300
        self.backend.set_custom('cpu', 50)
        self.backend.set_custom('gpu', 100)
        self.assertEqual([call for call in self.calls if call[0].startswith('Set')], [
            ('SetGamingFanBehavior', 0xC30009),
            ('SetGamingFanSpeed', 0x3201),
            ('SetGamingFanSpeed', 0x6404),
        ])

    def test_duplicate_duty_is_not_rewritten(self):
        self.outputs['GetGamingFanBehavior'] = 0x300
        self.outputs['GetGamingFanSpeed'] = 50 << 8
        self.backend.set_custom('cpu', 50)
        self.backend.set_custom('cpu', 50)
        self.assertEqual(len([call for call in self.calls if call[0] == 'SetGamingFanSpeed']), 1)

    def test_external_auto_change_reapplies_custom_even_with_same_percent(self):
        self.outputs['GetGamingFanBehavior'] = 0x300
        self.outputs['GetGamingFanSpeed'] = 50 << 8
        self.backend.set_custom('cpu', 50)
        self.outputs['GetGamingFanBehavior'] = 0x100
        self.backend.set_custom('cpu', 50)
        self.assertEqual(len([call for call in self.calls if call[0] == 'SetGamingFanBehavior']), 2)
        self.assertEqual(len([call for call in self.calls if call[0] == 'SetGamingFanSpeed']), 2)

    def test_zero_duty_is_rejected(self):
        with self.assertRaises(ValueError):
            self.backend.set_custom('cpu', 0)
        self.assertEqual(self.calls, [])

    def test_failed_wmi_status_does_not_cache_the_command(self):
        self.outputs['SetGamingFanSpeed'] = 1
        with self.assertRaises(RuntimeError):
            self.backend.set_custom('cpu', 50)
        self.outputs.clear()
        self.backend.set_custom('cpu', 50)
        self.assertEqual([x for x in self.calls if x[0] == 'SetGamingFanSpeed'], [
            ('SetGamingFanSpeed', 0x3201), ('SetGamingFanSpeed', 0x3201),
        ])

    def test_native_auto_is_not_ui_auto_curve(self):
        self.backend.set_native_mode('auto')
        self.assertEqual(self.calls, [('SetGamingFanBehavior', 0x410009)])

    def test_sensor_decodes_status_and_value(self):
        self.outputs['GetGamingSysInfo'] = 65 << 8
        self.assertEqual(self.backend.get_sensor(1), 65)
        self.assertEqual(self.calls, [('GetGamingSysInfo', 0x101)])

    def test_wmi_transport_accepts_true_return_value(self):
        self._test_wmi_return_value(True, should_fail=False)

    def test_wmi_transport_rejects_false_return_value(self):
        self._test_wmi_return_value(False, should_fail=True)

    def _test_wmi_return_value(self, return_value, should_fail):
        from unittest.mock import patch
        import sys
        import types
        from predator_wmi import invoke_acer_wmi

        class Param:
            def __init__(self, name, value=0):
                self.Name, self.Value = name, value
        class Params:
            def __init__(self, items):
                self.items = items
            def __call__(self, name):
                return next(x for x in self.items if x.Name == name)
            def __iter__(self):
                return iter(self.items)
        class Obj:
            def Methods_(self, method):
                return types.SimpleNamespace(InParameters=types.SimpleNamespace(
                    SpawnInstance_=lambda: types.SimpleNamespace(Properties_=Params([Param('gmInput')]))))
            def ExecMethod_(self, method, inputs):
                return types.SimpleNamespace(Properties_=Params([Param('gmOutput', 0), Param('ReturnValue', return_value)]))
        service = types.SimpleNamespace(ExecQuery=lambda _: [Obj()])
        com = types.ModuleType('win32com')
        com.client = types.SimpleNamespace(GetObject=lambda _: service)
        with patch.dict(sys.modules, {
            'pythoncom': types.SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None),
            'win32com': com, 'win32com.client': com.client,
        }):
            if should_fail:
                with self.assertRaisesRegex(RuntimeError, 'ReturnValue'):
                    invoke_acer_wmi('SetGamingFanBehavior', 0xC30009)
            else:
                self.assertEqual(invoke_acer_wmi('SetGamingFanBehavior', 0xC30009), 0)


if __name__ == '__main__':
    unittest.main()
