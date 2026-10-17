@echo off
"%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -u "%~dp0tools\usb_camera_preview_pc.py" %*
if errorlevel 1 pause
