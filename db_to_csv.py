# -*- coding: utf-8 -*-
"""
将串口转传产生的 .db 文件中的 LogData 表导出为 CSV 文件。
CSV 文件保存在 db 文件所在目录下的 csv 子目录中，主文件名与 db 相同，扩展名为 .csv。
列名来自数据库表结构（PRAGMA table_info(LogData)）。
"""
import csv
import os
import sqlite3
def get_csv_path_from_db_path(db_path):
    """
    根据 db 文件路径得到 csv 文件路径：db 同目录下的 csv 子目录、同主文件名、.csv。
    例如：C:/a_transmission_data/华H136-6/华H136-6第1次压裂7第11段.db
      -> C:/a_transmission_data/华H136-6/csv/华H136-6第1次压裂7第11段.csv
    """
    if not db_path or not str(db_path).strip():
        return None
    path = str(db_path).strip()
    if path.lower().endswith(".db"):
        base = path[:-3]
    else:
        base = path
    db_dir = os.path.dirname(os.path.abspath(os.path.normpath(path)))
    csv_dir = os.path.join(db_dir, "csv")
    name = os.path.basename(base) + ".csv"
    return os.path.join(csv_dir, name)


def db_to_csv(db_path, csv_path=None, encoding="utf-8-sig", newline=""):
    """
    将指定 db 文件中的 LogData 表导出为 CSV 文件。

    参数：
        db_path: SQLite .db 文件路径（与 LocalPlotWidget 使用的 db_path 一致）。
        csv_path: 可选。若不传则使用 db 所在目录下的 csv 子目录、同主文件名、扩展名为 .csv 的文件。
        encoding: 写入 CSV 的编码，默认 utf-8-sig（带 BOM，便于 Excel 正确识别中文）。
        newline: 写文件时的 newline 参数，默认 ""，避免 csv writer 多写换行。

    返回：
        成功时返回生成的 CSV 文件绝对路径（字符串）。

    异常：
        FileNotFoundError: db_path 文件不存在。
        ValueError: db_path 为空、或数据库中不存在 LogData 表。
        sqlite3.Error: 数据库访问错误。
    """
    if not db_path or not str(db_path).strip():
        raise ValueError("db_path 不能为空")

    db_path = os.path.abspath(os.path.normpath(str(db_path).strip()))
    if not os.path.isfile(db_path):
        raise FileNotFoundError("数据库文件不存在: {}".format(db_path))

    if csv_path is None:
        csv_path = get_csv_path_from_db_path(db_path)
    else:
        csv_path = os.path.abspath(os.path.normpath(str(csv_path).strip()))

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='LogData'"
        )
        if cursor.fetchone() is None:
            raise ValueError("当前数据库中不存在 LogData 表")

        cursor.execute("PRAGMA table_info(LogData)")
        columns_info = cursor.fetchall()
        column_names = [row[1] for row in columns_info]
        if not column_names:
            raise ValueError("LogData 表无列信息")

        cursor.execute("SELECT * FROM LogData ORDER BY ID ASC")
        rows = cursor.fetchall()
    finally:
        conn.close()

    csv_dir = os.path.dirname(csv_path)
    if csv_dir and not os.path.isdir(csv_dir):
        os.makedirs(csv_dir, exist_ok=True)

    with open(csv_path, "w", encoding=encoding, newline=newline) as f:
        writer = csv.writer(f)
        writer.writerow(column_names)
        for row in rows:
            writer.writerow(["" if cell is None else cell for cell in row])

    return csv_path


def db_to_csv_string(db_path, encoding="utf-8"):
    """
    将 LogData 表导出为 CSV 格式的字符串（不写文件），便于在界面中直接显示或解析填表。

    参数：
        db_path: SQLite .db 文件路径。
        encoding: 仅用于解码时（本函数返回 str，不涉及文件编码）。

    返回：
        str: CSV 内容字符串（首行为列名，后续为数据行）。

    异常：
        与 db_to_csv 相同。
    """
    import io

    if not db_path or not str(db_path).strip():
        raise ValueError("db_path 不能为空")

    db_path = os.path.abspath(os.path.normpath(str(db_path).strip()))
    if not os.path.isfile(db_path):
        raise FileNotFoundError("数据库文件不存在: {}".format(db_path))

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='LogData'"
        )
        if cursor.fetchone() is None:
            raise ValueError("当前数据库中不存在 LogData 表")

        cursor.execute("PRAGMA table_info(LogData)")
        columns_info = cursor.fetchall()
        column_names = [row[1] for row in columns_info]
        if not column_names:
            raise ValueError("LogData 表无列信息")

        cursor.execute("SELECT * FROM LogData ORDER BY ID ASC")
        rows = cursor.fetchall()
    finally:
        conn.close()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(column_names)
    for row in rows:
        writer.writerow(["" if cell is None else cell for cell in row])

    return buf.getvalue()

