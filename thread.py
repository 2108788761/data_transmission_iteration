# coding=gb2312
import configparser
import json
import sqlite3
import socket
import pandas as pd
import time
import datetime
import threading
from PyQt5.QtCore import QTimer, QThread, pyqtSignal
import serial
import serial.tools.list_ports
from PyQt5.QtWebSockets import QWebSocket
from PyQt5.QtNetwork import QNetworkRequest
from PyQt5.QtCore import QUrl
from crcmod import crcmod
import struct
import numpy as np
from PyQt5.QtNetwork import QNetworkProxy
import os
import logging
from logging.handlers import RotatingFileHandler
import datetime
from collections import deque
# 按 db 文件路径串行化写操作，避免多线程同时写同一 db 导致锁/异常
_db_write_locks = {}
_db_write_locks_mutex = threading.Lock()
def _get_db_write_lock(db_path):
    """同一 db 文件共用一个写锁，保证同一时刻只有一个写事务。"""
    path = os.path.normpath(os.path.abspath(db_path))
    with _db_write_locks_mutex:
        if path not in _db_write_locks:
            _db_write_locks[path] = threading.Lock()
        return _db_write_locks[path]
class ViscosityProcessor:
    """
    粘度数据处理：校准 + 去异常 + 平滑
    """
    def __init__(self,
                 k: float,
                 b: float,
                 spike_ratio_max: float = 0.3,
                 smooth_window: int = 5):
        # 标定参数
        self.k = k
        self.b = b
        # 异常点判定：相对变化比例阈值（例如 0.3 = 30%）
        self.spike_ratio_max = spike_ratio_max
        # 平滑窗口
        self.smooth_window = smooth_window
        self._buf = deque(maxlen=smooth_window)
        self._last_valid = None
    def _is_spike(self, v_prev: float | None, v_new: float) -> bool:
        if v_prev is None:
            return False
        base = max(abs(v_prev), 1e-6)
        return abs(v_new - v_prev) > self.spike_ratio_max * base
    def _smooth(self, v: float) -> float:
        self._buf.append(v)
        return sum(self._buf) / len(self._buf)
    def process_raw_value(self, raw_viscosity: float) -> float:
        """
        传入一次“原始粘度值”（未标定、或简单换算后的），返回：
        已标定 + 去异常 + 平滑后的最终粘度。
        """
        # 1. 线性校准
        true_v = self.k * raw_viscosity + self.b
        # 2. 异常点检测
        if self._is_spike(self._last_valid, true_v):
            # 异常点，用上一个有效值替代（也可以选择丢弃）
            if self._last_valid is not None:
                true_v = self._last_valid
        self._last_valid = true_v
        # 3. 平滑
        smooth_v = self._smooth(true_v)
        return smooth_v

from collections import deque
import time

from collections import deque
import time

class ViscosityStateFilter:
    """
    目标：
    - 不使用硬阈值 hard_min/hard_max（按你的要求去掉）
    - 支持：
      1）“突增很多倍 -> 很快又回落”判为异常毛刺（不改变 stable）
      2）候选上升/候选下降：持续/频率满足则确认切换 stable
    - 输出做轻度平滑（滑动平均）
    """

    STATE_STABLE = 0
    STATE_CANDIDATE_UP = 1
    STATE_CANDIDATE_DOWN = 2

    def __init__(
        self,
        k: float,
        b: float,

        # 上升触发（同时满足更稳）
        jump_abs: float = 8.0,          # 比 stable 高出至少 8
        jump_ratio: float = 1.6,        # 且至少是 stable 的 1.6 倍

        # 下降触发（同时满足更稳）
        drop_abs: float = 8.0,          # 比 stable 低至少 8
        drop_ratio: float = 1.6,        # 且 stable 至少是 v 的 1.6 倍（等价于 v <= stable / drop_ratio）

        # 确认窗口：N 秒内命中 >= need 次 判定真实变化
        confirm_window_s: int = 8,
        confirm_need: int = 5,
        fast_consecutive: int = 3,      # 连续命中次数达到则快速确认

        # 输出平滑
        smooth_window: int = 5,

        # ===== 新增：突增后快速回落判异常（“好多倍→又降回来”）=====
        spike_ratio: float = 3.0,       # “好多倍”的定义：v >= stable * spike_ratio
        spike_return_ratio: float = 1.2,# “降回来”的定义：回到 stable 的 1.2 倍以内
        spike_window_s: float = 2.0     # 在多少秒内回落算毛刺（建议 1~3 秒）
    ):
        self.k = k
        self.b = b

        self.jump_abs = jump_abs
        self.jump_ratio = jump_ratio
        self.drop_abs = drop_abs
        self.drop_ratio = drop_ratio

        self.confirm_window_s = confirm_window_s
        self.confirm_need = confirm_need
        self.fast_consecutive = fast_consecutive

        self.smooth_window = smooth_window
        self._out_buf = deque(maxlen=smooth_window)

        # 状态
        self.state = self.STATE_STABLE
        self.stable_level = None  # 当前确认的“真实水平”
        self._last_output = None

        # 上升候选
        self.cand_up_level = None
        self._up_hits_ts = deque()
        self._up_consecutive = 0
        self._up_start_ts = None

        # 下降候选
        self.cand_down_level = None
        self._down_hits_ts = deque()
        self._down_consecutive = 0
        self._down_start_ts = None

        # 毛刺检测（突增后快速回落）
        self.spike_ratio = spike_ratio
        self.spike_return_ratio = spike_return_ratio
        self.spike_window_s = spike_window_s
        self._spike_start_ts = None
        self._spike_base_stable = None

    def _calibrate(self, raw: float) -> float:
        return self.k * raw + self.b

    def _smooth_out(self, v: float) -> float:
        self._out_buf.append(v)
        return sum(self._out_buf) / len(self._out_buf)

    def _is_suspected_up(self, v: float) -> bool:
        if self.stable_level is None:
            return False
        return (v - self.stable_level) >= self.jump_abs and v >= self.stable_level * self.jump_ratio

    def _is_suspected_down(self, v: float) -> bool:
        if self.stable_level is None:
            return False
        return (self.stable_level - v) >= self.drop_abs and v <= (self.stable_level / max(self.drop_ratio, 1e-6))

    def _is_big_spike(self, v: float) -> bool:
        # “突然提高好多倍”
        if self.stable_level is None:
            return False
        base = max(abs(self.stable_level), 1e-6)
        return v >= base * self.spike_ratio

    def _returned_near_stable(self, v: float) -> bool:
        # “又降回来了”
        if self._spike_base_stable is None:
            return False
        base = max(abs(self._spike_base_stable), 1e-6)
        return v <= base * self.spike_return_ratio

    def update(self, raw_viscosity: float) -> float | None:
        """
        输入：raw（/10 后）
        输出：处理后粘度（校准 + 异常策略 + 平滑）
        """
        v = self._calibrate(raw_viscosity)
        now = time.time()

        # 1) 初始化 stable
        if self.stable_level is None:
            self.stable_level = v
            out = self._smooth_out(self.stable_level)
            self._last_output = out
            return out

        # 2) 新增：突增->快速回落判毛刺（不进入候选、不抬高 stable）
        # 2.1 若当前没有处在“毛刺观察”，并且出现了超大突增，进入毛刺观察
        if self._spike_start_ts is None and self._is_big_spike(v):
            self._spike_start_ts = now
            self._spike_base_stable = self.stable_level
            # 输出保持 stable
            out = self._smooth_out(self.stable_level)
            self._last_output = out
            return out

        # 2.2 若处在“毛刺观察窗口”内，判断是否快速回落
        if self._spike_start_ts is not None:
            if (now - self._spike_start_ts) <= self.spike_window_s:
                # 在窗口内回落到 stable 附近 -> 判为毛刺，忽略这段变化
                if self._returned_near_stable(v):
                    # 结束毛刺观察
                    self._spike_start_ts = None
                    self._spike_base_stable = None
                    # 仍输出 stable
                    out = self._smooth_out(self.stable_level)
                    self._last_output = out
                    return out
                else:
                    # 还在窗口内但没回落：继续观察，不让它立刻抬高 stable
                    out = self._smooth_out(self.stable_level)
                    self._last_output = out
                    return out
            else:
                # 超过窗口仍未回落：说明可能是真实上升，退出毛刺观察，允许正常候选逻辑继续
                self._spike_start_ts = None
                self._spike_base_stable = None

        # 3) 状态机：STABLE
        if self.state == self.STATE_STABLE:
            # 发现疑似上升：进入上升候选
            if self._is_suspected_up(v):
                self.state = self.STATE_CANDIDATE_UP
                self.cand_up_level = v
                self._up_hits_ts.clear()
                self._up_consecutive = 1
                self._up_start_ts = now
                self._up_hits_ts.append(now)

                out = self._smooth_out(self.stable_level)
                self._last_output = out
                return out

            # 发现疑似下降：进入下降候选
            if self._is_suspected_down(v):
                self.state = self.STATE_CANDIDATE_DOWN
                self.cand_down_level = v
                self._down_hits_ts.clear()
                self._down_consecutive = 1
                self._down_start_ts = now
                self._down_hits_ts.append(now)

                out = self._smooth_out(self.stable_level)
                self._last_output = out
                return out

            # 正常稳定：慢跟随（避免噪声）
            self.stable_level = 0.8 * self.stable_level + 0.2 * v
            out = self._smooth_out(self.stable_level)
            self._last_output = out
            return out

        # 4) 状态机：候选上升
        if self.state == self.STATE_CANDIDATE_UP:
            if self._up_start_ts is None:
                self._up_start_ts = now

            if self._is_suspected_up(v):
                self._up_hits_ts.append(now)
                self._up_consecutive += 1
                # 候选水平跟随高值
                self.cand_up_level = 0.7 * (self.cand_up_level or v) + 0.3 * v
            else:
                self._up_consecutive = 0

            # 只保留窗口内命中
            while self._up_hits_ts and (now - self._up_hits_ts[0]) > self.confirm_window_s:
                self._up_hits_ts.popleft()
            hits = len(self._up_hits_ts)

            # 快速确认/频率确认
            if self._up_consecutive >= self.fast_consecutive or hits >= self.confirm_need:
                self.stable_level = self.cand_up_level if self.cand_up_level is not None else self.stable_level
                self.state = self.STATE_STABLE
                self._up_start_ts = None

                out = self._smooth_out(self.stable_level)
                self._last_output = out
                return out

            # 超时退出
            if (now - self._up_start_ts) > self.confirm_window_s:
                self.state = self.STATE_STABLE
                self.cand_up_level = None
                self._up_hits_ts.clear()
                self._up_consecutive = 0
                self._up_start_ts = None

                out = self._smooth_out(self.stable_level)
                self._last_output = out
                return out

            # 未确认：保持稳定输出
            out = self._smooth_out(self.stable_level)
            self._last_output = out
            return out

        # 5) 状态机：候选下降（新增）
        if self.state == self.STATE_CANDIDATE_DOWN:
            if self._down_start_ts is None:
                self._down_start_ts = now

            if self._is_suspected_down(v):
                self._down_hits_ts.append(now)
                self._down_consecutive += 1
                # 候选水平跟随低值
                self.cand_down_level = 0.7 * (self.cand_down_level or v) + 0.3 * v
            else:
                self._down_consecutive = 0

            # 只保留窗口内命中
            while self._down_hits_ts and (now - self._down_hits_ts[0]) > self.confirm_window_s:
                self._down_hits_ts.popleft()
            hits = len(self._down_hits_ts)

            # 快速确认/频率确认：满足则切回低位（你要的“stable 切回低位”）
            if self._down_consecutive >= self.fast_consecutive or hits >= self.confirm_need:
                self.stable_level = self.cand_down_level if self.cand_down_level is not None else self.stable_level
                self.state = self.STATE_STABLE
                self._down_start_ts = None

                out = self._smooth_out(self.stable_level)
                self._last_output = out
                return out

            # 超时退出
            if (now - self._down_start_ts) > self.confirm_window_s:
                self.state = self.STATE_STABLE
                self.cand_down_level = None
                self._down_hits_ts.clear()
                self._down_consecutive = 0
                self._down_start_ts = None

                out = self._smooth_out(self.stable_level)
                self._last_output = out
                return out

            # 未确认：保持稳定输出
            out = self._smooth_out(self.stable_level)
            self._last_output = out
            return out

        return self._last_output

