# 六色直接识别提速版

版本：SIX_COLOR_FAST_20261015。开机模式为COLOR，直接同时检测红、黄、蓝、绿、黑、浅蓝，不需要任务二维码。由用户D:/K230_pro/k230_silver_rgb.py现有文件更新，保留HSV阈值、全画面搜索以及UART3/GPIO32/33/115200配置。串口协议仍为旧六色版V1请求应答，不包含比赛流程TASK_ACK/STEP。

## 先临时运行

在CanMV IDE停止当前程序，重新打开电脑本地的k230_silver_rgb.py，点击绿色运行。不要继续使用IDE里此前未刷新的旧标签。终端应打印 `[GX_BUILD] SIX_COLOR_FAST_20261015 colors=(1, 2, 3, 4, 5, 6)`。

不测试主控时可将UART_ENABLE改为False。LCD始终显示；默认IDE_PREVIEW=False，所以IDE帧缓冲区不显示实时画面是正常的。需要电脑端预览时改为True，保存后重新运行，会增加图传开销。

仅运行应用不会覆盖已有比赛流程的自启动入口。要改成上电自动运行此六色版本，才运行本目录配套的k230_install_autostart.py；看到两个INSTALL_OK后断电重启。安装器备份旧main.py到/sdcard/vision_backup/，随后把启动入口切为六色版。修改应用后须重新用tools/prepare_autostart.py生成安装器，避免旧内嵌代码覆盖修改。

## 提速设置与取舍

| 设置 | 默认值 | 含义 |
|---|---|---|
| PROCESS_SCALE | 0.25 | 六色在160×120图像分割，LCD及输出坐标仍为640×480 |
| MIN_PIXELS | 32 | 配合0.25缩放的最小色块像素数 |
| DETECT_PERIOD_MS | 100 | 每次检测结束后至少间隔100ms；期间持续采集和显示 |
| IDE_PREVIEW | False | 关闭电脑图传，保留LCD显示 |
| PRINT_INTERVAL_MS | 1000 | 每秒输出一次统计及目标 |
| GC_INTERVAL_MS | 1000 | 每秒清理内存，不再每帧清理 |
| GEOMETRY_SCALE | 0.5 | 可选圆环/ArUco仍使用旧分辨率 |

画面FPS是显示循环刷新率，DET是实际检测频率。100ms不是保证10次识别/秒，实际还要加计算耗时。降低DETECT_PERIOD_MS可以更频繁地检测，但会减少用于显示的空闲帧；设0表示每帧检测。六色同时计算、全画面搜索比比赛流程版只计算任务三色更费时，不能保证二者FPS相同。

缩小分割图会损失小物块及边缘细节。需要精细定位时可将PROCESS_SCALE改回0.5，同时MIN_PIXELS改回125、EDGE_MARGIN改回3，再按实际物块验证。HSV阈值没有因本次提速修改，识别准确率仍需实物光照验证。

串口COLOR/RING/QR等定位请求会立即处理新摄像头帧，定时检测的缓存仅用于画框；超过600ms的缓存框停止显示。stable计数只在真实检测时更新，QR确认也只计算实际解码次数。

验证：18项桌面算法/通信/主循环检查通过，另检查安装器内嵌代码一致性、备份和重复安装。未在实板测量FPS，未操作板端安装；请运行后查看终端GX_STATUS的fps、detect_fps和耗时。
