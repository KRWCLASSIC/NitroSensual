# NitroSensual `1.2`

**NitroSensual** is a Windows fan control and monitoring app for Acer Nitro laptops and similar systems, might even work for Predator series. It provides bloatless GUI for controlling CPU and GPU fan speeds, and displays real-time temperature readings using LibreHardwareMonitor.

> This app abuses how NitroSense works so don't remove it, Predator series and their PredatorSense app wasn't tested due to me not owning Predator series laptop, if someone can confirm for me if it works then please open an issue or pull request with patched code!

## Features

- Control CPU and GPU fan speeds (requires NitroSense in Custom mode)
- View real-time CPU and GPU temperatures
- Auto mode for temperature ranges with editor
- Automatic admin privilege elevation for registry access
- Clean PyQt5 interface

## How It Works

- **Fan control**: NitroSensual writes to the NitroSense registry keys and communicates with the PredatorSense service to set fan speeds.

- **Laptop monitoring**: Uses PSsvc (PredatorSense Service) to read temperatures and fan speeds.

> If something breaks, due to how it's designed you can reset fan speeds in NitroSense by manually setting speed or switching to Auto.

## Installation

A ready-to-use Windows binary is available in the [Releases](https://github.com/KRWCLASSIC/NitroSensual/releases) tab.

## Usage

Double click and use GUI to control your fans!

> CLI Support will be added in the near future!

## Notes

- You must enable "Custom" mode in NitroSense for fan control to work.
- You must have PredatorSense service (PSsvc) running to use this app.

## Experimental Predator PHN16S-71 support (source checkout)

On this exact Acer model, the source version uses `root\WMI:AcerGamingFunction`
instead of the NitroSense registry and legacy PredatorSense named pipe. This
route has unit tests and its WMI backend was validated on a Predator
PHN16S-71 with PredatorSense 5.1.514.0: a short 50% CPU/GPU trial reported
50% for both fans, raised RPM, and successfully restored firmware Auto.
The full GUI has only been smoke-tested with WMI mocked; do not assume
other Predator models behave the same way. Keep PredatorSense installed to
restore firmware Auto mode if the process crashes; avoid running it concurrently
with this app because the two programs can override each other's fan settings.
Administrator permissions are required for WMI access. Other models continue
to use the legacy path.

The UI's Auto mode is a configurable temperature curve; it is *not* firmware
Auto. If either temperature is unavailable or the curve requests 0%, the
Predator route returns control to firmware Auto rather than writing 0% duty.
Repeated, unchanged fan duty is not resent. Test with working temperature and
RPM readings before using Custom or the temperature curve.

Run the offline tests with `python -m unittest discover -s tests -v`; tests
mock WMI and do not change fan settings.