# 上传数据 线程 秒点数据
class WorkerThread(QThread):

    update_ui_signal = pyqtSignal(int, int)
    send_mesage_signal = pyqtSignal(str, int, int)

    connect_status_signal = pyqtSignal(str)

    def __init__(self, file_path, well_info, point_1, point_2, jwt_token):
        super(WorkerThread, self).__init__()

        # # ? 第一步：强制设置无代理环境
        # self.force_no_proxy_environment()

        self.jwt_token = jwt_token
        self.well_info = well_info
        self.file_path = file_path
        self.point_1 = point_1
        self.point_2 = point_2

        self.websocket_connect_status = False   # websocket 的连接状态
        self.reconnect_timer = QTimer()  # 用于定时重连

        self.OpenWebSocket()

        self.running = True

        self.setup_logging()


        print('向服务器传输秒点数据的线程已启动')
        self.logger.info('向服务器传输秒点数据的线程已启动')
        # 初始化日志系统
        print(f'point_1: {self.point_1}, point_2: {self.point_2}')
        self.logger.info(f'point_1: {self.point_1}, point_2: {self.point_2}')

    def setup_logging(self):
        """设置日志记录"""
        # 创建日志目录（如果不存在）
        log_dir = "logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        # 设置日志文件名（包含井信息和时间）
        well_name = self.well_info.get('well_name', 'unknown') if isinstance(self.well_info, dict) else str(
            self.well_info)
        log_file = f"{log_dir}/{well_name}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

        # 配置日志
        self.logger = logging.getLogger(f"WorkerThread_{well_name}")
        self.logger.setLevel(logging.INFO)

        # 文件处理器（按大小轮转）
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.INFO)

        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        # 设置日志格式
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        # 添加处理器
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

        self.logger.info(f"日志系统初始化完成，日志文件: {log_file}")

    # 建立 websocket 连接
    def OpenWebSocket(self):
        # 初始化 QWebSocket
        self.websocket = QWebSocket()

        # ? 关键：为WebSocket实例单独设置无代理
        # self.websocket.setProxy(QNetworkProxy(QNetworkProxy.NoProxy))

        # 连接 WebSocket 信号
        self.websocket.connected.connect(self.on_connected)
        self.websocket.error.connect(self.on_error)
        self.websocket.disconnected.connect(self.on_disconnected)
        # 连接 textMessageReceived 信号以接收信息
        self.websocket.textMessageReceived.connect(self.on_message_received)
        API_url = 'ws://39.101.202.11/ws/SecondPointDataTransfer/'
        # API_url = 'ws://10.51.50.77:55555/ws/SecondPointDataTransfer/'
        # API_url = 'ws://10.51.50.99/ws/SecondPointDataTransfer/'
        # API_url = 'ws:/localhost:8000/ws/SecondPointDataTransfer/'

        # API_url = 'ws://127.0.0.1:8000/ws/SecondPointDataTransfer/'
        # 将字符串 URL 转换为 QUrl 对象
        url = QUrl(API_url)
        # websocket不支持自定义请求头，可以通过子协议字段携带token，后端连接前验证token，
        # 为了传递子协议，需要使用 QNetworkRequest 来设置 Sec-WebSocket-Protocol 头字段。
        request = QNetworkRequest(url)  # 创建 QNetworkRequest 对象

        # ? 关键修复：为请求明确设置代理属性
        # 方法1：设置属性明确不要代理
        # request.setAttribute(QNetworkRequest.HttpPipeliningAllowedAttribute, True)

        # 设置子协议（通过 Sec-WebSocket-Protocol 头字段）
        request.setRawHeader(b"Sec-WebSocket-Protocol", self.jwt_token.encode())
        # 打开 WebSocket 连接
        self.websocket.open(request)

    # 连接建立 触发
    def on_connected(self):
        print("WebSocket connected!")
        self.logger.info(f'WebSocket connected!')
        # 建议添加连接验证
        print(f"? 连接详情:")
        print(f"   本地地址: {self.websocket.localAddress().toString()}:{self.websocket.localPort()}")
        print(f"   远程地址: {self.websocket.peerAddress().toString()}:{self.websocket.peerPort()}")

        self.connect_status_signal.emit('WebSocket connected!')
        self.websocket_connect_status = True
        self.reconnect_timer.timeout.connect(self.reconnect)

    # 连接出错 触发
    def on_error(self, error):
        print(f"WebSocket error: {error}")
        self.logger.info(f"WebSocket error: {error}")

        self.connect_status_signal.emit('WebSocket error!')
        self.websocket_connect_status = False
        # 处理重连机制
        self.handle_reconnect()
    # 重连
    def handle_reconnect(self):
        """处理重连逻辑"""
        self.connect_status_signal.emit('WebSocket reconnect!')
        self.reconnect_timer.start(5 * 1000)  # 转换为毫秒
    def reconnect(self):
        """执行重连"""
        self.reconnect_timer.stop()  # 停止定时器
        self.OpenWebSocket()  # 重新连接
    # 连接断开 触发
    def on_disconnected(self):
        print("WebSocket disconnected!")
        self.logger.info("WebSocket disconnected!")

        self.connect_status_signal.emit('WebSocket disconnected!')
        self.websocket_connect_status = False
    # 接收消息 触发
    def on_message_received(self, message):
        msg = json.loads(message)
        status_code = msg['flag']
        print("status_code:" + str(status_code))
        self.logger.info("status_code:：" + str(status_code))

        # 返回状态码，1002说明发送成功，1004说明发送失败
        if status_code == 1002:
            now_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.send_mesage_signal.emit(now_time + f'秒点数据已传到服务器 ID：{self.point_1}-{self.point_2}', self.point_1, self.point_2)
            self.point_2 = self.point_2 - 5
            self.point_1 = self.point_2
            print('self.point_1 = self.point_2：', self.point_1, self.point_2)
            self.logger.info('self.point_1 = self.point_2：%d %d', self.point_1, self.point_2)

        if status_code == 1004:
            self.point_1 = self.point_1 - 1
    # 读取数据库文件
    def read_db(self, query_str):
        file_path = self.file_path
        conn = sqlite3.connect(file_path)
        print('数据库连接成功')
        # 创建游标对象
        cursor = conn.cursor()
        # 执行查询
        print(query_str)
        cursor.execute(query_str)
        # 获取结果
        rows = cursor.fetchall()
        # print(f'rows: {rows}')
        # 关闭游标
        cursor.close()
        # 关闭连接
        conn.close()
        return rows
    def run(self):
        try:
            while self.running:
                time.sleep(1)
                self.check_updates()
        except Exception as e:
            print(f'客户端出错了！！！ =={e}')
            self.running = False
            self.websocket_connect_status = False
            self.websocket.close()
            self.update_ui_signal.emit(self.point_1, self.point_2)
    # 检查数据库是否有数据更新
    def check_updates(self):
        max_recv = 600
        if self.point_1 == 0:
            # 第一次发送数据
            query_str1 = 'SELECT * FROM LogData ORDER BY id ASC LIMIT 1'
            query_str2 = 'SELECT * FROM LogData ORDER BY id DESC LIMIT 1'
            rows1 = self.read_db(query_str1)
            rows2 = self.read_db(query_str2)
            # 查询的数据为空，即表中没有数据
            if not rows1:
                self.point_1 = 0
                self.point_2 = 0
                print('数据表为空！！没有数据！')
                self.logger.info('数据表为空！！没有数据！')

            else:
                self.point_1 = rows1[0][0]
                self.point_2 = rows2[0][0]

                query_str = 'SELECT * FROM LogData WHERE ID BETWEEN {} AND {} ORDER BY ID ASC'.format(self.point_1, self.point_2)
                rows = self.read_db(query_str)

                query_str = "PRAGMA table_info(LogData)"
                row_column = self.read_db(query_str)
                column_names = [row[1] for row in row_column]  # row[1] 是字段名
                print(column_names)
                print(column_names[1:-3])

                df = pd.DataFrame(rows, columns=column_names)

                # 找出有viscosity和density数据的行
                viscosity_data = df[df['viscosity'].notna() & df['density'].notna()]

                # 找出有viscosity 或 density数据的行
                # viscosity_data = df[df['viscosity'].notna() | df['density'].notna()]

                # 对于每个有viscosity/density数据的system_time，更新其他行
                for _, row in viscosity_data.iterrows():
                    system_time = row['system_time']
                    mask = df['system_time'] == system_time

                    # 更新非viscosity/density列
                    for col in column_names[1:-3]:
                        if pd.notna(row[col]):
                            df.loc[mask, col] = row[col]

                    # 更新viscosity和density列
                    df.loc[mask, ['viscosity', 'density']] = [row['viscosity'], row['density']]
                print('_____________')
                # print(df.to_string())
                # 删除原始的有viscosity/density数据的行（这些行现在其他数据都是None）
                df = df[~((df['viscosity'].notna() & df['density'].notna() & df['Time'].isna()))]

                # df = df[~((df['viscosity'].notna() | df['density'].notna() & df['Time'].isna()))]

                # 重置索引
                df = df.reset_index(drop=True)
                df = df.replace({np.nan: None})
                rows = [row for row in df.values.tolist() if row[1] is not None]
                # print(rows)
                if rows:
                    # # 写入数据时可以修改
                    # with open('E:/data.txt', 'a') as f:  # 以追加模式打开文件
                    #     f.write('@@@' + str(rows) + '@@@')  # 写入数据
                    # 将时间转为字符串，避免json序列化出错
                    for item in rows:
                        for j in range(len(item)):
                            if type(item[j]) == datetime.datetime:
                                item[j] = str(item[j])
                        # 每条数据前都插入井信息
                        item.insert(0, self.well_info)
                    send_data = rows
                    json_data = json.dumps(send_data)
                    self.websocket.sendTextMessage(json_data)
                    # 调用 WebSocket 的刷新方法，确保消息立即发送
                    self.websocket.flush()
        else:
            # point_1 = self.point_2 说明没有数据更新
            if self.point_1 == self.point_2:
                print('数据库中没有数据更新')
                self.logger.info('数据库中没有数据更新')

                query_str = 'SELECT * FROM LogData ORDER BY id DESC LIMIT 1'  # 查询数据库中最后一条数据
                rows = self.read_db(query_str)
                self.point_2 = rows[0][0]
            # point_1 ！= self.point_2 说明有数据更新
            if self.point_1 != self.point_2:
                print('数据库中有数据更新！')
                self.logger.info(f'数据库中有数据更新！point_1={self.point_1},point_2={self.point_2}')

                # self.point_1 = self.point_1 - 5
                # 发送数据给后端服务器
                query_str = 'SELECT * FROM LogData WHERE ID BETWEEN {} AND {} ORDER BY ID ASC'.format(self.point_1, self.point_2)
                rows = self.read_db(query_str)

                query_str = "PRAGMA table_info(LogData)"
                row_column = self.read_db(query_str)
                column_names = [row[1] for row in row_column]  # row[1] 是字段名
                print(column_names)

                df = pd.DataFrame(rows, columns=column_names)

                # 找出有viscosity和density数据的行
                viscosity_data = df[df['viscosity'].notna() & df['density'].notna()]

                # 对于每个有viscosity/density数据的system_time，更新其他行
                for _, row in viscosity_data.iterrows():
                    system_time = row['system_time']
                    mask = df['system_time'] == system_time

                    # 更新非viscosity/density列
                    for col in column_names[1:-3]:
                        if pd.notna(row[col]):
                            df.loc[mask, col] = row[col]

                    # 更新viscosity和density列
                    df.loc[mask, ['viscosity', 'density']] = [row['viscosity'], row['density']]

                # 删除原始的有viscosity/density数据的行（这些行现在其他数据都是None）
                df = df[~((df['viscosity'].notna() & df['density'].notna() & df['Time'].isna()))]
                # 重置索引
                df = df.reset_index(drop=True)
                df = df.replace({np.nan: None})
                rows = [row for row in df.values.tolist() if row[1] is not None]
                if rows:
                    # # 写入数据时可以修改
                    # with open('E:/data.txt', 'a') as f:  # 以追加模式打开文件
                    #     f.write('@@@' + str(rows) + '@@@\n\n\n')  # 写入数据

                    for item in rows:  # 将时间转为字符串，避免json序列化出错
                        for j in range(len(item)):
                            if type(item[j]) == datetime.datetime:
                                item[j] = str(item[j])
                        # 每条数据前都插入井信息
                        item.insert(0, self.well_info)
                    send_data = rows
                    json_data = json.dumps(send_data)
                    self.websocket.sendTextMessage(json_data)
                    # 调用 WebSocket 的刷新方法，确保消息立即发送
                    self.websocket.flush()
    def stop(self):
        """停止线程"""
        self.running = False
        if self.websocket_connect_status:
            self.websocket.close()
        print('线程已停止!')
        self.logger.info('线程已停止!')

