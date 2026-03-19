# -*- coding: utf-8 -*-

from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import QThread, pyqtSignal

try:
    from PyQt5.QtChart import QChart, QChartView, QLineSeries, QValueAxis, QDateTimeAxis  # type: ignore
    QT_CHART_AVAILABLE = True
except Exception:
    QT_CHART_AVAILABLE = False

import sqlite3
import datetime
import time



def _parse_time_to_datetime(text, base_date, last_dt):
    """
    参数：
        text: 原始时间字符串（可能是 'YYYY-MM-DD HH:MM:SS' 或 'HH:MM:SS'）
        base_date: 统一映射使用的“虚拟日期”（如 datetime.date(2000, 1, 1)）
        last_dt: 上一条记录的 datetime，用于处理跨午夜（可以为 None）

    返回：
        正常解析则返回 datetime.datetime 实例（日期部分统一为 base_date/跨午夜累加），无法解析则返回 None。
    """
    text = str(text).strip()
    try:
        dt_full = datetime.datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        return dt_full
    except Exception:
        pass
    t = None
    try:
        t = datetime.datetime.strptime(text, "%H:%M:%S").time()
    except Exception:
        return None
    dt_obj = datetime.datetime.combine(base_date, t)
    if last_dt is not None and dt_obj <= last_dt:
        dt_obj = dt_obj + datetime.timedelta(days=1)
    return dt_obj

def _dt_to_ms(dt):
    """
    将 Python datetime 转为 Qt 时间轴使用的毫秒时间戳。
    与主线程中原 load_full_data 的算法一致，保证 Worker 与主线程时间基准统一。
    dt: datetime.datetime（可由 _parse_time_to_datetime 得到）
    返回: int，自纪元起的毫秒数（Qt 约定）
    """
    qt_dt = QtCore.QDateTime(
        dt.year, dt.month, dt.day,
        dt.hour, dt.minute, dt.second
    )
    return int(qt_dt.toMSecsSinceEpoch())

