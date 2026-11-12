# K230直接显示USB摄像头画面

版本USB_CAMERA_PREVIEW_20261112。用户已将独立USB摄像头通过Type-C连接K230；本程序专门验证板端取帧与LCD显示，不是电脑预览程序。它不会打开K230自带摄像头，不进行扫码/颜色识别或STM32通信。

## 在IDE临时运行

在电脑CanMV IDE打开D:/K230_pro/k230_usb_camera_test.py，连接K230并停止旧程序，再点击绿色运行。正常情况下LCD及IDE显示摄像头画面，终端出现USB_FOUND、USB_MODE和USB_FRAME_OK，每秒输出USB_FPS。保持640×480、MJPEG、请求30fps；实际帧率以板端输出为准，不能套用电脑上的30fps测量。

## Type-C被摄像头占用时

先临时将K230连接电脑，在CanMV IDE运行D:/K230_pro/k230_usb_camera_install.py一次。程序在板端备份原main.py到/sdcard/vision_backup/，写入并读回验证/sdcard/usb_camera_preview.py和/sdcard/main.py，最后打印两条INSTALL_OK。

随后断电，断开电脑，重新接好USB摄像头，按板卡要求给K230供电，重新上电。约3秒程序延时后开始检测USB摄像头，屏幕先显示等待，再显示画面或错误码。此安装会把原比赛程序的自启动入口切为USB预览；需要恢复比赛时运行比赛工程自己的install.py，或恢复本次安装前的main.py备份。不要删除boot.py，不需要重刷固件。

安装器内嵌程序；修改预览源文件后必须重新生成安装器，不能用旧安装器覆盖修改。生成方式：python tools/build_usb_camera_installer.py。

## 错误码

| 输出 | 含义 |
|---|---|
| USB_UNSUPPORTED | 当前固件没有media.uvc模块 |
| USB_NOT_FOUND | 10秒内未枚举到设备，检查Host模式、供电和数据线 |
| USB_MODE_FAILED | 请求的视频模式未成功协商 |
| USB_START_FAILED | 视频流未成功启动 |
| USB_FRAME_TIMEOUT | 设备/视频流已启动，但未持续读到图像 |

错误码保留在LCD，便于脱离电脑查看。普通Type-C插头或转接线不能自行赋予板子Host功能。这个程序用于验证现有连接，不修改USB控制器角色/板卡固件，也不能仅凭失败断言摄像头损坏。

依据官方CanMV UVC接口编写，兼容旧FORMAT_MJPEG和新FOURCC_MJPEG常量。尚未在用户当前K230连接上取得USB_FRAME_OK，不能宣称Type-C接入已成功。