# 接收数据 线程 秒点数据
class ReceiverThread(QThread):
    update_textEdit = pyqtSignal(str)
    update_textEdit_2 = pyqtSignal(str)

    def __init__(self, cur_well, cur_frac_num, cur_layer, cur_period, field_name, measuring_truck, field_index, port_name):
        super(ReceiverThread, self).__init__()
        self.cur_well = cur_well
        self.cur_frac_num = cur_frac_num
        self.cur_layer = cur_layer
        self.cur_period = cur_period
        # 字段名称
        self.field_name = field_name
        # 仪表车厂家
        self.measuring_truck = measuring_truck
        self.field_index = field_index  # 只针对三一重工使用
        self.port_name = port_name
        self.running = True
        print('接收数据线程已启动')

    def save_data(self, field_name, data, field_num):
        file_name = self.cur_well + '第' + self.cur_frac_num + '次压裂' + self.cur_layer + '第' + self.cur_period + '段'
        temp_file_path = 'C:/a_transmission_data/' + self.cur_well + '/' + file_name + '.db'
        # temp_file_path = 'D:/a_transmission_data/' + self.cur_well + '/' + file_name + '.db'
        cur_time = datetime.datetime.now()
        system_time = cur_time.strftime("%H:%M:%S")
        data = data + (system_time,)
        with _get_db_write_lock(temp_file_path):
            conn = sqlite3.connect(temp_file_path)
            conn.execute('PRAGMA journal_mode=WAL')
            cursor = conn.cursor()
            placeholders = ", ".join(["?"] * (len(field_name) + 2))
            columns = ','.join(field_name)
            print(data)
            print((len(field_name) + 2))
            if len(data) == len(field_name) + 2:
                cursor.execute(f'INSERT INTO LogData (Time,{columns},system_time) VALUES ({placeholders})', data)
                conn.commit()
            cursor.close()
            conn.close()

    def save_data_copy(self, field_name, data, field_num):
        print('我执行了2')
        print(field_num)
        file_name = self.cur_well + '第' + self.cur_frac_num + '次压裂' + self.cur_layer + '第' + self.cur_period + '段'
        temp_file_path = 'C:/a_transmission_data/' + self.cur_well + '/' + file_name + '.db'
        # temp_file_path = 'D:/a_transmission_data/' + self.cur_well + '/' + file_name + '.db'
        cur_time = datetime.datetime.now()
        system_time = cur_time.strftime("%H:%M:%S")
        data = data + (system_time,)
        with _get_db_write_lock(temp_file_path):
            conn = sqlite3.connect(temp_file_path)
            conn.execute('PRAGMA journal_mode=WAL')
            cursor = conn.cursor()
            columns = ','.join(field_name)
            placeholders = ", ".join(["?"] * (len(field_name) + 2))
            field_num = field_num + 1
            if len(data) == field_num:
                cursor.execute(f'INSERT INTO LogData (Time,{columns},system_time) VALUES ({placeholders})', data)
                conn.commit()
                print(f'{data[0]}秒数据已保存到数据库文件中')
            cursor.close()
            conn.close()
        self.update_textEdit.emit(data[0])

    def save_data_31(self, field_name, data, field_num, field_index):
        file_name = self.cur_well + '第' + self.cur_frac_num + '次压裂' + self.cur_layer + '第' + self.cur_period + '段'
        temp_file_path = 'C:/a_transmission_data/' + self.cur_well + '/' + file_name + '.db'
        # temp_file_path = 'D:/a_transmission_data/' + self.cur_well + '/' + file_name + '.db'

        cur_time = datetime.datetime.now()
        current_time = cur_time.strftime("%Y-%m-%d %H:%M:%S")
        data_ = [current_time]
        for i in field_index:
            try:
                value = data[i - 1] if (i - 1) < len(data) else 0
                data_.append(value)
            except IndexError:
                print(f"警告: 数据索引 {i - 1} 超出范围(数据长度={len(data)})，已使用默认值0")
                data_.append(0)
        current_time_ = cur_time.strftime("%H:%M:%S")
        data_.append(current_time_)
        data_end = tuple(data_)
        field_num = field_num + 1
        with _get_db_write_lock(temp_file_path):
            conn = sqlite3.connect(temp_file_path)
            conn.execute('PRAGMA journal_mode=WAL')
            cursor = conn.cursor()
            columns = ','.join(field_name)
            placeholders = ", ".join(["?"] * (len(field_name)+2))
            if len(data_end) == field_num:
                cursor.execute(f'INSERT INTO LogData (Time,{columns},system_time) VALUES ({placeholders})', data_end)
                conn.commit()
                print(f'{data_end[0]}秒数据已保存到数据库文件中')
            cursor.close()
            conn.close()
        self.update_textEdit.emit(data_end[0])

    def run(self):
        # 配置串口参数
        # port = 'COM6'  # 请根据实际情况修改串口号
        port = self.port_name  # 请根据实际情况修改串口号
        baudrate = 9600  # 波特率
        timeout = 1  # 超时设置
        # 设置数据位、校验位和停止位
        data_bits = 8  # 数据位（5, 6, 7, 或 8）
        parity = serial.PARITY_NONE  # 校验位（无校验）
        stop_bits = serial.STOPBITS_ONE  # 停止位（1位）
        # 暂存字符串 处理串口发送数据的异常
        temp_str = ''
        # 发送的字段数量 还需要加上时间字段，字段数量+1
        field_num = len(self.field_name) + 1
        # 文件路径
        file_path1 = f'C:/a_transmission_data/{self.cur_well}/{self.cur_well}第{self.cur_frac_num}次压裂{self.cur_layer}第{self.cur_period}段_AllData.txt'
        # file_path1 = f'D:/a_transmission_data/{self.cur_well}/{self.cur_well}第{self.cur_frac_num}次压裂{self.cur_layer}第{self.cur_period}段_AllData.txt'

        # 字段的索引值 只针对 仪表车厂家为 三一重工 时使用
        field_index = self.field_index

        buffer = ''   # 缓存数据
        try:
            # 初始化串口
            ser = serial.Serial(port, baudrate, timeout=timeout, bytesize=data_bits, parity=parity, stopbits=stop_bits)
            print(f"打开串口 {port}，波特率 {baudrate}")
            while self.running:
                # 在接收串口数据时 处理异常
                if self.measuring_truck == '杰瑞':
                    '''  
                    杰瑞的数据格式：要求发送端发送指定字段，客户端根据发送端接收，中间用逗号分隔
                    '''
                    # 尝试读取数据
                    if ser.in_waiting > 0:  # 检查是否有数据等待接收
                        raw_data = ser.read(ser.in_waiting)  # 读取所有等待的数据
                        data = raw_data.decode('utf-8')  # 解码
                        # 将收到的数据展示到状态栏
                        # self.update_textEdit_2.emit(f'数据：{data}')
                        # 写入数据
                        cur_time = datetime.datetime.now()
                        current_time = cur_time.strftime("%H:%M:%S")
                        with open(file_path1, 'a') as f:  # 以追加模式打开文件
                            f.write(current_time + '：@@@' + data + '@@@' + '\n')  # 写入数据
                        # 加入到缓冲区
                        buffer += data
                        lines = buffer.splitlines(keepends=True)  # 保留末尾的换行符，默认是False
                        # 除了最后一行，最后一行数据可能不完整
                        for line in lines[:-1]:
                            line = line.strip()
                            if line:
                                print(f"收到数据: {line}")
                                data_list = line.split(',')
                                # 将收到的数据展示到状态栏
                                print(field_num)
                                self.update_textEdit_2.emit(f'接收到数据：{data_list}')
                                print(len(data_list))
                                print(field_num)
                                print(len(self.field_name))
                                print(self.field_name)
                                if len(data_list) == field_num:
                                    print('我执行了1')
                                    print(data_list)
                                    # # # 处理 data[0]，使其只保留时间部分
                                    # if " " in data_list[0].strip():  # 检查是否包含日期部分（有空格）
                                    #     data_list[0] = data_list[0].strip().split()[1]  # 分割并取时间部分
                                    # else:
                                    #     data_list[0] = data_list[0].strip()  # 否则直接去除前后空格
                                    # 保存到数据库
                                    self.save_data(self.field_name, tuple(data_list), field_num)
                                else:
                                    self.update_textEdit_2.emit('发送端的数据个数与选择的字段不匹配！')

                        buffer = lines[-1] if lines else ""
                    else:
                        time.sleep(1)  # 需要设置 time.sleep()
                elif self.measuring_truck == '三一重工':
                    '''  
                    三一重工的数据格式：发送全部20个数据，客户端根据选择接收，中间可能用空格或者逗号分隔
                    '''
                    # 尝试读取数据
                    if ser.in_waiting > 0:  # 检查是否有数据等待接收
                        raw_data = ser.read(ser.in_waiting)  # 读取所有等待的数据
                        data = raw_data.decode('utf-8')  # 解码
                        cur_time = datetime.datetime.now()
                        current_time = cur_time.strftime("%H:%M:%S")
                        # 写入数据时可以修改
                        with open(file_path1, 'a') as f:  # 以追加模式打开文件
                            f.write(current_time + '：@@@' + data + '@@@')  # 写入数据
                        # data_list = data.split(' ')
                        # # 将收到的数据展示到状态栏
                        self.update_textEdit_2.emit(f'接收到数据：{data}')
                        # print(field_num)
                        # self.save_data_31(self.field_name, tuple(data_list), field_num, field_index)
                        # 加入到缓冲区
                        buffer += data
                        lines = buffer.splitlines(keepends=True)  # 保留末尾的换行符，默认是False
                        # 除了最后一行，最后一行数据可能不完整
                        for line in lines[:-1]:
                            line = line.strip()
                            if line:
                                print(f"收到数据: {line}")
                                data_list = line.split(',')
                                # 将收到的数据展示到状态栏
                                print(field_num)
                                self.update_textEdit_2.emit(f'接收到数据：{data_list}')
                                print(len(data_list))
                                print(field_num)
                                print(len(self.field_name))
                                print(self.field_name)
                                self.save_data_31(self.field_name, tuple(data_list), field_num, field_index)

                        buffer = lines[-1] if lines else ""
                    else:
                        time.sleep(0.1)  # 需要设置 time.sleep() 否则获取的数据会是 一位一位的

                    # # 尝试读取数据  仪表厂家 四机厂
                    # if ser.in_waiting > 0:  # 检查是否有数据等待接收
                    #     raw_data = ser.read(ser.in_waiting)  # 读取所有等待的数据
                    #     data = raw_data.decode('utf-8')  # 解码
                    #     # 加入到缓冲区
                    #     buffer += data
                    #     lines = buffer.splitlines(keepends=True)  # 保留末尾的换行符，默认是False
                    #     # 除了最后一行，最后一行数据可能不完整
                    #     for line in lines[:-1]:
                    #         line = line.strip()
                    #         if line:
                    #             print(f"收到数据: {line}")
                    #             data_list = line.split(' ')
                    #             new_list = [data_list[0] + ' ' + data_list[1]] + data_list[2:]
                    #             print(f"收到数据: {new_list}")
                    #     buffer = lines[-1] if lines else ""
                    # else:
                    #     time.sleep(0.1)  # 需要设置 time.sleep()
                elif self.measuring_truck == '宏华':
                    # 尝试读取数据
                    if ser.in_waiting > 0:  # 检查是否有数据等待接收
                        raw_data = ser.read(ser.in_waiting)  # 读取所有等待的数据
                        data = raw_data.decode('utf-8')  # 解码
                        # 将收到的数据展示到状态栏
                        # self.update_textEdit_2.emit(f'数据：{data}')
                        # 写入数据
                        cur_time = datetime.datetime.now()
                        current_time = cur_time.strftime("%H:%M:%S")
                        with open(file_path1, 'a') as f:  # 以追加模式打开文件
                            f.write(current_time + '：@@@' + data + '@@@' + '\n')  # 写入数据

                        # 加入到缓冲区
                        buffer += data
                        lines = buffer.splitlines(keepends=True)  # 保留末尾的换行符，默认是False
                        # 除了最后一行，最后一行数据可能不完整
                        for line in lines[:-1]:
                            line = line.strip()
                            if line:
                                print(f"收到数据: {line}")
                                data_list = line.split(',')
                                # 将收到的数据展示到状态栏
                                self.update_textEdit_2.emit(f'接收到数据：{data_list}')
                                if len(data_list) == field_num:
                                    # 保存到数据库
                                    self.save_data(self.field_name, tuple(data_list), field_num)
                        buffer = lines[-1] if lines else ""
                    else:
                        time.sleep(0.1)  # 需要设置 time.sleep()
                elif self.measuring_truck == '四机厂':
                    '''
                    四机厂的数据格式为：2025-11-04 11:18:30 12.70 3.2 4.6 等
                    '''
                    # 尝试读取数据
                    if ser.in_waiting > 0:  # 检查是否有数据等待接收
                        raw_data = ser.read(ser.in_waiting)  # 读取所有等待的数据
                        data = raw_data.decode('utf-8')  # 解码
                        # 写入数据
                        cur_time = datetime.datetime.now()
                        current_time = cur_time.strftime("%H:%M:%S")
                        with open(file_path1, 'a') as f:  # 以追加模式打开文件
                            f.write(current_time + '：@@@' + data + '@@@' + '\n')  # 写入数据
                        # 加入到缓冲区
                        buffer += data
                        lines = buffer.splitlines(keepends=True)  # 保留末尾的换行符，默认是False
                        # 除了最后一行，最后一行数据可能不完整
                        for line in lines[:-1]:
                            line = line.strip()
                            if line:
                                print(f"收到数据: {line}")
                                data_list = line.split(' ')
                                # 将收到的数据展示到状态栏
                                print(field_num)
                                print(len(data_list))
                                print(field_num)
                                print(len(self.field_name))
                                print(self.field_name)
                                new_list = [data_list[0] + ' ' + data_list[1]] + data_list[2:]
                                print(f"收到数据: {new_list}")
                                self.update_textEdit_2.emit(f'接收到数据：{new_list}')
                                if len(new_list) == field_num:
                                    print('我执行了1')
                                    print(new_list)
                                    # 保存到数据库
                                    self.save_data(self.field_name, tuple(new_list), field_num)
                                else:
                                    self.update_textEdit_2.emit('发送端的数据个数与选择的字段不匹配！')

                        buffer = lines[-1] if lines else ""
                    else:
                        time.sleep(1)  # 需要设置 time.sleep()
                else:
                    pass
        except serial.SerialException as e:
            print(f"串口错误: {e}")
            self.update_textEdit_2.emit(f"打开秒点数据串口出错: {e}")
        except KeyboardInterrupt:
            print("程序被用户终止。")
        finally:
            if ser.is_open:
                ser.close()  # 关闭串口
                print(f"串口 {port} 已关闭。")
                self.update_textEdit_2.emit(f"串口 {port} 已关闭。")

    def stop(self):
        self.running = False
