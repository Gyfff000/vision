# 只修改本文件，然后重新运行 tools/build_install.py 生成 install.py。
BUILD_ID = "FLOW_20261012_V1"
QR_CAMERA = "ONBOARD"  # 将来只把此行改为 "USB"；颜色识别始终使用自带摄像头。
UART_ENABLE = True
UART_ID = 3
UART_TX_PIN = 32  # 亚博12针排针物理第5脚，GPIO32。
UART_RX_PIN = 33  # 亚博12针排针物理第3脚，GPIO33。
UART_BAUD = 115200
WIDTH, HEIGHT = 640, 480
IDE_PREVIEW = False  # LCD始终显示。调试IDE画面时改True，会增加传输开销。
PROCESS_SCALE = 0.25  # 仅颜色分割缩小；显示、坐标和扫码仍为640x480。
RING_SCALE = 0.5
DETECT_PERIOD_MS = 100  # 识别间隔；收到定位请求时立即处理新图像。
QR_SCAN_PERIOD_MS = 150  # 扫码间隔；间隔中继续刷新LCD，确认次数按实际解码计。
PRINT_INTERVAL_MS = 1000
GC_INTERVAL_MS = 1000
QR_CONFIRM_FRAMES = 3
TASK_RETRY_MS = 1000
MAX_RESULT_AGE_MS = 600
ACTIVE_COLOR_IDS = (1, 2, 3, 4, 5, 6)
COLOR_ROIS = {"RAW": (80, 60, 480, 360), "PROCESS": None,
              "STORE": None, "STACK": None}
DETECT_ROI = COLOR_ROIS["RAW"]
EDGE_MARGIN = 2
MIN_PIXELS = 32  # 在缩小后的图像中计数。真实物料仍需验证。
MAX_AREA_FRACTION = 0.45
MIN_DENSITY = 0.25
MIN_ASPECT, MAX_ASPECT = 0.25, 4.0
MORPH_RADIUS = 1
STABLE_FRAMES = 4
STABLE_DISTANCE_PX = 12
REFERENCE_PIXEL = (320, 240)
PLANE_H, PLANE_ROI = None, None
# 每种实际工作高度分别标定。None表示不能输出可信毫米坐标。
CALIBRATIONS = {"RAW": (None, None), "PROCESS": (None, None),
                "STORE": (None, None), "STACK": (None, None)}
# 各工位在图像中的区域必须按现场数字1/2/3建立映射，不能猜左右顺序。
STATION_ROIS = {"PROCESS": {}, "STORE": {}}
RING_SLOT_ROIS = {}
RING_THRESHOLD = 3500
RING_MIN_RADIUS, RING_MAX_RADIUS = 8, 90  # 在RING_SCALE=0.5图像中。
COLOR_NAMES = {1: "RED", 2: "YELLOW", 3: "BLUE", 4: "GREEN", 5: "BLACK", 6: "LIGHT_BLUE"}
DRAW_COLORS = {1: (255,40,40), 2: (255,255,0), 3: (80,100,255),
               4: (0,255,0), 5: (255,255,255), 6: (0,255,255)}
HSV_RANGES = {
    1: ((0,10,100,255,60,255), (170,179,100,255,60,255)),
    2: ((15,34,100,255,80,255),),
    3: ((100,135,150,255,60,255),),
    4: ((35,79,80,255,60,255),),
    5: ((0,179,0,255,0,65),),
    6: ((80,135,50,149,100,255),),
}