class _PlotLoadWorker(QThread):
    """在子线程中执行 DB 查询与解析，通过信号把结果传给主线程。"""
    # 参数：dict。全量时含 mode='full', sec_points, visc_points, max_id, seconds_cols, overall_x_min, overall_x_max, view_x_min, view_x_max, p_range, rs_range, v_range
    # 增量时含 mode='incremental', new_sec_points, new_visc_points, new_max_id
    data_ready = pyqtSignal(dict)

    def __init__(self, db_path, last_max_id=0, seconds_cols=None, visc_base_date=None, y_ranges=None, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self.last_max_id = last_max_id
        self.seconds_cols = seconds_cols  # (pressure_col, rate_col, sand_col) 或 None
        self.visc_base_date = visc_base_date  # datetime.date 或 None，粘度解析 system_time 时用
        self.y_ranges = y_ranges  # 用户 Y 轴范围 dict，None 表示用下方默认

    def run(self):
        if not self.db_path:
            return
        try:
            if self.seconds_cols is None or self.last_max_id <= 0:
                self._run_full_load()
            else:
                self._run_incremental_load()
        except Exception as e:
            import traceback
            print("本地曲线 Worker 异常:", e)
            traceback.print_exc()

    def _run_full_load(self):
        import sqlite3
        _DB_TIMEOUT = 10
        _MAX_RETRIES = 3
        _RETRY_SLEEP = 0.3

        conn = None
        cursor = None
        sec_rows = []
        visc_rows = []
        seconds_cols = None
        base_date = datetime.date(2000, 1, 1)
        ref_date = base_date

        for attempt in range(_MAX_RETRIES):
            try:
                conn = sqlite3.connect(self.db_path, timeout=_DB_TIMEOUT)
                conn.execute("PRAGMA journal_mode=WAL")
                cursor = conn.cursor()

                cursor.execute("PRAGMA table_info(LogData)")
                columns_info = cursor.fetchall()
                column_names = [row[1] for row in columns_info]
                index_map = {name: idx for idx, name in enumerate(column_names)}
                if not all(c in index_map for c in ["system_time", "viscosity", "density"]):
                    cursor.close()
                    conn.close()
                    return

                standard_seconds_cols = ["套管压力", "套管排量", "砂比"]
                seconds_cols = None
                if all(c in index_map for c in standard_seconds_cols):
                    seconds_cols = ("套管压力", "套管排量", "砂比")
                else:
                    cursor.execute(
                        "SELECT COUNT(*) FROM LogData WHERE Time IS NOT NULL AND viscosity IS NULL AND density IS NULL"
                    )
                    n_sec = cursor.fetchone()[0]
                    if n_sec <= 0:
                        cursor.close()
                        conn.close()
                        return
                    ignore = {"ID", "Time", "system_time", "viscosity", "density"}
                    candidates = []
                    for col in column_names:
                        if col in ignore:
                            continue
                        cursor.execute(
                            f'SELECT COUNT(*) FROM LogData WHERE Time IS NOT NULL AND viscosity IS NULL AND density IS NULL AND "{col}" IS NOT NULL'
                        )
                        if cursor.fetchone()[0] != n_sec:
                            continue
                        cursor.execute(
                            f'SELECT MIN(CAST("{col}" AS REAL)), MAX(CAST("{col}" AS REAL)) FROM LogData WHERE Time IS NOT NULL AND viscosity IS NULL AND density IS NULL AND "{col}" IS NOT NULL'
                        )
                        mn, mx = cursor.fetchone()
                        candidates.append((col, mn, mx))
                    if len(candidates) >= 3:
                        candidates_sorted = sorted(candidates, key=lambda x: (x[2] is None, x[2]), reverse=True)
                        pressure_col = candidates_sorted[0][0]
                        rest = candidates_sorted[1:]
                        sand_like = [c for c in rest if c[2] is not None and c[2] <= 2.0]
                        sand_col = sorted(sand_like, key=lambda x: abs((x[2] or 0.0) - 1.0))[0][0] if sand_like else rest[-1][0]
                        rate_col = next(c[0] for c in rest if c[0] != sand_col)
                        seconds_cols = (pressure_col, rate_col, sand_col)
                if seconds_cols is None:
                    cursor.close()
                    conn.close()
                    return

                pressure_col, rate_col, sand_col = seconds_cols
                cursor.execute(
                    f'SELECT ID, Time, "{pressure_col}", "{rate_col}", "{sand_col}" FROM LogData WHERE Time IS NOT NULL AND viscosity IS NULL AND density IS NULL ORDER BY ID ASC'
                )
                sec_rows = cursor.fetchall()
                cursor.execute(
                    "SELECT ID, system_time, viscosity, density FROM LogData WHERE system_time IS NOT NULL AND viscosity IS NOT NULL AND density IS NOT NULL ORDER BY ID ASC"
                )
                visc_rows = cursor.fetchall()

                cursor.close()
                conn.close()
                conn = None
                cursor = None
                break
            except sqlite3.OperationalError:
                if cursor:
                    try:
                        cursor.close()
                    except Exception:
                        pass
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass
                conn = None
                cursor = None
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_SLEEP)
                else:
                    raise

        # 以下在连接已关闭后，仅用 sec_rows / visc_rows 在内存中处理
        sec_points = []
        last_dt_time = None
        for row in sec_rows:
            rid, raw_time, raw_p, raw_r, raw_s = row[0], row[1], row[2], row[3], row[4]
            dt = _parse_time_to_datetime(raw_time, base_date, last_dt_time)
            if dt is None:
                continue
            last_dt_time = dt
            ms = _dt_to_ms(dt)
            try:
                p_val = float(raw_p) if raw_p is not None else 0.0
            except (TypeError, ValueError):
                p_val = 0.0
            try:
                r_val = float(raw_r) if raw_r is not None else 0.0
            except (TypeError, ValueError):
                r_val = 0.0
            try:
                s_val = float(raw_s) if raw_s is not None else 0.0
            except (TypeError, ValueError):
                s_val = 0.0
            sec_points.append((ms, p_val, r_val, s_val))
        sec_points.sort(key=lambda x: x[0])
        max_id_sec = max((row[0] for row in sec_rows), default=0)
        ref_date = base_date
        if sec_rows:
            try:
                ref_date = datetime.datetime.strptime(str(sec_rows[0][1]).strip(), "%Y-%m-%d %H:%M:%S").date()
            except Exception:
                pass
        visc_points = []
        last_dt_sys = None
        for row in visc_rows:
            rid, raw_sys_time, raw_vis, _ = row[0], row[1], row[2], row[3]
            dt = _parse_time_to_datetime(raw_sys_time, ref_date, last_dt_sys)
            if dt is None:
                continue
            last_dt_sys = dt
            ms = _dt_to_ms(dt)
            try:
                v = float(raw_vis)
            except (TypeError, ValueError):
                continue
            visc_points.append((ms, v))
        visc_points.sort(key=lambda x: x[0])
        max_id_visc = max((row[0] for row in visc_rows), default=0)
        max_id = max(max_id_sec, max_id_visc)

        all_ts = [x[0] for x in sec_points] + [x[0] for x in visc_points]
        if not all_ts:
            return
        # 首点即出轴；右端固定缓冲 5 小时，轴长 = 数据 + 5h
        BUFFER_HOURS_MS = 1 * 3600 * 1000
        data_x_min = min(all_ts)
        data_x_max = max(all_ts)
        overall_x_min = data_x_min
        overall_x_max = data_x_max + BUFFER_HOURS_MS
        view_x_min = min(x[0] for x in sec_points) if sec_points else overall_x_min
        view_x_max = (max(x[0] for x in sec_points) if sec_points else data_x_max) + BUFFER_HOURS_MS
        # p_vals = [x[1] for x in sec_points]
        # rs_vals = [x[2] for x in sec_points] + [x[3] for x in sec_points]
        # v_vals = [x[1] for x in visc_points]
        # p_min, p_max = (min(p_vals), max(p_vals)) if p_vals else (0.0, 1.0)
        # margin_p = (p_max - p_min) * 0.2 if p_max > p_min else 0.2
        # p_range = (p_min - margin_p, p_max + margin_p)
        # rs_min = min(rs_vals) if rs_vals else 0.0
        # rs_max = max(rs_vals) if rs_vals else 1.0
        # margin_rs = (rs_max - rs_min) * 0.2 if rs_max > rs_min else 0.2
        # rs_range = (rs_min - margin_rs, rs_max + margin_rs)
        # v_min = min(v_vals) if v_vals else 0.0
        # v_max = max(v_vals) if v_vals else 100.0
        # margin_v = (v_max - v_min) * 0.2 if v_max > v_min else 10.0
        # v_range = (v_min - margin_v, v_max + margin_v)
        # 纵轴固定刻度，从 0 开始，与现场大屏一致；曲线从轴线底部（0）开始绘制
        # FIXED_PRESSURE_MAX = 100.0  # 套压 (MPa)
        # FIXED_RATE_SAND_MAX = 50.0  # 排量 / 砂比
        # FIXED_VISCOSITY_MAX = 100.0  # 粘度 (mPa·s)
        # p_range = (0.0, FIXED_PRESSURE_MAX)
        # rs_range = (0.0, FIXED_RATE_SAND_MAX)
        # v_range = (0.0, FIXED_VISCOSITY_MAX)
        # 纵轴固定刻度：套压 0~100，排量 0~50，砂比 0~2000，粘度 0~100；曲线从 0 起画
        # 纵轴范围：优先使用用户设置（y_ranges），否则用默认
        if self.y_ranges:
            p_range = tuple(self.y_ranges.get('p_range', (0.0, 100.0)))
            rate_range = tuple(self.y_ranges.get('rate_range', (0.0, 50.0)))
            sand_range = tuple(self.y_ranges.get('sand_range', (0.0, 100.0)))
            v_range = tuple(self.y_ranges.get('v_range', (0.0, 100.0)))
        else:
            p_range = (0.0, 100.0)
            rate_range = (0.0, 50.0)
            sand_range = (0.0, 100.0)
            v_range = (0.0, 100.0)

        # self.data_ready.emit({
        #     "mode": "full",
        #     "sec_points": sec_points,
        #     "visc_points": visc_points,
        #     "max_id": max_id,
        #     "seconds_cols": seconds_cols,
        #     "overall_x_min": overall_x_min,
        #     "overall_x_max": overall_x_max,
        #     "view_x_min": view_x_min,
        #     "view_x_max": view_x_max,
        #     "p_range": p_range,
        #     "rs_range": rs_range,
        #     "v_range": v_range,
        #     "visc_base_date": (ref_date.year, ref_date.month, ref_date.day),
        # })
        self.data_ready.emit({
            "mode": "full",
            "sec_points": sec_points,
            "visc_points": visc_points,
            "max_id": max_id,
            "seconds_cols": seconds_cols,
            "overall_x_min": overall_x_min,
            "overall_x_max": overall_x_max,
            "view_x_min": view_x_min,
            "view_x_max": view_x_max,
            "p_range": p_range,
            "rate_range": rate_range,
            "sand_range": sand_range,
            "v_range": v_range,
            "visc_base_date": (ref_date.year, ref_date.month, ref_date.day),
        })

    def _run_incremental_load(self):
        import sqlite3
        _DB_TIMEOUT = 10
        _MAX_RETRIES = 3
        _RETRY_SLEEP = 0.3

        base_date = datetime.date(2000, 1, 1)
        base_date_visc = self.visc_base_date if self.visc_base_date is not None else base_date
        pressure_col, rate_col, sand_col = self.seconds_cols

        conn = None
        cursor = None
        sec_rows = []
        visc_rows = []

        for attempt in range(_MAX_RETRIES):
            try:
                conn = sqlite3.connect(self.db_path, timeout=_DB_TIMEOUT)
                conn.execute("PRAGMA journal_mode=WAL")
                cursor = conn.cursor()

                cursor.execute(
                    f'SELECT ID, Time, "{pressure_col}", "{rate_col}", "{sand_col}" FROM LogData WHERE ID > ? AND Time IS NOT NULL AND viscosity IS NULL AND density IS NULL ORDER BY ID ASC',
                    (self.last_max_id,)
                )
                sec_rows = cursor.fetchall()
                cursor.execute(
                    "SELECT ID, system_time, viscosity, density FROM LogData WHERE ID > ? AND system_time IS NOT NULL AND viscosity IS NOT NULL AND density IS NOT NULL ORDER BY ID ASC",
                    (self.last_max_id,)
                )
                visc_rows = cursor.fetchall()

                cursor.close()
                conn.close()
                conn = None
                cursor = None
                break
            except sqlite3.OperationalError:
                if cursor:
                    try:
                        cursor.close()
                    except Exception:
                        pass
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass
                conn = None
                cursor = None
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_SLEEP)
                else:
                    raise

        # 以下在连接已关闭后，仅用 sec_rows / visc_rows 在内存中处理
        new_sec_points = []
        last_dt_time = None
        for row in sec_rows:
            raw_time, raw_p, raw_r, raw_s = row[1], row[2], row[3], row[4]
            dt = _parse_time_to_datetime(raw_time, base_date, last_dt_time)
            if dt is None:
                continue
            last_dt_time = dt
            ms = _dt_to_ms(dt)
            try:
                p_val = float(raw_p) if raw_p is not None else 0.0
                r_val = float(raw_r) if raw_r is not None else 0.0
                s_val = float(raw_s) if raw_s is not None else 0.0
            except (TypeError, ValueError):
                continue
            new_sec_points.append((ms, p_val, r_val, s_val))
        new_max_id_sec = max((row[0] for row in sec_rows), default=self.last_max_id)

        new_visc_points = []
        last_dt_sys = None
        for row in visc_rows:
            raw_sys_time, raw_vis = row[1], row[2]
            dt = _parse_time_to_datetime(raw_sys_time, base_date_visc, last_dt_sys)
            if dt is None:
                continue
            last_dt_sys = dt
            ms = _dt_to_ms(dt)
            try:
                v = float(raw_vis)
            except (TypeError, ValueError):
                continue
            new_visc_points.append((ms, v))
        new_max_id_visc = max((row[0] for row in visc_rows), default=self.last_max_id)
        new_max_id = max(new_max_id_sec, new_max_id_visc)

        self.data_ready.emit({
            "mode": "incremental",
            "new_sec_points": new_sec_points,
            "new_visc_points": new_visc_points,
            "new_max_id": new_max_id,
        })