# 接收数据线程 粘度、密度数据
class ReceiverViscosityThread(QThread):

    update_textEdit = pyqtSignal(str)

    def __init__(self, file_path, port_name, liquid_style):
        super(ReceiverViscosityThread, self).__init__()

        self.file_path = file_path
        self.port_name = port_name
        self.liquid_style = liquid_style
        self.get_k_b()
        # self.viscosity_processor = ViscosityProcessor(
        #     k=self.k,  # get_k_b() 设置的 k
        #     b=self.b,  # get_k_b() 设置的 b
        #     spike_ratio_max=0.3,  # 单次变化>30% 视为异常，可根据需要调整
        #     smooth_window=5  # 平滑窗口大小，可根据需要调整
        # )
        self.viscosity_filter = ViscosityStateFilter(
            k=self.k,
            b=self.b,
            jump_abs=8.0,
            jump_ratio=1.6,
            confirm_window_s=8,  # 8秒窗口
            confirm_need=7,  # 8秒内 >=5 次命中认为真实上升
            fast_consecutive=6,  # 连续3次命中直接确认
            smooth_window=5
        )
        self.running = True
        print('接收数据线程已启动')

    # CRC计算函数
    def calculate_crc(self, data):
        crc16 = crcmod.mkCrcFun(0x18005, rev=True, initCrc=0xFFFF, xorOut=0x0000)
        crc = crc16(bytes(data))
        return crc.to_bytes(2, byteorder='little')

    def get_k_b(self):
        config = configparser.ConfigParser()
        try:
            config.read('config.ini', encoding='utf-8')
        except UnicodeDecodeError:
            config.read('config.ini', encoding='gbk')
        if 'calibration_parameter' not in config:
            self.k = 1.0
            self.b = 0.3
            return
        params = config['calibration_parameter']
        liquid_style_key = ''
        if self.liquid_style == '滑溜水':
            liquid_style_key = "slippery_water"
        elif self.liquid_style == '胍胶':
            liquid_style_key = "gua_gum"
        elif self.liquid_style == '交联胶':
            liquid_style_key = "jiaolian_gum"
        elif self.liquid_style == '线性胶':
            liquid_style_key = "xianxing_gum"
        elif self.liquid_style == '盐酸':
            liquid_style_key = "muriatic_acid"
        else:
            if 'liquid_list' in config and 'liquid_styles' in config['liquid_list']:
                liquid_str = config['liquid_list']['liquid_styles']
                liquid_names = [s.strip() for s in liquid_str.split(',') if s.strip()]
                try:
                    idx = liquid_names.index(self.liquid_style)
                    liquid_style_key = 'liquid_' + str(idx + 1)
                except ValueError:
                    pass
        if liquid_style_key and liquid_style_key in params:
            try:
                d = json.loads(params[liquid_style_key])
                self.k = float(d.get('k', 1))
                self.b = float(d.get('b', 0.3))
            except Exception:
                d = json.loads(params.get('default', '{"k":1, "b":0.3}'))
                self.k = float(d.get('k', 1))
                self.b = float(d.get('b', 0.3))
        else:
            d = json.loads(params.get('default', '{"k":1, "b":0.3}'))
            self.k = float(d.get('k', 1))
            self.b = float(d.get('b', 0.3))

    def _ensure_raw_viscosity_column(self, conn):
        """
        确保 LogData 表存在 raw_viscosity 列（兼容旧 db）。
        """
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(LogData)")
        cols = [r[1] for r in cursor.fetchall()]
        if "raw_viscosity" not in cols:
            cursor.execute("ALTER TABLE LogData ADD COLUMN raw_viscosity TEXT")
            conn.commit()
        cursor.close()

    def save_data(self, data):
        """
        data = (raw_viscosity_2, viscosity_2, density_2, system_time)
        其中 raw_viscosity_2 / viscosity_2 / density_2 建议为两位小数字符串，例如 "21.24"
        """
        temp_file_path = self.file_path
        with _get_db_write_lock(temp_file_path):
            conn = sqlite3.connect(temp_file_path)
            conn.execute('PRAGMA journal_mode=WAL')

            # 新增：兼容旧 db，确保列存在
            self._ensure_raw_viscosity_column(conn)

            cursor = conn.cursor()

            # 新增 raw_viscosity 列，并强制 TEXT 入库
            cursor.execute(
                'INSERT INTO LogData (raw_viscosity, viscosity, density, system_time) '
                'VALUES (CAST(? AS TEXT), CAST(? AS TEXT), CAST(? AS TEXT), ?)',
                data
            )

            conn.commit()
            cursor.close()
            conn.close()

    def save_data_copy(self, data):
        temp_file_path = self.file_path
        with _get_db_write_lock(temp_file_path):
            conn = sqlite3.connect(temp_file_path)
            conn.execute('PRAGMA journal_mode=WAL')
            cursor = conn.cursor()
            placeholders = ", ".join(["?"] * (len(data)))
            cursor.execute(f'INSERT INTO ViscosityData (Time,Viscosity,density) VALUES ({placeholders})', data)
            conn.commit()
            cursor.close()
            conn.close()
        print(f'{data[0]}秒的粘/密度数据已保存到数据库文件中')
        self.update_textEdit.emit(f'{data[0]}秒的粘/密度数据已保存到数据库文件中')

    def _read_exact(self, ser, n, timeout_s=1.2):
        """读取恰好 n 字节；超时返回 None。"""
        end = time.time() + timeout_s
        buf = bytearray()
        while len(buf) < n and time.time() < end and self.running:
            chunk = ser.read(n - len(buf))
            if chunk:
                buf.extend(chunk)
            else:
                time.sleep(0.002)
        return bytes(buf) if len(buf) == n else None

    def _crc16_modbus(self, data: bytes) -> bytes:
        """返回 2 字节 CRC（little-endian）。"""
        crc16 = crcmod.mkCrcFun(0x18005, rev=True, initCrc=0xFFFF, xorOut=0x0000)
        crc = crc16(data)
        return crc.to_bytes(2, byteorder='little')

    def run(self):
        # 配置串口参数
        # port = 'COM6'  # 请根据实际情况修改串口号
        port = self.port_name  # 请根据实际情况修改串口号
        baudrate = 9600  # 波特率
        timeout = 1  # 超时设置
        # 设置数据位、校验位和停止位
        data_bits = 8  # 数据位（5, 6, 7, 或 8）
        parity = serial.PARITY_NONE  # 校验位（无校验）
        stop_bits = serial.STOPBITS_ONE  # 停止位（1位）
        file_path1 = f'{self.file_path.split(".")[0]}_viscosity_AllData.txt'

        try:
            # 初始化串口
            ser = serial.Serial(port, baudrate, timeout=timeout, bytesize=data_bits, parity=parity, stopbits=stop_bits)
            print(f"打开串口 {port}，波特率 {baudrate}")
            # --------------------------
            # 构造请求帧（示例：读取设备号1的数据）
            # --------------------------
            device_id = 0x01  # 设备地址
            func_code = 0x03  # 功能码（读取保持寄存器）
            start_addr = 0x0001  # 起始地址（寄存器地址）
            reg_count = 0x0005  # 数据结束地址

            # 构建请求数据帧（无CRC）
            request_data = [
                device_id,
                func_code,
                (start_addr >> 8) & 0xFF, start_addr & 0xFF,
                (reg_count >> 8) & 0xFF, reg_count & 0xFF
            ]
            # 计算CRC并添加到请求帧
            crc = self.calculate_crc(request_data)
            request_frame = bytes(request_data) + crc
            # 每秒采集 1 条
            poll_interval_s = 1.0

            # 启动时清一次缓冲，避免残留脏数据影响首帧
            try:
                ser.reset_input_buffer()
                ser.reset_output_buffer()
            except Exception:
                pass

            last_err_ts = 0.0  # 限制错误刷屏（最多每秒提示1次）

            while self.running:
                time.sleep(poll_interval_s)
                try:
                    data_list = []

                    # 每轮发送前清输入缓冲，避免上一轮残留导致错帧（物理串口很常见）
                    try:
                        ser.reset_input_buffer()
                    except Exception:
                        pass

                    # 发送请求帧
                    ser.write(request_frame)

                    # ===== 按 Modbus RTU 响应帧读取：先读 3 字节头 =====
                    # header = [addr][func][byte_count]
                    header = self._read_exact(ser, 3, timeout_s=1.2)
                    if not header:
                        raise TimeoutError("未收到响应数据")

                    resp_device, resp_func, byte_count = header[0], header[1], header[2]

                    # 设备地址不匹配
                    if resp_device != device_id:
                        raise ValueError("响应设备号不匹配")

                    # Modbus 异常响应：func = func|0x80，后面 1 字节异常码 + CRC2
                    if resp_func == (func_code | 0x80):
                        _ = self._read_exact(ser, 3, timeout_s=0.8)
                        raise ValueError("设备返回异常响应")

                    # 功能码不匹配
                    if resp_func != func_code:
                        raise ValueError("响应功能码不匹配")

                    # 你请求的是 5 个寄存器 -> 10 字节数据
                    if byte_count != 10:
                        # 把剩余数据读掉（byte_count + CRC2）避免污染下一帧
                        _ = self._read_exact(ser, byte_count + 2, timeout_s=0.5)
                        raise ValueError(f"响应字节数异常: {byte_count}")

                    # 再读 data(10) + CRC(2)
                    payload = self._read_exact(ser, byte_count + 2, timeout_s=1.2)
                    if not payload:
                        raise TimeoutError("响应数据读取超时")

                    data_part = payload[:byte_count]
                    crc_recv = payload[byte_count:byte_count + 2]

                    # CRC 校验（覆盖 header + data）
                    crc_calc = self._crc16_modbus(header + data_part)
                    if crc_recv != crc_calc:
                        raise ValueError("CRC校验失败")

                    # ===== 解析：保持与你原逻辑兼容 =====
                    # data_part 前4字节：粘度(2) + 密度(2)（big-endian）
                    viscosity_bytes = data_part[0:2]
                    density_bytes = data_part[2:4]

                    raw_viscosity = int.from_bytes(viscosity_bytes, byteorder='big') / 10.0
                    print(f'粘度原始: {raw_viscosity}')

                    # smooth_viscosity = self.viscosity_processor.process_raw_value(raw_viscosity)
                    smooth_viscosity = self.viscosity_filter.update(raw_viscosity)
                    # 新增规则：处理后的粘度若为负，强制转为 0
                    if smooth_viscosity is not None and smooth_viscosity < 0:
                        smooth_viscosity = 0.0
                    print(f'粘度处理后(平滑): {smooth_viscosity}')

                    density = int.from_bytes(density_bytes, byteorder='big') / 10000.0

                    # 两位小数（准备入库）
                    raw_viscosity_2 = "{:.2f}".format(raw_viscosity)
                    viscosity_2 = "{:.2f}".format(smooth_viscosity)
                    density_2 = "{:.2f}".format(density)

                    system_time = datetime.datetime.now().strftime("%H:%M:%S")

                    # 注意顺序：raw_viscosity, viscosity, density, system_time
                    data_list.append(raw_viscosity_2)
                    data_list.append(viscosity_2)
                    data_list.append(density_2)
                    data_list.append(system_time)

                    print(data_list)
                    self.save_data(tuple(data_list))

                    self.update_textEdit.emit(f"粘度: {smooth_viscosity:.2f} mPa \u00B7 s")
                    # 修改后的状态栏输出：粘度在前 + 对应的 system_time（HH:MM:SS）
                    # self.update_textEdit.emit(f"粘度: {smooth_viscosity:.2f} mPa?s  {system_time}")

                except Exception as e:
                    # 控制刷屏：最多每秒提示 1 次
                    now = time.time()
                    if now - last_err_ts >= 1.0:
                        last_err_ts = now
                        self.update_textEdit.emit(f"通信异常: {str(e)}")
            # while self.running:
            #     time.sleep(0.01)
            #     try:
            #         data_list = []
            #
            #         # 发送请求
            #         ser.write(request_frame)
            #         # self.update_textEdit.emit(f"发送请求: {request_frame.hex().upper()}")
            #
            #         # 等待并读取响应
            #         response = ser.read(1024)  # 读取最多1024字节
            #         if not response:
            #             # self.update_textEdit.emit("未收到响应数据")
            #             raise TimeoutError("未收到响应数据")
            #         # self.update_textEdit.emit(f"接收响应: {response.hex().upper()}")
            #         # --------------------------
            #         # 解析响应数据（根据示例格式）
            #         # --------------------------
            #         # 基础校验
            #         if len(response) < 9:
            #             self.update_textEdit.emit("响应数据长度不足")
            #             raise ValueError("响应数据长度不足")
            #         # 校验设备号和功能码
            #         resp_device = response[0]
            #         resp_func = response[1]
            #         if resp_device != device_id or resp_func != func_code:
            #             self.update_textEdit.emit("响应设备号或功能码不匹配")
            #             raise ValueError("响应设备号或功能码不匹配")
            #
            #         # 提取数据部分（根据示例）
            #         viscosity_bytes = response[3:5]  # 粘度（2字节）
            #         density_bytes = response[5:7]  # 密度（2字节）
            #
            #         # 1）从字节得到原始粘度（这里仍然 /10，保持和原来一致）
            #         raw_viscosity = int.from_bytes(viscosity_bytes, byteorder='big') / 10.0
            #         print(f'粘度原始: {raw_viscosity}')
            #         # 2）交给处理器：再校准 + 去异常 + 平滑
            #         smooth_viscosity = self.viscosity_processor.process_raw_value(raw_viscosity)
            #         print(f'粘度处理后(平滑): {smooth_viscosity}')
            #         # 如需展示公式，可以只展示最基础的线性公式
            #         formula_str = f"{self.k} * {raw_viscosity} + {self.b}"
            #         print(f'粘度校公式: {formula_str}')
            #         # 3）密度保持原有逻辑
            #         density = int.from_bytes(density_bytes, byteorder='big') / 10000.0
            #         # 4）写入列表：使用平滑后的粘度值
            #         data_list.append(smooth_viscosity)
            #         data_list.append(density)
            #         # import random
            #         # data_list = [round(random.uniform(100, 120), 2) for _ in range(2)]
            #         cur_time = datetime.datetime.now()
            #         system_time = cur_time.strftime("%H:%M:%S")
            #         data_list.append(system_time)
            #         print(data_list)
            #         self.save_data(tuple(data_list))
            #         # self.save_data_copy(tuple(data_list))
            #         # self.save_data(tuple(data_list))
            #         # 打印结果
            #         # self.update_textEdit.emit(f"数据解析结果:")
            #         # self.update_textEdit.emit(f"设备号: {resp_device:02X}")
            #         # self.update_textEdit.emit(f"粘度: {true_viscosity:.2f} mPa?s")
            #         self.update_textEdit.emit(f"粘度: {smooth_viscosity:.2f} mPa?s")
            #         # self.update_textEdit.emit(f"")
            #     except Exception as e:
            #         self.update_textEdit.emit(f"通信正常: {str(e)}")
        except serial.SerialException as e:
            self.update_textEdit.emit(f'打开黏/密度串口错误: {e}')
            print(f"串口错误: {e}")
        except KeyboardInterrupt:
            print("程序被用户终止。")
        finally:
            if ser.is_open:
                ser.close()  # 关闭串口
                print(f"串口 {port} 已关闭。")
                self.update_textEdit.emit(f"串口 {port} 已关闭。")

    def stop(self):
        self.running = False
