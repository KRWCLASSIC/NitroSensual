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
