# 电脑直接预览外接USB摄像头

本工具在Windows电脑运行，按DirectShow设备名FHD Camera选择外接摄像头，不依赖K230。仅显示实时画面，不保存照片或视频。按ESC/Q或关闭预览窗口退出。

2026-10-17新增画面上方的摄像头按钮：直接点击FHD Camera/Integrated Webcam切换，或先点击画面取得焦点再按C、Tab循环切换，也可在画面窗口按0/1选择当前列表中的设备。编号可能随重新插拔改变，应看设备名称。PowerShell出现PS提示符后表示程序已退出，此时输入1不会切换摄像头。摄像头被占用或断开时保留选择按钮和错误提示，按R重试。

本机启动命令：

```powershell
& "D:\K230_pro\USB_camera_PC\打开USB摄像头.cmd"
```

本机启动器使用用户目录下现有Codex Python运行时。其他电脑需先安装Python和tools/requirements-pc-camera.txt中的依赖，再运行python tools/usb_camera_preview_pc.py。camera_deps目录仅为本机下载的依赖，不提交仓库。

如设备改名，可用--list查看名称，再传--camera-name "实际名称"。找不到或出现多个同名设备会明确报错，不会退回内置摄像头。若被其他应用占用，先关闭Windows相机、会议软件后重试。

启动器支持传递参数，例如直接打开内置摄像头：

```powershell
& "D:\K230_pro\USB_camera_PC\打开USB摄像头.cmd" --camera-name "Integrated Webcam"
```

2026-10-16实测：DirectShow枚举0=Integrated Webcam，1=FHD Camera；程序按名称选择FHD Camera并实际收到三帧640×480图像。该结果证明当时能采集视频，不表示已经完成长期稳定性和所有模式测试。