# 上传数据 线程 粘度、密度数据
class UploadViscosityThread(QThread):

    update_ui_signal = pyqtSignal(int, int)
    send_mesage_signal = pyqtSignal(str, int, int)
    connect_status_signal = pyqtSignal(str)

    def __init__(self, file_path, well_info, viscosity_point_1, viscosity_point_2, jwt_token):
        super(UploadViscosityThread, self).__init__()

        self.jwt_token = jwt_token
        self.OpenWebSocket()
        self.websocket_connect_status = False   # websocket 的连接状态
        self.well_info = well_info
        self.file_path = file_path
        self.viscosity_point_1 = viscosity_point_1
        self.viscosity_point_2 = viscosity_point_2

        self.running = True
        print('向服务器传输秒点数据的线程已启动')
        print(f'point_1: {self.viscosity_point_1}, point_2: {self.viscosity_point_2}')

    # 建立 websocket 连接
    def OpenWebSocket(self):
        # 初始化 QWebSocket
        self.websocket = QWebSocket()
        # 连接 WebSocket 信号
        self.websocket.connected.connect(self.on_connected)
        self.websocket.error.connect(self.on_error)
        self.websocket.disconnected.connect(self.on_disconnected)
        # 连接 textMessageReceived 信号以接收信息
        self.websocket.textMessageReceived.connect(self.on_message_received)
        API_url = 'ws://39.101.202.11/ws/ViscosityDataTransfer/'
        # API_url = 'ws://10.51.50.77:55555/ws/ViscosityDataTransfer/'
        # API_url = 'ws://10.51.50.99/ws/ViscosityDataTransfer/'
        # API_url = 'ws://localhost:8000/ws/ViscosityDataTransfer/'
        # 将字符串 URL 转换为 QUrl 对象
        url = QUrl(API_url)
        # websocket不支持自定义请求头，可以通过子协议字段携带token，后端连接前验证token，
        # 为了传递子协议，需要使用 QNetworkRequest 来设置 Sec-WebSocket-Protocol 头字段。
        request = QNetworkRequest(url)  # 创建 QNetworkRequest 对象
        # 设置子协议（通过 Sec-WebSocket-Protocol 头字段）
        request.setRawHeader(b"Sec-WebSocket-Protocol", self.jwt_token.encode())
        # 打开 WebSocket 连接
        self.websocket.open(request)

    # 连接建立 触发
    def on_connected(self):
        print("WebSocket connected!")
        self.connect_status_signal.emit('粘度、密度数据传输，WebSocket connected!')
        self.websocket_connect_status = True
        self.reconnect_timer = QTimer()  # 用于定时重连
        self.reconnect_timer.timeout.connect(self.reconnect)

    # 连接出错 触发
    def on_error(self, error):
        print(f"WebSocket error: {error}")
        self.connect_status_signal.emit('粘度、密度数据传输，WebSocket error!')
        self.websocket_connect_status = False
        # 处理重连机制
        self.handle_reconnect()

    # 重连
    def handle_reconnect(self):
        """处理重连逻辑"""
        self.connect_status_signal.emit('粘度、密度数据传输，WebSocket reconnect!')
        self.reconnect_timer.start(5 * 1000)  # 转换为毫秒

    def reconnect(self):
        """执行重连"""
        self.reconnect_timer.stop()  # 停止定时器
        self.OpenWebSocket()  # 重新连接

    # 连接断开 触发
    def on_disconnected(self):
        print("WebSocket disconnected!")
        self.connect_status_signal.emit('粘度、密度数据传输，WebSocket disconnected!')
        self.websocket_connect_status = False

    # 接收消息 触发
    def on_message_received(self, message):
        msg = json.loads(message)
        status_code = msg['flag']
        print("status_code:" + str(status_code))
        # 返回状态码，1002说明发送成功，1004说明发送失败
        if status_code == 1002:
            now_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.send_mesage_signal.emit(now_time + f'粘/密度已传到服务器 ID：{self.viscosity_point_1}-{self.viscosity_point_2}', self.viscosity_point_1, self.viscosity_point_2)
            self.viscosity_point_1 = self.viscosity_point_2
            print('self.point_1 = self.point_2：', self.viscosity_point_1, self.viscosity_point_2)
        if status_code == 1004:
            self.viscosity_point_1 = self.viscosity_point_1 - 1

    # 读取数据库文件
    def read_db(self, query_str):
        file_path = self.file_path
        conn = sqlite3.connect(file_path)
        print('数据库连接成功')
        # 创建游标对象
        cursor = conn.cursor()
        # 执行查询
        print(query_str)
        cursor.execute(query_str)
        # 获取结果
        rows = cursor.fetchall()
        # print(f'rows: {rows}')
        # 关闭游标
        cursor.close()
        # 关闭连接
        conn.close()
        return rows

    def run(self):
        try:
            while self.running:
                time.sleep(1)
                self.check_updates()
        except Exception as e:
            print(f'客户端出错了！！！ =={e}')
            self.running = False
            self.websocket_connect_status = False
            self.websocket.close()
            self.update_ui_signal.emit(self.viscosity_point_1, self.viscosity_point_2)

    # 检查数据库是否有数据更新
    def check_updates(self):
        max_recv = 600
        if self.viscosity_point_1 == 0:
            # 第一次发送数据
            query_str1 = 'SELECT * FROM ViscosityData ORDER BY id ASC LIMIT 1'
            query_str2 = 'SELECT * FROM ViscosityData ORDER BY id DESC LIMIT 1'
            rows1 = self.read_db(query_str1)
            rows2 = self.read_db(query_str2)
            # 查询的数据为空，即表中没有数据
            if not rows1:
                self.viscosity_point_1 = 0
                self.viscosity_point_2 = 0
                print('数据表为空！！没有数据！')
            else:
                self.viscosity_point_1 = rows1[0][0]
                self.viscosity_point_2 = rows2[0][0]

                query_str = 'SELECT * FROM ViscosityData WHERE ID BETWEEN {} AND {} ORDER BY ID ASC'.format(self.viscosity_point_1, self.viscosity_point_2)
                rows = self.read_db(query_str)
                rows = [list(item) for item in rows]
                # 将时间转为字符串，避免json序列化出错
                for item in rows:
                    for j in range(len(item)):
                        if type(item[j]) == datetime.datetime:
                            item[j] = str(item[j])
                    # 每条数据前都插入井信息
                    item.insert(0, self.well_info)
                if len(rows) > max_recv:
                    start = 0
                    num_range = int(len(rows) / max_recv)
                    for i in range(num_range):
                        send_data = rows[start: start + max_recv]
                        json_data = json.dumps(send_data)
                        self.websocket.sendTextMessage(json_data)
                        start += max_recv
                    send_data = rows[num_range * max_recv:]
                    json_data = json.dumps(send_data)
                    self.websocket.sendTextMessage(json_data)
                    # 调用 WebSocket 的刷新方法，确保消息立即发送
                    self.websocket.flush()
                else:
                    send_data = rows
                    json_data = json.dumps(send_data)
                    self.websocket.sendTextMessage(json_data)
                    # 调用 WebSocket 的刷新方法，确保消息立即发送
                    self.websocket.flush()
        else:
            # point_1 = self.point_2 说明没有数据更新
            if self.viscosity_point_1 == self.viscosity_point_2:
                print('数据库中没有数据更新')
                time.sleep(1)
                query_str = 'SELECT * FROM ViscosityData ORDER BY id DESC LIMIT 1'  # 查询数据库中最后一条数据
                rows = self.read_db(query_str)
                self.viscosity_point_2 = rows[0][0]
            # point_1 ！= self.point_2 说明有数据更新
            if self.viscosity_point_1 != self.viscosity_point_2:
                print('数据库中有数据更新！')
                self.viscosity_point_1 = self.viscosity_point_1 + 1
                # 发送数据给后端服务器
                query_str = 'SELECT * FROM ViscosityData WHERE ID BETWEEN {} AND {} ORDER BY ID ASC'.format(self.viscosity_point_1, self.viscosity_point_2)
                rows = self.read_db(query_str)
                rows = [list(item) for item in rows]
                for item in rows:  # 将时间转为字符串，避免json序列化出错
                    for j in range(len(item)):
                        if type(item[j]) == datetime.datetime:
                            item[j] = str(item[j])
                    # 每条数据前都插入井信息
                    item.insert(0, self.well_info)
                if len(rows) > max_recv:
                    start = 0
                    num_range = int(len(rows) / max_recv)
                    for i in range(num_range):
                        send_data = rows[start: start + max_recv]
                        json_data = json.dumps(send_data)
                        self.websocket.sendTextMessage(json_data)
                        start += max_recv
                    send_data = rows[num_range * max_recv:]
                    json_data = json.dumps(send_data)
                    self.websocket.sendTextMessage(json_data)
                    # 调用 WebSocket 的刷新方法，确保消息立即发送
                    self.websocket.flush()
                else:
                    send_data = rows
                    json_data = json.dumps(send_data)
                    self.websocket.sendTextMessage(json_data)
                    # 调用 WebSocket 的刷新方法，确保消息立即发送
                    self.websocket.flush()

    def stop(self):
        """停止线程"""
        self.running = False
        if self.websocket_connect_status:
            self.websocket.close()
        print('线程已停止!')