class ChartViewZoomPan(QChartView):
    """带滚轮缩放与鼠标拖拽平移的图表视图（支持多 Y 轴）。"""

    def __init__(self, chart, parent=None):
        super(ChartViewZoomPan, self).__init__(chart, parent)
        self.setRenderHint(QtGui.QPainter.Antialiasing)
        self._full_x_min = 0
        self._full_x_max = 10
        self._full_y_ranges = []
        self._drag_start = None

    def set_full_ranges(self, x_min, x_max, y_ranges):
        """记录完整数据范围。y_ranges 形如 [(y1_min, y1_max), (y2_min, y2_max), ...]。"""
        self._full_x_min = x_min
        self._full_x_max = x_max
        self._full_y_ranges = list(y_ranges) if y_ranges else []

    def _get_axes(self):
        """返回 (x_axis, y_axes)；其中 y_axes 可能包含多根 Y 轴。"""
        axes_h = self.chart().axes(QtCore.Qt.Horizontal)
        axes_v = self.chart().axes(QtCore.Qt.Vertical)
        axis_x = axes_h[0] if axes_h else None
        axis_ys = list(axes_v) if axes_v else []
        return axis_x, axis_ys

    def wheelEvent(self, event):
        axis_x, axis_ys = self._get_axes()
        if not axis_x:
            return
        # factor = 1.2 if event.angleDelta().y() > 0 else 1.0 / 1.2
        factor = 1.0 / 1.2 if event.angleDelta().y() > 0 else 1.2
        # 仅横轴缩放，纵坐标轴保持不变
        x_anchor = self._full_x_min
        if isinstance(axis_x, QDateTimeAxis):
            x_min_dt = axis_x.min()
            x_max_dt = axis_x.max()
            x_min = x_min_dt.toMSecsSinceEpoch()
            x_max = x_max_dt.toMSecsSinceEpoch()
            span_x = x_max - x_min
            if span_x <= 0:
                span_x = 1
            new_x_max = min(self._full_x_max, x_anchor + span_x * factor)
            new_x_max = max(new_x_max, x_anchor + 1)
            axis_x.setRange(
                QtCore.QDateTime.fromMSecsSinceEpoch(int(x_anchor)),
                QtCore.QDateTime.fromMSecsSinceEpoch(int(new_x_max)),
            )
        else:
            x_min = axis_x.min()
            x_max = axis_x.max()
            span_x = x_max - x_min
            if span_x <= 0:
                span_x = 1
            new_x_max = min(self._full_x_max, x_anchor + span_x * factor)
            new_x_max = max(new_x_max, x_anchor + 1e-6)
            axis_x.setRange(x_anchor, new_x_max)
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._drag_start = (event.pos().x(), event.pos().y())
        super(ChartViewZoomPan, self).mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_start is not None:
            axis_x, axis_ys = self._get_axes()
            if axis_x:
                dx = event.pos().x() - self._drag_start[0]
                w = self.width()
                if w > 0:
                    if isinstance(axis_x, QDateTimeAxis):
                        x_min_dt = axis_x.min()
                        x_max_dt = axis_x.max()
                        x_min = x_min_dt.toMSecsSinceEpoch()
                        x_max = x_max_dt.toMSecsSinceEpoch()
                        span = x_max - x_min
                        offset_x = dx * span / float(w)
                        new_x_min = x_min - offset_x
                        new_x_max = x_max - offset_x
                        # 水平拖拽时左端不早于曲线起点、右端不晚于曲线终点，保持窗口宽度
                        new_x_min = max(self._full_x_min, min(new_x_min, self._full_x_max - span))
                        new_x_max = new_x_min + span
                        axis_x.setRange(
                            QtCore.QDateTime.fromMSecsSinceEpoch(int(new_x_min)),
                            QtCore.QDateTime.fromMSecsSinceEpoch(int(new_x_max)),
                        )
                    else:
                        x_min, x_max = axis_x.min(), axis_x.max()
                        span = x_max - x_min
                        offset_x = dx * span / float(w)
                        new_x_min = x_min - offset_x
                        new_x_max = x_max - offset_x
                        new_x_min = max(self._full_x_min, min(new_x_min, self._full_x_max - span))
                        new_x_max = new_x_min + span
                        axis_x.setRange(new_x_min, new_x_max)
                self._drag_start = (event.pos().x(), event.pos().y())
        super(ChartViewZoomPan, self).mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._drag_start = None
        super(ChartViewZoomPan, self).mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_R:
            axis_x, axis_ys = self._get_axes()
            if axis_x:
                if isinstance(axis_x, QDateTimeAxis):
                    axis_x.setRange(
                        QtCore.QDateTime.fromMSecsSinceEpoch(int(self._full_x_min)),
                        QtCore.QDateTime.fromMSecsSinceEpoch(int(self._full_x_max)),
                    )
                else:
                    axis_x.setRange(self._full_x_min, self._full_x_max)
            if axis_ys and self._full_y_ranges:
                for axis_y, (y_min, y_max) in zip(axis_ys, self._full_y_ranges):
                    axis_y.setRange(y_min, y_max)
            event.accept()
        else:
            super(ChartViewZoomPan, self).keyPressEvent(event)


