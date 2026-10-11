# STM32 与 K230 视觉通信 V1

本包只传视觉数据，不驱动电机。串口使用3.3V TTL、115200、8N1：K230 TX接STM32 RX，RX接TX，共地。不要把IDE的USB虚拟串口当作已连接STM32的UART。双方串口号和实际可用引脚确定后，在K230文件头填写 `UART_ID/UART_TX_PIN/UART_RX_PIN`，再将 `UART_ENABLE=True`。默认未配置，不会占用未知引脚。

## 报文

ASCII字节帧：`$正文*四位CRC十六进制\r\n`。CRC16-CCITT-FALSE，初始FFFF，多项式1021，不反射，无最终异或，覆盖正文，不含$、*、换行。已知向量 `123456789 -> 29B1`。最长正文240字节。下列示例中的 `CRC` 为示意，不能直接照发；编码函数会生成真实校验值。

请求正文：`V1,seq,command`。seq范围0～65535，每个新请求递增，不同时挂起多个请求。

| command | 响应 |
|---|---|
| PING | PONG和DONE，先测通链路 |
| COLOR | 每色最大一个BLOCK，或NO_TARGET，最后DONE |
| RING | 最多三个RING，或NO_TARGET，最后DONE |
| ARUCO | 0号标记ARUCO或NO_MARKER，最后DONE |
| QR | 唯一二维码QR或NO_QR，最后DONE |
| STOP | 停止采集，STOPPED和DONE；不是控制整车停车 |

COLOR/RING/ARUCO可有一个参数：`V1,seq,COLOR,GRASP`，标定配置GRASP/PLACE/STACK由主程序 `CALIBRATIONS` 定义。无参数使用 `PLANE_H/PLANE_ROI`。切换模式或标定配置会重置稳定历史。

检测记录正文统一：

```text
V1,seq,BLOCK,id,cx,cy,dx,dy,pixels,slot,valid,stable,calibrated,x_mm,y_mm
V1,seq,RING,id,cx,cy,dx,dy,pixels,slot,valid,stable,calibrated,x_mm,y_mm
V1,seq,ARUCO,id,cx,cy,dx,dy,pixels,slot,valid,stable,calibrated,x_mm,y_mm
```

- BLOCK id：1红、2黄、3蓝、4绿、5黑、6浅蓝。银奖RGB版只启用1/4/3，不沿用上游0/1/2编号。
- cx/cy为640×480原图中心像素；dx/dy相对 `REFERENCE_PIXEL`，右/下为正。pixels是按比例折算的掩膜像素数。
- slot：圆环已配置的工位编号1/2/3，未知为0；不是原项目左上/右上/下方的pos。BLOCK/ARUCO默认0。
- valid：过滤通过；stable：连续4帧视觉中心稳定。ARUCO目前stable固定0，没有跨帧确认。
- calibrated：标定矩阵且有效域存在才为1；否则x_mm/y_mm为字符串NA，禁止把NA当0毫米。毫米是标定平面坐标，不是通用机械偏差。

二维码：`V1,seq,QR,valid,stable,payload_hex`。载荷是UTF-8字节转十六进制，最大64字节，避免逗号/换行破坏报文。valid只表示符合2027四组三位任务码；stable表示唯一二维码连续3帧相同。`Good`是解码测试，valid=0，稳定后终端打印Good；不能当搬运任务。

结束：`V1,seq,DONE,count,frame_ms`。count只计BLOCK/RING/ARUCO/QR数据帧，不计NO_TARGET等状态帧。frame_ms是K230本地计时，不能直接和STM32时间相减。错误：`V1,seq,ERROR,reason`，随后DONE；错误请求清空可用结果，不能使用半包。PING响应为 `V1,seq,PONG,K230,1,mode`。

解析器接收分段/粘包，遇$重新同步，拒绝CRC错误和超长帧。K230不缓存上次结果作为本次响应；同次读取到多个视觉请求时只处理第一个，其他返回BUSY。主控从发出请求到完成实行超时，首次/切换相机建议5秒，稳定后按实测时延调整；初版六色约3fps，不能假定30fps或100ms必返回。

## STM32 工程接入

把 `stm32/vision_client.c` 与 `.h` 加到Keil或CubeIDE工程。它们不依赖具体型号或HAL；C99电脑编译及跨语言报文检查通过，实际STM32编译/收发未测。MCU工程需要可用的 `snprintf/strtof` 支持。

在串口中断/DMA回调中把字节放入接收环形缓冲区，在主循环/任务里调用 `vision_feed`；不要在中断里做浮点解析或阻塞发送。调用 `vision_tick`检查超时。缓冲区溢出时放弃当前请求并重试，不能继续消费不完整结果。

```c
VisionClient vision;
char tx[80];
uint16_t sequence = 1;

/* 初始化一次 */
vision_init(&vision);

/* 空闲时发出请求；send_uart是你们STM32工程已有的发送函数。 */
size_t n = vision_request(&vision, sequence++, "PING",
                        now_ms, 5000, tx, sizeof(tx));
if (n) send_uart((const uint8_t *)tx, n);

/* 主循环：把环形缓冲区里的有效字节交给接收器。 */
vision_feed(&vision, received_bytes, received_length);
vision_tick(&vision, now_ms);

/* 仅在本次DONE完成且无错误时读取。每发新请求会清除上次结果。 */
if (vision.complete && !vision.failed) {
    if (vision.pong) { /* PING通过，可改为COLOR测试 */ }
    for (unsigned i=0; i<vision.count; ++i) {
        const VisionRecord *r = &vision.records[i];
        if (r->valid && r->stable) {
            /* 读取id/cx/cy/dx/dy；只有r->calibrated时读取毫米坐标。
               选择目标、运动约束和抓放许可由STM32决定。 */
        }
    }
    vision.complete = 0;
}
```

带工作平面配置的请求用 `vision_request_profile(...,"COLOR","GRASP",...)`；其余参数与 `vision_request` 相同。若发送失败，不要继续等待本次结果，应重新初始化接收状态后重试。收到超时、ERROR、NO_TARGET或stable=0时，不沿用旧坐标。

通信验收顺序：PING来回 → 空画面COLOR → 静止目标COLOR及消失 → QR任务码 → 错CRC/断线/超时 → 标定坐标。先不用接电机，也能把协议测通。电脑可用USB转3.3V-TTL适配器及 `tools/vision_serial_console.py` 协助测试。