# 接收数据线程 水数据
class ReceiverWaterThread(QThread):

    update_textEdit = pyqtSignal(str)
    connection_success = pyqtSignal()  # 新增：连接成功信号

    def __init__(self, file_path, ip, port):
        super(ReceiverWaterThread, self).__init__()

        self.file_path = file_path
        self.ip = ip
        self.port = port
        self.running = True
        print('接收数据线程已启动')

    def parse_float_from_hex(self, hex_str):
        """
        从16进制字符串中解析IEEE 754浮点数
        :param hex_str: 16进制字符串（8个字符，表示4字节浮点数）
        :return: 解析后的浮点数
        """
        # 将16进制字符串转换为字节数据
        byte_data = bytes.fromhex(hex_str)
        # 直接解析为浮点数（使用大端字节序）
        float_value = struct.unpack('>f', byte_data)[0]
        return float_value

    def save_data(self, data):
        temp_file_path = self.file_path
        # 连接到数据库（如果数据库文件）
        conn = sqlite3.connect(temp_file_path)
        # 创建一个游标对象，用于执行SQL语句
        cursor = conn.cursor()
        # 根据列数生成占位符
        placeholders = ", ".join(["?"] * (len(data)))
        # 插入数据
        # placeholders = ', '.join(['?'] * len(data))  # 生成问号占位符
        cursor.execute(f'INSERT INTO WaterData (Time,waterflow,accumulatewater) VALUES ({placeholders})', data)
        # 提交更改
        conn.commit()
        # 关闭连接
        cursor.close()
        conn.close()

        print(f'{data[0]}秒的水数据已保存到数据库文件中')
        self.update_textEdit.emit(f'{data[0]}秒的水数据已保存到数据库文件中')

    def run(self):
        # --------------------------
        # IP配置
        # --------------------------
        try:
            """
                发送 Modbus TCP 请求帧并接收响应
            """
            # 创建 TCP 套接字
            self.update_textEdit.emit(f'正在发起连接，IP：{self.ip}，端口号：{self.port}')
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((self.ip, self.port))
            self.update_textEdit.emit("TCP连接建立成功")
            self.connection_success.emit()  # 发送连接成功信号
            # --------------------------
            # 构造请求帧（示例：读取设备号1的数据）
            # --------------------------
            # Modbus TCP 请求帧参数
            transaction_id = 0x0001  # 事务ID（可动态递增）
            protocol_id = 0x0000  # 协议ID（固定）

            device_id = 0x01  # 设备地址
            func_code = 0x03  # 功能码：读取保持寄存器
            start_addr = 0x0118  # 起始地址
            reg_count = 0x0008  # 读取寄存器数量
            # 构建请求数据帧（无CRC）
            # 构建正确的 Modbus TCP 请求帧（字节流）
            request = (
                    transaction_id.to_bytes(2, 'big') +
                    protocol_id.to_bytes(2, 'big') +
                    (6).to_bytes(2, 'big') +  # 后续字节长度（设备ID + 功能码 + 地址 + 数量）
                    device_id.to_bytes(1, 'big') +
                    func_code.to_bytes(1, 'big') +
                    start_addr.to_bytes(2, 'big') +
                    reg_count.to_bytes(2, 'big')
            )
            while self.running:
                time.sleep(10)
                try:
                    # 发送请求
                    sock.send(request)
                    # 等待并读取响应
                    response = sock.recv(1024)  # 读取最多1024字节
                    if not response:
                        self.update_textEdit.emit("未收到响应数据")
                        raise TimeoutError("未收到响应数据")
                    print(f"接收响应: {response.hex().upper()}")
                    data = response.hex().upper()
                    data_list = []
                    # --------------------------
                    # 解析响应数据（根据示例格式）
                    # --------------------------
                    # 提取两个浮点数的16进制部分
                    float1_hex = data[18:26]  # 509E46D5
                    float2_hex = data[26:34]  # 540E3F83
                    float1 = round(self.parse_float_from_hex(float1_hex), 2)
                    float2 = round(self.parse_float_from_hex(float2_hex), 2)
                    # 打印结果
                    cur_time = datetime.datetime.now()
                    current_time = cur_time.strftime("%H:%M:%S")
                    data_list.append(current_time)
                    data_list.append(float1)
                    data_list.append(float2)
                    self.update_textEdit.emit(f"{current_time}数据解析结果==>瞬时流量：{float1}, 累积液量：{float2}")
                    self.save_data(tuple(data_list))
                    # if float1 >= 10.0:
                    #     self.save_data(tuple(data_list))
                except Exception as e:
                    self.update_textEdit.emit(f"通信错误: {str(e)}")
        except Exception as e:
            print(f"发生错误: {e}")
            self.update_textEdit.emit(f"发生错误: {e}")
            self.update_textEdit.emit(f"请确认IP地址和端口号正确之后重试！")
        finally:
            if sock:
                sock.close()
                self.update_textEdit.emit("socket连接已关闭！")

    def stop(self):
        self.running = False