class LocalPlotWidget(QtWidgets.QWidget):
    """
    本地秒点曲线绘图控件：横轴为时间，纵轴多 Y 轴（套压 / 排量+砂比 / 黏度）。

    行为要求：
    - 第一次手动调用 load_full_data() 成功加载数据后，开始自动定时轮询；
    - 之后不用再手动点刷新；
    - 更换 db_path 后，需要重新“先手动一次再自动”；
    - 窗口销毁时停止轮询。
    """
    # 曲线数据更新后发出当前 db 路径，供主窗口/历史曲线弹窗同步刷新表格
    curve_data_updated = pyqtSignal(str)

    def __init__(self, parent=None):
        super(LocalPlotWidget, self).__init__(parent)

        self.db_path = ""
        self.current_well_info_str = ""

        # 自动刷新相关
        self._auto_refresh_timer = QtCore.QTimer(self)
        self._auto_refresh_timer.setInterval(3000)  # 默认 1 秒
        self._auto_refresh_timer.timeout.connect(self._on_auto_refresh_timeout)
        # 当前这个 db_path 是否已经因为“手动刷新”而启动过自动刷新
        self._auto_refresh_started_for_current_db = False
        # 当前一次 load_full_data 是否由定时器触发
        self._loading_from_timer = False
        # 防止重入
        self._is_loading = False
        self._last_max_id = 0
        self._seconds_cols = None  # (pressure_col, rate_col, sand_col)，全量后由 Worker 回填
        self._load_worker = None  # 当前加载线程，防止重复 start
        self._visc_base_date = None
        self._user_y_ranges = None  # 用户设置的 Y 轴范围 dict，None 表示用 Worker 默认
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if QT_CHART_AVAILABLE:
            self.chart = QChart()
            self.chart.setAnimationOptions(QChart.NoAnimation)

            self.chart_view = ChartViewZoomPan(self.chart, self)

            self.series_pressure = QLineSeries()
            self.series_pressure.setName("套管压力")
            self.series_pressure.setPen(QtGui.QPen(QtGui.QColor(255, 0, 0)))  # 红色

            self.series_rate = QLineSeries()
            self.series_rate.setName("套管排量")
            self.series_rate.setPen(QtGui.QPen(QtGui.QColor(0, 0, 139)))  # 深蓝色

            self.series_sand_ratio = QLineSeries()
            self.series_sand_ratio.setName("砂比")
            self.series_sand_ratio.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0)))  # 黑色

            self.series_viscosity = QLineSeries()
            self.series_viscosity.setName("粘度")
            self.series_viscosity.setPen(QtGui.QPen(QtGui.QColor(255, 165, 0)))  # 橙色

            self.chart.addSeries(self.series_pressure)
            self.chart.addSeries(self.series_rate)
            self.chart.addSeries(self.series_sand_ratio)
            self.chart.addSeries(self.series_viscosity)

            self.axis_time = QDateTimeAxis()
            self.axis_time.setTitleText("时间")
            self.axis_time.setFormat("HH:mm:ss")

            self.axis_pressure = QValueAxis()
            self.axis_pressure.setTitleText("套压 (MPa)")

            self.axis_rate = QValueAxis()
            self.axis_rate.setTitleText("排量")
            self.axis_sand_ratio = QValueAxis()
            self.axis_sand_ratio.setTitleText("砂比")

            self.axis_viscosity = QValueAxis()
            self.axis_viscosity.setTitleText("粘度 (mPa·s)")

            self.chart.addAxis(self.axis_time, QtCore.Qt.AlignBottom)
            self.chart.addAxis(self.axis_pressure, QtCore.Qt.AlignLeft)
            self.chart.addAxis(self.axis_rate, QtCore.Qt.AlignRight)
            self.chart.addAxis(self.axis_sand_ratio, QtCore.Qt.AlignRight)
            self.chart.addAxis(self.axis_viscosity, QtCore.Qt.AlignRight)

            self.series_pressure.attachAxis(self.axis_time)
            self.series_pressure.attachAxis(self.axis_pressure)

            self.series_rate.attachAxis(self.axis_time)
            self.series_rate.attachAxis(self.axis_rate)
            self.series_sand_ratio.attachAxis(self.axis_time)
            self.series_sand_ratio.attachAxis(self.axis_sand_ratio)

            self.series_viscosity.attachAxis(self.axis_time)
            self.series_viscosity.attachAxis(self.axis_viscosity)

            # 新增：为所有曲线设置鼠标悬停 tooltip
            self._setup_hover_tooltip()

            layout.addWidget(self.chart_view)
        else:
            placeholder_label = QtWidgets.QLabel(self)
            placeholder_label.setText("当前运行环境未安装 QtCharts，本地秒点曲线功能不可用。")
            placeholder_label.setAlignment(QtCore.Qt.AlignCenter)
            layout.addWidget(placeholder_label)

    def closeEvent(self, event):
        """窗口关闭时停止定时器。"""
        self._auto_refresh_timer.stop()
        super(LocalPlotWidget, self).closeEvent(event)

    def set_db_path(self, db_path, well, frac_num, layer, period):
        """设置当前 .db 路径以及井段信息，并更新图表标题。"""
        old_path = self.db_path
        self.db_path = db_path or ""
        if QT_CHART_AVAILABLE:
            self.current_well_info_str = f"{well}第{frac_num}次压裂{layer}第{period}段"
            self.chart.setTitle(self.current_well_info_str)

        # 更换 db 时，停止旧的自动刷新，新的 db 需要重新“先手动一次再自动”
        if self.db_path != old_path:
            self._auto_refresh_timer.stop()
            self._auto_refresh_started_for_current_db = False
            self._last_max_id = 0
            self._seconds_cols = None
            self._visc_base_date = None

    def set_user_y_ranges(self, p_range, rate_range, sand_range, v_range):
        """设置用户指定的四组 Y 轴范围，下次全量加载时生效。传 None 可恢复使用默认。"""
        if p_range is None and rate_range is None and sand_range is None and v_range is None:
            self._user_y_ranges = None
            return
        self._user_y_ranges = {
            'p_range': p_range or (0.0, 100.0),
            'rate_range': rate_range or (0.0, 50.0),
            'sand_range': sand_range or (0.0, 100.0),
            'v_range': v_range or (0.0, 100.0),
        }

    def clear_plot(self):
        """清空四条曲线的数据点。"""
        if QT_CHART_AVAILABLE:
            self.series_pressure.clear()
            self.series_rate.clear()
            self.series_sand_ratio.clear()
            self.series_viscosity.clear()

    def _on_worker_data_ready(self, result):
        """主线程：根据 Worker 返回的 result 一次性更新 series 与轴范围。"""
        if not QT_CHART_AVAILABLE:
            return
        mode = result.get("mode")
        if mode == "full":
            sec_points = result.get("sec_points", [])
            visc_points = result.get("visc_points", [])
            self.clear_plot()
            for ms, p_val, r_val, s_val in sec_points:
                self.series_pressure.append(ms, p_val)
                self.series_rate.append(ms, r_val)
                self.series_sand_ratio.append(ms, s_val)
            for ms, v_val in visc_points:
                self.series_viscosity.append(ms, v_val)
            self._last_max_id = result.get("max_id", 0)
            self._seconds_cols = result.get("seconds_cols")
            vb = result.get("visc_base_date")
            if vb and len(vb) == 3:
                try:
                    self._visc_base_date = datetime.date(int(vb[0]), int(vb[1]), int(vb[2]))
                except Exception:
                    self._visc_base_date = None
            else:
                self._visc_base_date = None
            view_x_min = result.get("view_x_min")
            view_x_max = result.get("view_x_max")
            overall_x_min = result.get("overall_x_min")
            overall_x_max = result.get("overall_x_max")
            p_range = result.get("p_range", (0.0, 100.0))
            rate_range = result.get("rate_range", (0.0, 50.0))
            sand_range = result.get("sand_range", (0.0, 100.0))
            v_range = result.get("v_range", (0.0, 100.0))
            if view_x_min is not None and view_x_max is not None:
                self.axis_time.setRange(
                    QtCore.QDateTime.fromMSecsSinceEpoch(int(view_x_min)),
                    QtCore.QDateTime.fromMSecsSinceEpoch(int(view_x_max)),
                )
            self.axis_pressure.setRange(p_range[0], p_range[1])
            self.axis_rate.setRange(rate_range[0], rate_range[1])
            self.axis_sand_ratio.setRange(sand_range[0], sand_range[1])
            self.axis_viscosity.setRange(v_range[0], v_range[1])
            if overall_x_min is not None and overall_x_max is not None:
                self.chart_view.set_full_ranges(
                    x_min=overall_x_min,
                    x_max=overall_x_max,
                    y_ranges=[p_range, rate_range, sand_range, v_range],
                )
        elif mode == "incremental":
            new_sec = result.get("new_sec_points", [])
            new_visc = result.get("new_visc_points", [])
            for ms, p_val, r_val, s_val in new_sec:
                self.series_pressure.append(ms, p_val)
                self.series_rate.append(ms, r_val)
                self.series_sand_ratio.append(ms, s_val)
            for ms, v_val in new_visc:
                self.series_viscosity.append(ms, v_val)
            self._last_max_id = result.get("new_max_id", self._last_max_id)
            # 若有新点可在此按需扩展轴范围（可选）
        self._is_loading = False
        if self.db_path:
            self.curve_data_updated.emit(self.db_path)

    def _setup_hover_tooltip(self):
        """
        为各条曲线绑定 hovered 信号，用于在鼠标悬停时显示共享时间的四组数据。
        悬浮框使用 QGraphicsItem（持久显示），不再使用 QToolTip（会自动消失）。
        """
        if not QT_CHART_AVAILABLE:
            return
        # 确保悬浮图元存在
        self._ensure_hover_items()
        for name in ("series_pressure", "series_rate", "series_sand_ratio", "series_viscosity"):
            series = getattr(self, name, None)
            if series is not None:
                series.hovered.connect(self._on_series_hovered)

    def _ensure_hover_items(self):
        """
        创建一个可持久显示的悬浮框（背景矩形 + 文本），并加入 chart 场景。
        只创建一次，后续仅更新内容和位置。
        """
        if not QT_CHART_AVAILABLE:
            return
        if not hasattr(self, "chart") or self.chart is None:
            return

        # 已创建则直接返回
        if getattr(self, "_hover_text_item", None) is not None and getattr(self, "_hover_rect_item", None) is not None:
            return

        # 延迟隐藏计时器（可选：避免 hovered True/False 抖动导致闪烁）
        self._hover_hide_timer = QtCore.QTimer(self)
        self._hover_hide_timer.setSingleShot(True)
        self._hover_hide_timer.timeout.connect(self._hide_hover_items)

        # 文本 item
        self._hover_text_item = QtWidgets.QGraphicsSimpleTextItem()
        self._hover_text_item.setZValue(9999)

        font = self._hover_text_item.font()
        font.setPointSize(9)
        self._hover_text_item.setFont(font)

        # 背景矩形 item
        self._hover_rect_item = QtWidgets.QGraphicsRectItem()
        self._hover_rect_item.setZValue(9998)

        pen = QtGui.QPen(QtGui.QColor(120, 120, 120))
        pen.setWidth(1)
        self._hover_rect_item.setPen(pen)
        self._hover_rect_item.setBrush(QtGui.QBrush(QtGui.QColor(255, 255, 255, 235)))  # 半透明白底

        # 加入 chart 场景
        self.chart.scene().addItem(self._hover_rect_item)
        self.chart.scene().addItem(self._hover_text_item)

        # 初始隐藏
        self._hover_rect_item.hide()
        self._hover_text_item.hide()

    def _hide_hover_items(self):
        """隐藏悬浮框（供 timer 调用）"""
        if getattr(self, "_hover_rect_item", None) is not None:
            self._hover_rect_item.hide()
        if getattr(self, "_hover_text_item", None) is not None:
            self._hover_text_item.hide()

    def _on_series_hovered(self, point, state):
        """
        悬浮显示（持久浮动框）：
        - state=True：更新内容与位置，并显示浮动框
        - state=False：启动短延时隐藏（避免闪烁）
        """
        if not QT_CHART_AVAILABLE:
            return

        # 确保图元存在
        self._ensure_hover_items()

        if not state:
            # 离开曲线点：延迟隐藏，避免抖动
            if getattr(self, "_hover_hide_timer", None) is not None:
                self._hover_hide_timer.start(200)
            return

        try:
            # 悬浮时取消隐藏
            if getattr(self, "_hover_hide_timer", None) is not None and self._hover_hide_timer.isActive():
                self._hover_hide_timer.stop()

            x = point.x()  # ms 时间戳（与 axis_time 一致）

            def nearest_y(series, max_delta_ms=5000):
                if series is None:
                    return None
                # pointsVector 在你当前工程可用；若未来环境不支持，可换成 series.points()
                pts = series.pointsVector()
                if not pts:
                    return None
                best_y = None
                best_dx = None
                for p in pts:
                    dx = abs(p.x() - x)
                    if best_dx is None or dx < best_dx:
                        best_dx = dx
                        best_y = p.y()
                if best_dx is not None and best_dx <= max_delta_ms:
                    return best_y
                return None

            series_p = getattr(self, "series_pressure", None)
            series_q = getattr(self, "series_rate", None)
            series_s = getattr(self, "series_sand_ratio", None)
            series_v = getattr(self, "series_viscosity", None)

            p_val = nearest_y(series_p)
            q_val = nearest_y(series_q)
            s_val = nearest_y(series_s)
            v_val = nearest_y(series_v)

            qt_dt = QtCore.QDateTime.fromMSecsSinceEpoch(int(x))
            time_str = qt_dt.toString("HH:mm:ss")

            def fmt(v):
                if v is None:
                    return "--"
                try:
                    return "{:.2f}".format(float(v))
                except Exception:
                    return str(v)

            lines = [
                f"时间: {time_str}",
                f"套管压力: {fmt(p_val)} MPa",
                f"套管排量: {fmt(q_val)}",
                f"砂比: {fmt(s_val)}",
                f"粘度: {fmt(v_val)} mPa·s",
            ]
            text = "\n".join(lines)

            # 更新文本
            self._hover_text_item.setText(text)

            # 计算位置：以当前点的屏幕坐标为锚点（chart内部坐标）
            anchor_scene_pos = self.chart.mapToPosition(point)  # QPointF（在 plotArea 坐标系）

            # 文本尺寸
            text_rect = self._hover_text_item.boundingRect()
            padding = 6

            # 默认放在右上角
            x0 = anchor_scene_pos.x() + 12
            y0 = anchor_scene_pos.y() - (text_rect.height() + 12)

            # 边界处理：不让框跑出 plotArea
            plot = self.chart.plotArea()
            box_w = text_rect.width() + padding * 2
            box_h = text_rect.height() + padding * 2

            if x0 + box_w > plot.right():
                x0 = anchor_scene_pos.x() - box_w - 12
            if y0 < plot.top():
                y0 = anchor_scene_pos.y() + 12
            if y0 + box_h > plot.bottom():
                y0 = plot.bottom() - box_h - 2

            # 设置背景矩形和文本位置（注意：QGraphicsItem 坐标在 chart scene 中）
            self._hover_text_item.setPos(x0 + padding, y0 + padding)
            self._hover_rect_item.setRect(x0, y0, box_w, box_h)

            # 显示
            self._hover_rect_item.show()
            self._hover_text_item.show()

        except Exception as e:
            import traceback
            print("本地曲线悬浮框异常:", e)
            traceback.print_exc()

    def _on_auto_refresh_timeout(self):
        """定时器：仅做增量加载（只查 ID > _last_max_id）；若尚未全量则先触发全量。"""
        if not self.db_path or self._is_loading:
            return
        self._is_loading = True
        self._loading_from_timer = True
        if self._last_max_id > 0 and self._seconds_cols is not None:
            self._start_load_worker(is_incremental=True)
        else:
            self._start_load_worker(is_incremental=False)

    def _start_load_worker(self, is_incremental=False):
        """启动子线程做全量或增量加载；结果通过 _on_worker_data_ready 在主线程更新。"""
        if self._load_worker is not None and self._load_worker.isRunning():
            self._is_loading = False
            return
        if is_incremental and self._last_max_id > 0 and self._seconds_cols is not None:
            self._load_worker = _PlotLoadWorker(
                self.db_path,
                last_max_id=self._last_max_id,
                seconds_cols=self._seconds_cols,
                visc_base_date=getattr(self, '_visc_base_date', None),
                parent=self,
            )
        else:
            self._load_worker = _PlotLoadWorker(
                self.db_path,
                last_max_id=0,
                seconds_cols=None,
                y_ranges=getattr(self, '_user_y_ranges', None),
                parent=self,
            )
        self._load_worker.data_ready.connect(self._on_worker_data_ready, QtCore.Qt.QueuedConnection)
        self._load_worker.finished.connect(self._on_worker_finished)
        self._load_worker.start()

    def _on_worker_finished(self):
        """Worker 线程结束，允许下次加载；若是手动刷新且尚未开定时器，则启动 3 秒定时器。"""
        self._load_worker = None
        if not self._loading_from_timer and not self._auto_refresh_started_for_current_db and self._last_max_id > 0:
            self._auto_refresh_timer.start()
            self._auto_refresh_started_for_current_db = True
        self._loading_from_timer = False

    def load_full_data(self):
        """手动刷新：在子线程做全量加载，主线程只负责收到结果后一次性更新 series/轴范围。"""
        if not QT_CHART_AVAILABLE or not self.db_path:
            return
        if self._is_loading:
            return
        self._is_loading = True
        self._loading_from_timer = False
        self._start_load_worker(is_incremental=False)

    # def load_full_data(self):
    #     """
    #     从 LogData 表读取全表数据按时间画完整曲线。
    #
    #     行为：
    #     - 若是“手动刷新”（非定时器触发）且成功加载到有效数据，
    #       且当前 db 还未启动过自动刷新，则启动定时器，后续自动轮询。
    #     """
    #     if not QT_CHART_AVAILABLE:
    #         return
    #     if not self.db_path:
    #         return
    #     if self._is_loading:
    #         return
    #
    #     self._is_loading = True
    #     loaded_any_valid_data = False
    #
    #     self.clear_plot()
    #
    #     try:
    #         conn = sqlite3.connect(self.db_path)
    #         cursor = conn.cursor()
    #
    #         cursor.execute("PRAGMA table_info(LogData)")
    #         columns_info = cursor.fetchall()
    #         column_names = [row[1] for row in columns_info]
    #         index_map = {name: idx for idx, name in enumerate(column_names)}
    #
    #         required_visc_cols = ["system_time", "viscosity", "density"]
    #         if any(c not in index_map for c in required_visc_cols):
    #             cursor.close()
    #             conn.close()
    #             return
    #
    #         standard_seconds_cols = ["套管压力", "套管排量", "砂比"]
    #         seconds_cols = None
    #         if all(c in index_map for c in standard_seconds_cols):
    #             seconds_cols = ("套管压力", "套管排量", "砂比")
    #         else:
    #             cursor.execute(
    #                 "SELECT COUNT(*) FROM LogData WHERE Time IS NOT NULL AND viscosity IS NULL AND density IS NULL"
    #             )
    #             seconds_rows_count = cursor.fetchone()[0]
    #             if seconds_rows_count > 0:
    #                 ignore = {"ID", "Time", "system_time", "viscosity", "density"}
    #                 candidates = []
    #                 for col in column_names:
    #                     if col in ignore:
    #                         continue
    #                     cursor.execute(
    #                         f"""
    #                         SELECT COUNT(*)
    #                         FROM LogData
    #                         WHERE Time IS NOT NULL
    #                           AND viscosity IS NULL
    #                           AND density IS NULL
    #                           AND "{col}" IS NOT NULL
    #                         """
    #                     )
    #                     n = cursor.fetchone()[0]
    #                     if n != seconds_rows_count:
    #                         continue
    #                     cursor.execute(
    #                         f"""
    #                         SELECT MIN(CAST("{col}" AS REAL)), MAX(CAST("{col}" AS REAL))
    #                         FROM LogData
    #                         WHERE Time IS NOT NULL
    #                           AND viscosity IS NULL
    #                           AND density IS NULL
    #                           AND "{col}" IS NOT NULL
    #                         """
    #                     )
    #                     mn, mx = cursor.fetchone()
    #                     candidates.append((col, mn, mx))
    #
    #                 if len(candidates) >= 3:
    #                     candidates_sorted = sorted(
    #                         candidates, key=lambda x: (x[2] is None, x[2]), reverse=True
    #                     )
    #                     pressure_col = candidates_sorted[0][0]
    #                     rest = candidates_sorted[1:]
    #                     sand_like = [c for c in rest if c[2] is not None and c[2] <= 2.0]
    #                     if sand_like:
    #                         sand_col = sorted(
    #                             sand_like, key=lambda x: abs((x[2] or 0.0) - 1.0)
    #                         )[0][0]
    #                     else:
    #                         sand_col = rest[-1][0]
    #                     rate_col = next(c[0] for c in rest if c[0] not in {sand_col})
    #                     seconds_cols = (pressure_col, rate_col, sand_col)
    #
    #         if seconds_cols is None:
    #             cursor.close()
    #             conn.close()
    #             return
    #
    #         base_date = datetime.date(2000, 1, 1)
    #
    #         pressure_col, rate_col, sand_col = seconds_cols
    #         cursor.execute(
    #             f"""
    #             SELECT Time, "{pressure_col}", "{rate_col}", "{sand_col}"
    #             FROM LogData
    #             WHERE Time IS NOT NULL
    #               AND viscosity IS NULL
    #               AND density IS NULL
    #             ORDER BY ID ASC
    #             """
    #         )
    #         sec_rows = cursor.fetchall()
    #
    #         sec_points = []
    #         last_dt_time = None
    #         sec_time_stamps = []
    #         for raw_time, raw_p, raw_r, raw_s in sec_rows:
    #             dt = _parse_time_to_datetime(raw_time, base_date, last_dt_time)
    #             if dt is None:
    #                 continue
    #             last_dt_time = dt
    #             qt_dt = QtCore.QDateTime(
    #                 dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second
    #             )
    #             ms = qt_dt.toMSecsSinceEpoch()
    #             try:
    #                 p_val = float(raw_p) if raw_p is not None else 0.0
    #             except (TypeError, ValueError):
    #                 p_val = 0.0
    #             try:
    #                 r_val = float(raw_r) if raw_r is not None else 0.0
    #             except (TypeError, ValueError):
    #                 r_val = 0.0
    #             try:
    #                 s_val = float(raw_s) if raw_s is not None else 0.0
    #             except (TypeError, ValueError):
    #                 s_val = 0.0
    #             sec_points.append((ms, p_val, r_val, s_val))
    #             sec_time_stamps.append(ms)
    #
    #         sec_points.sort(key=lambda x: x[0])
    #
    #         cursor.execute(
    #             """
    #             SELECT system_time, viscosity, density
    #             FROM LogData
    #             WHERE system_time IS NOT NULL
    #               AND viscosity IS NOT NULL
    #               AND density IS NOT NULL
    #             ORDER BY ID ASC
    #             """
    #         )
    #         visc_rows = cursor.fetchall()
    #
    #         visc_points = []
    #         last_dt_sys = None
    #         for raw_sys_time, raw_vis, _raw_den in visc_rows:
    #             dt = _parse_time_to_datetime(raw_sys_time, base_date, last_dt_sys)
    #             if dt is None:
    #                 continue
    #             last_dt_sys = dt
    #             qt_dt = QtCore.QDateTime(
    #                 dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second
    #             )
    #             ms = qt_dt.toMSecsSinceEpoch()
    #             try:
    #                 v = float(raw_vis)
    #             except (TypeError, ValueError):
    #                 continue
    #             visc_points.append((ms, v))
    #
    #         visc_points.sort(key=lambda x: x[0])
    #
    #         all_time_stamps = []
    #         pressure_values = []
    #         rate_values = []
    #         sand_ratio_values = []
    #         viscosity_values = []
    #
    #         for ms, p_val, r_val, s_val in sec_points:
    #             self.series_pressure.append(ms, p_val)
    #             self.series_rate.append(ms, r_val)
    #             self.series_sand_ratio.append(ms, s_val)
    #             all_time_stamps.append(ms)
    #             pressure_values.append(p_val)
    #             rate_values.append(r_val)
    #             sand_ratio_values.append(s_val)
    #
    #         for ms, v in visc_points:
    #             self.series_viscosity.append(ms, v)
    #             all_time_stamps.append(ms)
    #             viscosity_values.append(v)
    #
    #         if not all_time_stamps:
    #             cursor.close()
    #             conn.close()
    #             return
    #
    #         overall_x_min = min(all_time_stamps)
    #         overall_x_max = max(all_time_stamps)
    #
    #         if sec_time_stamps:
    #             view_x_min = min(sec_time_stamps)
    #             view_x_max = max(sec_time_stamps)
    #         else:
    #             view_x_min = overall_x_min
    #             view_x_max = overall_x_max
    #
    #         self.axis_time.setRange(
    #             QtCore.QDateTime.fromMSecsSinceEpoch(int(view_x_min)),
    #             QtCore.QDateTime.fromMSecsSinceEpoch(int(view_x_max)),
    #         )
    #
    #         if pressure_values:
    #             p_min = min(pressure_values)
    #             p_max = max(pressure_values)
    #             margin_p = (
    #                 (p_max - p_min) * 0.2
    #                 if p_max > p_min
    #                 else max(abs(p_max), 1.0) * 0.2
    #             )
    #             self.axis_pressure.setRange(p_min - margin_p, p_max + margin_p)
    #             p_range = (p_min - margin_p, p_max + margin_p)
    #         else:
    #             self.axis_pressure.setRange(0.0, 1.0)
    #             p_range = (0.0, 1.0)
    #
    #         combined_ys = rate_values + sand_ratio_values
    #         if combined_ys:
    #             rs_min = min(combined_ys)
    #             rs_max = max(combined_ys)
    #             margin_rs = (
    #                 (rs_max - rs_min) * 0.2
    #                 if rs_max > rs_min
    #                 else max(abs(rs_max), 1.0) * 0.2
    #             )
    #             self.axis_rate_sand.setRange(rs_min - margin_rs, rs_max + margin_rs)
    #             rs_range = (rs_min - margin_rs, rs_max + margin_rs)
    #         else:
    #             self.axis_rate_sand.setRange(0.0, 1.0)
    #             rs_range = (0.0, 1.0)
    #
    #         if viscosity_values:
    #             v_min = min(viscosity_values)
    #             v_max = max(viscosity_values)
    #             margin_v = (
    #                 (v_max - v_min) * 0.2
    #                 if v_max > v_min
    #                 else max(abs(v_max), 1.0) * 0.2
    #             )
    #             self.axis_viscosity.setRange(v_min - margin_v, v_max + margin_v)
    #             v_range = (v_min - margin_v, v_max + margin_v)
    #         else:
    #             self.axis_viscosity.setRange(0.0, 100.0)
    #             v_range = (0.0, 100.0)
    #
    #         y_ranges_list = [p_range, rs_range, v_range]
    #
    #         self.chart_view.set_full_ranges(
    #             x_min=overall_x_min,
    #             x_max=overall_x_max,
    #             y_ranges=y_ranges_list,
    #         )
    #
    #         loaded_any_valid_data = True
    #
    #         cursor.close()
    #         conn.close()
    #     except Exception as e:
    #         import traceback
    #         print("本地秒点曲线 load_full_data 出现异常：", e)
    #         traceback.print_exc()
    #     finally:
    #         self._is_loading = False
    #
    #     # 若是“手动刷新”（非定时器）、本次确实加载到有效数据、且当前 db 尚未开启自动刷新，则启动定时轮询
    #     if (
    #         loaded_any_valid_data
    #         and not self._loading_from_timer
    #         and not self._auto_refresh_started_for_current_db
    #     ):
    #         self._auto_refresh_timer.start()
    #         self._auto_refresh_started_for_current_db = True