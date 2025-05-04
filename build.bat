@echo off
pyinstaller --windowed --onefile nitrosensual.py
del /Q nitrosensual.spec 
rmdir /S /Q build