# 上传数据 线程 水数据
class UploadWaterThread(QThread):

    update_ui_signal = pyqtSignal(int, int)
    send_mesage_signal = pyqtSignal(str, int, int)
    connect_status_signal = pyqtSignal(str)

    def __init__(self, file_path, platform, water_point_1, water_point_2, jwt_token):
        super(UploadWaterThread, self).__init__()

        self.jwt_token = jwt_token
        self.OpenWebSocket()
        self.websocket_connect_status = False   # websocket 的连接状态
        self.platform = platform
        self.file_path = file_path
        self.water_point_1 = water_point_1
        self.water_point_2 = water_point_2

        self.running = True
        print('向服务器传输秒点数据的线程已启动')
        print(self.file_path)
        print(f'point_1: {self.water_point_1}, point_2: {self.water_point_2}')

    # 建立 websocket 连接
    def OpenWebSocket(self):
        # 初始化 QWebSocket
        self.websocket = QWebSocket()
        # 连接 WebSocket 信号
        self.websocket.connected.connect(self.on_connected)
        self.websocket.error.connect(self.on_error)
        self.websocket.disconnected.connect(self.on_disconnected)
        # 连接 textMessageReceived 信号以接收信息
        self.websocket.textMessageReceived.connect(self.on_message_received)
        API_url = 'ws://39.101.202.11/ws/WaterDataTransfer/'
        # API_url = 'ws://10.51.50.77:55555/ws/WaterDataTransfer/'
        # API_url = 'ws://10.51.50.99/ws/WaterDataTransfer/'
        # API_url = 'ws://localhost:8000/ws/WaterDataTransfer/'
        # 将字符串 URL 转换为 QUrl 对象
        url = QUrl(API_url)
        # websocket不支持自定义请求头，可以通过子协议字段携带token，后端连接前验证token，
        # 为了传递子协议，需要使用 QNetworkRequest 来设置 Sec-WebSocket-Protocol 头字段。
        request = QNetworkRequest(url)  # 创建 QNetworkRequest 对象
        # 设置子协议（通过 Sec-WebSocket-Protocol 头字段）
        request.setRawHeader(b"Sec-WebSocket-Protocol", self.jwt_token.encode())
        # 打开 WebSocket 连接
        self.websocket.open(request)

    # 连接建立 触发
    def on_connected(self):
        print("WebSocket connected!")
        self.connect_status_signal.emit('水数据传输，WebSocket connected!')
        self.websocket_connect_status = True
        self.reconnect_timer = QTimer()  # 用于定时重连
        self.reconnect_timer.timeout.connect(self.reconnect)

    # 连接出错 触发
    def on_error(self, error):
        print(f"WebSocket error: {error}")
        self.connect_status_signal.emit('水数据传输，WebSocket error!')
        self.websocket_connect_status = False
        # 处理重连机制
        self.handle_reconnect()

    # 重连
    def handle_reconnect(self):
        """处理重连逻辑"""
        self.connect_status_signal.emit('粘度、密度数据传输，WebSocket reconnect!')
        self.reconnect_timer.start(5 * 1000)  # 转换为毫秒

    def reconnect(self):
        """执行重连"""
        self.reconnect_timer.stop()  # 停止定时器
        self.OpenWebSocket()  # 重新连接

    # 连接断开 触发
    def on_disconnected(self):
        print("WebSocket disconnected!")
        self.connect_status_signal.emit('水数据传输，WebSocket disconnected!')
        self.websocket_connect_status = False

    # 接收消息 触发
    def on_message_received(self, message):
        msg = json.loads(message)
        status_code = msg['flag']
        print("status_code:" + str(status_code))
        # 返回状态码，1002说明发送成功，1004说明发送失败
        if status_code == 1002:
            now_time = datetime.datetime.now().strftime('%H:%M:%S')
            self.send_mesage_signal.emit(now_time + f'水数据已传到服务器 ID：{self.water_point_1}-{self.water_point_2}', self.water_point_1, self.water_point_2)
            self.water_point_1 = self.water_point_2
            print('self.point_1 = self.point_2：', self.water_point_1, self.water_point_2)
        if status_code == 1004:
            self.water_point_1 = self.water_point_1 - 1

    # 读取数据库文件
    def read_db(self, query_str):
        file_path = self.file_path
        conn = sqlite3.connect(file_path)
        print('数据库连接成功')
        # 创建游标对象
        cursor = conn.cursor()
        # 执行查询
        print(query_str)
        cursor.execute(query_str)
        # 获取结果
        rows = cursor.fetchall()
        # print(f'rows: {rows}')
        # 关闭游标
        cursor.close()
        # 关闭连接
        conn.close()
        return rows

    def run(self):
        try:
            while self.running:
                time.sleep(1)
                self.check_updates()
        except Exception as e:
            print(f'客户端出错了！！！ =={e}')
            self.running = False
            self.websocket_connect_status = False
            self.websocket.close()
            self.update_ui_signal.emit(self.water_point_1, self.water_point_2)

    # 检查数据库是否有数据更新
    def check_updates(self):
        max_recv = 600
        if self.water_point_1 == 0:
            # 第一次发送数据
            query_str1 = 'SELECT * FROM WaterData ORDER BY id ASC LIMIT 1'
            query_str2 = 'SELECT * FROM WaterData ORDER BY id DESC LIMIT 1'
            rows1 = self.read_db(query_str1)
            rows2 = self.read_db(query_str2)
            print('我执行了第一次发送水数据！')
            # 查询的数据为空，即表中没有数据
            if not rows1:
                self.water_point_1 = 0
                self.water_point_2 = 0
                print('数据表为空！！没有数据！')
            else:
                self.water_point_1 = rows1[0][0]
                self.water_point_2 = rows2[0][0]
                query_str = 'SELECT * FROM WaterData WHERE ID BETWEEN {} AND {} ORDER BY ID ASC'.format(self.water_point_1, self.water_point_2)
                rows = self.read_db(query_str)
                rows = [list(item) for item in rows]
                # 将时间转为字符串，避免json序列化出错
                for item in rows:
                    for j in range(len(item)):
                        if type(item[j]) == datetime.datetime:
                            item[j] = str(item[j])
                    # 每条数据前都插入井信息
                    item.insert(0, self.platform)
                if len(rows) > max_recv:
                    start = 0
                    num_range = int(len(rows) / max_recv)
                    for i in range(num_range):
                        send_data = rows[start: start + max_recv]
                        json_data = json.dumps(send_data)
                        self.websocket.sendTextMessage(json_data)
                        start += max_recv
                    send_data = rows[num_range * max_recv:]
                    json_data = json.dumps(send_data)
                    self.websocket.sendTextMessage(json_data)
                    # 调用 WebSocket 的刷新方法，确保消息立即发送
                    self.websocket.flush()
                else:
                    send_data = rows
                    json_data = json.dumps(send_data)
                    self.websocket.sendTextMessage(json_data)
                    # 调用 WebSocket 的刷新方法，确保消息立即发送
                    self.websocket.flush()
        else:
            # point_1 = self.point_2 说明没有数据更新
            if self.water_point_1 == self.water_point_2:
                print('数据库中没有数据更新')
                time.sleep(1)
                query_str = 'SELECT * FROM WaterData ORDER BY id DESC LIMIT 1'  # 查询数据库中最后一条数据
                rows = self.read_db(query_str)
                self.water_point_2 = rows[0][0]
            # point_1 ！= self.point_2 说明有数据更新
            if self.water_point_1 != self.water_point_2:
                print('数据库中有数据更新！')
                self.water_point_1 = self.water_point_1 + 1
                # 发送数据给后端服务器
                query_str = 'SELECT * FROM WaterData WHERE ID BETWEEN {} AND {} ORDER BY ID ASC'.format(self.water_point_1, self.water_point_2)
                rows = self.read_db(query_str)
                rows = [list(item) for item in rows]
                for item in rows:  # 将时间转为字符串，避免json序列化出错
                    for j in range(len(item)):
                        if type(item[j]) == datetime.datetime:
                            item[j] = str(item[j])
                    # 每条数据前都插入井信息
                    item.insert(0, self.platform)
                if len(rows) > max_recv:
                    start = 0
                    num_range = int(len(rows) / max_recv)
                    for i in range(num_range):
                        send_data = rows[start: start + max_recv]
                        json_data = json.dumps(send_data)
                        self.websocket.sendTextMessage(json_data)
                        start += max_recv
                    send_data = rows[num_range * max_recv:]
                    json_data = json.dumps(send_data)
                    self.websocket.sendTextMessage(json_data)
                    # 调用 WebSocket 的刷新方法，确保消息立即发送
                    self.websocket.flush()
                else:
                    send_data = rows
                    json_data = json.dumps(send_data)
                    self.websocket.sendTextMessage(json_data)
                    # 调用 WebSocket 的刷新方法，确保消息立即发送
                    self.websocket.flush()

    def stop(self):
        """停止线程"""
        self.running = False
        if self.websocket_connect_status:
            self.websocket.close()
        print('线程已停止!')
