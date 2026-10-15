# 电脑直接预览外接USB摄像头

本工具在Windows电脑运行，按DirectShow设备名FHD Camera选择外接摄像头，不依赖K230。仅显示实时画面，不保存照片或视频。按ESC/Q或关闭预览窗口退出。

本机启动命令：

```powershell
& "D:\K230_pro\USB_camera_PC\打开USB摄像头.cmd"
```

本机启动器使用用户目录下现有Codex Python运行时。其他电脑需先安装Python和tools/requirements-pc-camera.txt中的依赖，再运行python tools/usb_camera_preview_pc.py。camera_deps目录仅为本机下载的依赖，不提交仓库。

如设备改名，可用--list查看名称，再传--camera-name "实际名称"。找不到或出现多个同名设备会明确报错，不会退回内置摄像头。若被其他应用占用，先关闭Windows相机、会议软件后重试。

2026-10-16实测：DirectShow枚举0=Integrated Webcam，1=FHD Camera；程序按名称选择FHD Camera并实际收到三帧640×480图像。该结果证明当时能采集视频，不表示已经完成长期稳定性和所有模式测试。
