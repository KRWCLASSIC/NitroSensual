"""Opt-in Acer Predator WMI transport. Importing this module does not touch hardware."""

import winreg


MODEL = 'Predator PHN16S-71'
FANS = {'cpu': 1, 'gpu': 4}
MODES = {'auto': 0x410009, 'max': 0x820009, 'custom': 0xC30009}


def is_supported_predator(manufacturer, model):
    return manufacturer.strip().casefold() == 'acer' and model.strip().casefold() == MODEL.casefold()


def local_model_supported():
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\BIOS') as key:
            manufacturer = winreg.QueryValueEx(key, 'SystemManufacturer')[0]
            model = winreg.QueryValueEx(key, 'SystemProductName')[0]
        return is_supported_predator(manufacturer, model)
    except OSError:
        return False


def invoke_acer_wmi(method, value):
    """Invoke one firmware method on the caller's COM thread (requires WMI access)."""
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    try:
        service = win32com.client.GetObject(r'winmgmts:\\.\root\WMI')
        objects = service.ExecQuery('SELECT * FROM AcerGamingFunction')
        obj = next(iter(objects), None)
        if obj is None:
            raise RuntimeError('AcerGamingFunction not available')
        inputs = obj.Methods_(method).InParameters.SpawnInstance_()
        inputs.Properties_('gmInput').Value = value
        result = obj.ExecMethod_(method, inputs)
        for prop in result.Properties_:
            if prop.Name.casefold() == 'returnvalue':
                accepted = prop.Value if isinstance(prop.Value, bool) else int(prop.Value) == 0
                if not accepted:
                    raise RuntimeError(f'{method} WMI ReturnValue={prop.Value}')
        return int(result.Properties_('gmOutput').Value)
    finally:
        pythoncom.CoUninitialize()


class PredatorWmiBackend:
    def __init__(self, invoke=invoke_acer_wmi):
        self.invoke = invoke
        self.mode = None
        self.last_duty = {}

    def _send(self, method, value):
        output = self.invoke(method, value)
        if output & 0xFF:
            raise RuntimeError(f'{method} returned firmware status {output & 0xFF}')
        return output

    def set_native_mode(self, mode):
        if mode not in MODES:
            raise ValueError(f'Unknown fan mode: {mode}')
        expected = {'auto': 1, 'max': 2, 'custom': 3}[mode]
        if mode != self.mode or any(self.get_behavior(fan) != expected for fan in FANS):
            self._send('SetGamingFanBehavior', MODES[mode])
            self.mode = mode
            self.last_duty.clear()

    def set_custom(self, fan_type, percent):
        if fan_type not in FANS or not isinstance(percent, int) or not 1 <= percent <= 100:
            raise ValueError('Custom fan duty must be 1..100 for CPU/GPU')
        self.set_native_mode('custom')
        if self.last_duty.get(fan_type) == percent and self.get_percent(fan_type) == percent:
            return
        value = ((percent * 25600 // 100) & 0xFF00) + FANS[fan_type]
        self._send('SetGamingFanSpeed', value)
        self.last_duty[fan_type] = percent

    def get_sensor(self, index):
        value = self._send('GetGamingSysInfo', 1 | (index << 8))
        return (value >> 8) & 0xFFFF

    def get_percent(self, fan_type):
        if fan_type not in FANS:
            raise ValueError(f'Unknown fan: {fan_type}')
        value = self._send('GetGamingFanSpeed', FANS[fan_type])
        return (value >> 8) & 0xFFFF

    def get_behavior(self, fan_type):
        if fan_type not in FANS:
            raise ValueError(f'Unknown fan: {fan_type}')
        index = 1 if fan_type == 'cpu' else 3
        value = self._send('GetGamingFanBehavior', index)
        return (value >> 8) & 0xFF
