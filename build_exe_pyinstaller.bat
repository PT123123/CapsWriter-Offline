@echo off
chcp 65001
REM 使用PyInstaller将tray_gui.py打包为exe
REM 请确保已安装PyInstaller（pip install pyinstaller）
REM 并在命令行中运行本脚本

pyinstaller --noconfirm --onefile --windowed --icon=assets/icon.ico --debug all tray_gui.py

echo 打包完成！请在dist目录下查找生成的exe文件。
pause