# def get_processed_log_data(db_path):
#     """
#     从 LogData 读取数据，按 system_time 将粘度行合并到同 system_time 的秒点行；
#     若粘度的 system_time 与任一秒点行都不同，则保留为单独一行。
#     返回 (display_headers, rows)，用于表格显示和保存 CSV。
#     display_headers: ['时间','套管压力','套管排量','砂比','粘度','system_time']
#     rows: list of list，每行 6 个元素（与 display_headers 对应）。
#     """
#     if not db_path or not str(db_path).strip():
#         raise ValueError("db_path 不能为空")
#     db_path = os.path.abspath(os.path.normpath(str(db_path).strip()))
#     if not os.path.isfile(db_path):
#         raise FileNotFoundError("数据库文件不存在: {}".format(db_path))
#
#     conn = sqlite3.connect(db_path)
#     try:
#         cursor = conn.cursor()
#         cursor.execute(
#             "SELECT name FROM sqlite_master WHERE type='table' AND name='LogData'"
#         )
#         if cursor.fetchone() is None:
#             raise ValueError("当前数据库中不存在 LogData 表")
#         cursor.execute("PRAGMA table_info(LogData)")
#         columns_info = cursor.fetchall()
#         column_names = [row[1] for row in columns_info]
#         if not column_names:
#             raise ValueError("LogData 表无列信息")
#
#         need_cols = ['ID', 'Time', '套管压力', '套管排量', '砂比', 'viscosity', 'density', 'system_time']
#         missing = [c for c in need_cols if c not in column_names]
#         if missing:
#             raise ValueError("LogData 表缺少列: {}".format(', '.join(missing)))
#
#         cursor.execute(
#             "SELECT ID, Time, 套管压力, 套管排量, 砂比, viscosity, density, system_time FROM LogData ORDER BY ID ASC"
#         )
#         raw_rows = cursor.fetchall()
#     finally:
#         conn.close()
#
#     # 秒点行：有 Time 或 套管压力/套管排量/砂比 中任一非空
#     sec_rows = []   # (id, time, 套管压力, 套管排量, 砂比, viscosity, density, system_time)
#     visc_only = []  # (id, system_time, viscosity, density)
#     for r in raw_rows:
#         rid, t, p, q, s, visc, dens, st = r
#         has_sec = (t is not None and str(t).strip()) or (p is not None) or (q is not None) or (s is not None)
#         has_visc = visc is not None and st is not None and str(st).strip()
#         if has_sec:
#             sec_rows.append([rid, t, p, q, s, visc, dens, st])
#         if has_visc:
#             visc_only.append([rid, st, visc, dens])
#
#     # 按 system_time 把粘度合并进秒点行
#     st_to_visc = {}
#     for _, st, v, d in visc_only:
#         st_key = str(st).strip() if st else ''
#         if st_key not in st_to_visc:
#             st_to_visc[st_key] = []
#         st_to_visc[st_key].append((v, d))
#
#     # 为每个秒点行填粘度（同 system_time 取最后一个粘度）
#     for row in sec_rows:
#         st = row[7]
#         st_key = str(st).strip() if st else ''
#         if st_key in st_to_visc and st_to_visc[st_key]:
#             v, d = st_to_visc[st_key][-1]
#             row[5], row[6] = v, d
#             st_to_visc[st_key] = []
#
#     # 未匹配的粘度行单独成行（时间、套管压力、套管排量、砂比为空，粘度和 system_time 有值）
#     display_headers = ['时间', '套管压力', '套管排量', '砂比', '粘度', 'system_time']
#     out_rows = []
#     for row in sec_rows:
#         t, p, q, s, visc, dens, st = row[1], row[2], row[3], row[4], row[5], row[6], row[7]
#         out_rows.append([_cell_str(t), _cell_str(p), _cell_str(q), _cell_str(s), _cell_str(visc), _cell_str(st)])
#
#     for st_key, rest in st_to_visc.items():
#         for v, d in rest:
#             out_rows.append(['', '', '', '', _cell_str(v), st_key])
#
#     # 按原始 ID 顺序稳定排序：秒点行已在前面，未匹配粘度行按 visc_only 顺序（可再按 ID 排）
#     return display_headers, out_rows

def get_processed_log_data(db_path):
    """
    从 LogData 读取数据，按 system_time 将粘度行合并到同 system_time 的秒点行；
    若粘度的 system_time 与任一秒点行都不同，则保留为单独一行。

    修改点：
    - 最终输出按 (system_time, ID) 升序稳定排序（最新在底部）。
    - 合并规则不变：只有 system_time 完全一致才合并；同秒多条粘度取最后一条（按 ID 最后）。
    """
    if not db_path or not str(db_path).strip():
        raise ValueError("db_path 不能为空")
    db_path = os.path.abspath(os.path.normpath(str(db_path).strip()))
    if not os.path.isfile(db_path):
        raise FileNotFoundError("数据库文件不存在: {}".format(db_path))

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='LogData'")
        if cursor.fetchone() is None:
            raise ValueError("当前数据库中不存在 LogData 表")

        cursor.execute("PRAGMA table_info(LogData)")
        columns_info = cursor.fetchall()
        column_names = [row[1] for row in columns_info]
        if not column_names:
            raise ValueError("LogData 表无列信息")

        need_cols = ['ID', 'Time', '套管压力', '套管排量', '砂比', 'viscosity', 'density', 'system_time']
        missing = [c for c in need_cols if c not in column_names]
        if missing:
            raise ValueError("LogData 表缺少列: {}".format(', '.join(missing)))

        cursor.execute(
            "SELECT ID, Time, 套管压力, 套管排量, 砂比, viscosity, density, system_time "
            "FROM LogData ORDER BY ID ASC"
        )
        raw_rows = cursor.fetchall()
    finally:
        conn.close()

    # 先分类
    sec_rows = []   # [id, time, p, q, s, viscosity, density, system_time]
    visc_only = []  # [id, system_time, viscosity, density]
    for r in raw_rows:
        rid, t, p, q, s, visc, dens, st = r
        has_sec = (t is not None and str(t).strip()) or (p is not None) or (q is not None) or (s is not None)
        has_visc = visc is not None and st is not None and str(st).strip()
        if has_sec:
            sec_rows.append([rid, t, p, q, s, visc, dens, st])
        if has_visc:
            visc_only.append([rid, st, visc, dens])

    # system_time -> [(id, viscosity, density), ...]（按 ID 升序追加）
    st_to_visc = {}
    for vid, st, v, d in visc_only:
        st_key = str(st).strip() if st else ''
        if st_key not in st_to_visc:
            st_to_visc[st_key] = []
        st_to_visc[st_key].append((vid, v, d))

    # 秒点行合并同秒粘度：同 system_time 取最后一条（id 最大）
    for row in sec_rows:
        st = row[7]
        st_key = str(st).strip() if st else ''
        if st_key in st_to_visc and st_to_visc[st_key]:
            vid, v, d = st_to_visc[st_key][-1]
            row[5], row[6] = v, d
            st_to_visc[st_key] = []  # 清空，表示已被“消费合并”

    display_headers = ['时间', '套管压力', '套管排量', '砂比', '粘度', 'system_time']

    # 构造“可排序的行”：
    # 统一用 (system_time, id) 做稳定排序键。
    sortable = []

    # 1) 秒点行（含已合并的粘度）
    for row in sec_rows:
        rid, t, p, q, s, visc, dens, st = row
        st_key = _cell_str(st)
        sortable.append((
            st_key, rid,
            [_cell_str(t), _cell_str(p), _cell_str(q), _cell_str(s), _cell_str(visc), st_key]
        ))

    # 2) 未匹配粘度行（单独成行）
    for st_key, rest in st_to_visc.items():
        for vid, v, d in rest:
            st_clean = _cell_str(st_key)
            sortable.append((
                st_clean, vid,
                ['', '', '', '', _cell_str(v), st_clean]
            ))

    # 排序：system_time（字符串） + ID（数字）升序
    # 注意：system_time 为空的行（若存在）会排到最前；通常你的粘度行不会为空。
    sortable.sort(key=lambda x: (x[0], x[1]))

    out_rows = [item[2] for item in sortable]
    return display_headers, out_rows


def _cell_str(cell):
    if cell is None:
        return ''
    s = str(cell).strip()
    return '' if s.lower() == 'none' else s


def write_processed_csv(header, rows, csv_path, encoding="utf-8-sig", newline=""):
    """将处理后的表头和数据写入 CSV 文件。"""
    import csv as _csv
    csv_dir = os.path.dirname(csv_path)
    if csv_dir and not os.path.isdir(csv_dir):
        os.makedirs(csv_dir, exist_ok=True)
    with open(csv_path, "w", encoding=encoding, newline=newline) as f:
        w = _csv.writer(f)
        w.writerow(header)
        for row in rows:
            w.writerow(row)
    return csv_path