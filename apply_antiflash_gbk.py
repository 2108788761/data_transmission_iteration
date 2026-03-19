# -*- coding: utf-8 -*-
# Apply doc section 11 anti-crash to this project. Read/write GBK only. No new Chinese comments.
# Run from: e:\BW\IDEA\data_transmission_iteration
import os
import sys

ENC = 'gbk'
BASE = os.path.dirname(os.path.abspath(__file__))

def patch_openexe():
    path = os.path.join(BASE, 'OpenExeWindow.py')
    with open(path, 'r', encoding=ENC) as f:
        s = f.read()

    # 1) __init__: after self.water_file_path = '' add 4 thread = None
    old1 = "        self.water_file_path = ''\n        # 初始化数据 函数"
    new1 = "        self.water_file_path = ''\n        self.receiver_thread = None\n        self.worker_thread = None\n        self.receiver_viscosity_thread = None\n        self.receive_water_thread = None\n        # 初始化数据 函数"
    if old1 in s:
        s = s.replace(old1, new1, 1)
        print('OpenExeWindow: added 4 thread=None in __init__')
    else:
        print('OpenExeWindow: __init__ block not found (skip or already done)')

    # 2) end_upload: receiver_thread check
    s = s.replace("        if self.receiver_thread.isRunning():", "        if self.receiver_thread is not None and self.receiver_thread.isRunning():")
    # 3) end_upload: worker_thread check and terminate
    s = s.replace("                    if self.worker_thread.isRunning():\n                        self.worker_thread.terminate()  # 终止线程\n                        print('向服务器发送数据线程已关闭')",
                  "                    if self.worker_thread is not None and self.worker_thread.isRunning():\n                        self.worker_thread.terminate()  # 终止线程\n                        print('向服务器发送数据线程已关闭')")
    # 4) end_upload_tab4
    s = s.replace("                if self.worker_thread.isRunning():\n                    self.worker_thread.stop()  # 终止线程",
                  "                if self.worker_thread is not None and self.worker_thread.isRunning():\n                    self.worker_thread.stop()  # 终止线程")
    # 5) thread_finished / thread_finished_2 / thread_finished_3: guard terminate
    s = s.replace("        self.worker_thread.terminate()  # 终止线程\n        self.point_1 = point_1",
                  "        if self.worker_thread is not None:\n            self.worker_thread.terminate()  # 终止线程\n        self.point_1 = point_1")
    s = s.replace("        self.worker_thread.terminate()  # 终止线程\n        self.viscosity_point_1 = point_1",
                  "        if self.worker_thread is not None:\n            self.worker_thread.terminate()  # 终止线程\n        self.viscosity_point_1 = point_1")
    s = s.replace("        self.worker_thread.terminate()  # 终止线程\n        self.water_point_1 = point_1",
                  "        if self.worker_thread is not None:\n            self.worker_thread.terminate()  # 终止线程\n        self.water_point_1 = point_1")
    # 6) end_upload_viscosity_data
    old_vis = "    def end_upload_viscosity_data(self):\n        # 创建一个确认弹窗\n        print(self.receiver_viscosity_thread.isRunning())\n        if self.receiver_viscosity_thread.isRunning():"
    new_vis = "    def end_upload_viscosity_data(self):\n        # 创建一个确认弹窗\n        if self.receiver_viscosity_thread is not None:\n            print(self.receiver_viscosity_thread.isRunning())\n        if self.receiver_viscosity_thread is not None and self.receiver_viscosity_thread.isRunning():"
    if old_vis in s:
        s = s.replace(old_vis, new_vis, 1)
    s = s.replace("                    if self.Upload_Viscosity_Thread.isRunning():",
                  "                    if getattr(self, 'Upload_Viscosity_Thread', None) is not None and self.Upload_Viscosity_Thread.isRunning():")
    # 7) end_upload_water_data
    old_w = "    def end_upload_water_data(self):\n        # 创建一个确认弹窗\n        print(self.receive_water_thread.isRunning())\n        if self.receive_water_thread.isRunning():"
    new_w = "    def end_upload_water_data(self):\n        # 创建一个确认弹窗\n        if self.receive_water_thread is not None:\n            print(self.receive_water_thread.isRunning())\n        if self.receive_water_thread is not None and self.receive_water_thread.isRunning():"
    if old_w in s:
        s = s.replace(old_w, new_w, 1)
    # 8) stop_receive_water_data
    s = s.replace("            if self.receive_water_thread.isRunning():", "            if self.receive_water_thread is not None and self.receive_water_thread.isRunning():")
    old_sw = "            self.btn_start_tab5.setEnabled(True)\n            self.btn_stop_tab5.setEnabled(False)\n            print(self.receive_water_thread.isRunning())"
    new_sw = "            self.btn_start_tab5.setEnabled(True)\n            self.btn_stop_tab5.setEnabled(False)\n            if self.receive_water_thread is not None:\n                print(self.receive_water_thread.isRunning())"
    if old_sw in s:
        s = s.replace(old_sw, new_sw, 1)
    # 9) stop_receive
    s = s.replace("            if self.receiver_thread.isRunning():", "            if self.receiver_thread is not None and self.receiver_thread.isRunning():")
    # 10) stop_receive_viscosity_data
    s = s.replace("            if self.receiver_viscosity_thread.isRunning():", "            if self.receiver_viscosity_thread is not None and self.receiver_viscosity_thread.isRunning():")
    old_sv = "            print('接收黏度/密度数据线程已关闭')\n            print(self.receiver_viscosity_thread.isRunning())"
    new_sv = "            print('接收黏度/密度数据线程已关闭')\n            if self.receiver_viscosity_thread is not None:\n                print(self.receiver_viscosity_thread.isRunning())"
    if old_sv in s:
        s = s.replace(old_sv, new_sv, 1)
    # receiver_thread_finished: no isRunning in IDEA version, only append. So no change.
    # But stop_receive has if self.receiver_thread.isRunning() - done above.

    with open(path, 'w', encoding=ENC) as f:
        f.write(s)
    print('OpenExeWindow.py written (GBK).')

def patch_thread():
    path = os.path.join(BASE, 'thread.py')
    with open(path, 'r', encoding=ENC) as f:
        s = f.read()

    # --- ReceiverThread ---
    # ser = None before try in run()
    old_ser = "        buffer = ''   # 缓存数据\n        try:\n            # 初始化串口\n            ser = serial.Serial(port, baudrate"
    new_ser = "        buffer = ''   # 缓存数据\n        ser = None\n        try:\n            # 初始化串口\n            ser = serial.Serial(port, baudrate"
    if old_ser in s:
        s = s.replace(old_ser, new_ser, 1)
        print('thread: ReceiverThread run() ser=None added')
    # except Exception + finally
    old_fin = "        except KeyboardInterrupt:\n            print(\"程序被用户终止。\")\n        finally:\n            if ser.is_open:\n                ser.close()  # 关闭串口\n                print(f\"串口 {port} 已关闭。\")\n                self.update_textEdit_2.emit(f\"串口 {port} 已关闭。\")\n\n    def stop(self):\n        self.running = False\n# 接收数据线程 粘度、密度数据\nclass ReceiverViscosityThread(QThread):"
    new_fin = "        except KeyboardInterrupt:\n            print(\"程序被用户终止。\")\n        except Exception as e:\n            print(f\"sec-point recv err: {e}\")\n            self.update_textEdit_2.emit(f\"sec-point recv err: {e}\")\n        finally:\n            if ser is not None and getattr(ser, 'is_open', False):\n                ser.close()  # 关闭串口\n                print(f\"串口 {port} 已关闭。\")\n                self.update_textEdit_2.emit(f\"串口 {port} 已关闭。\")\n\n    def stop(self):\n        self.running = False\n# 接收数据线程 粘度、密度数据\nclass ReceiverViscosityThread(QThread):"
    if old_fin in s:
        s = s.replace(old_fin, new_fin, 1)
        print('thread: ReceiverThread except Exception + finally fixed')
    else:
        print('thread: ReceiverThread finally block not found')

    # save_data wrap
    old_sd = "    def save_data(self, field_name, data, field_num):\n        file_name = self.cur_well + '第' + self.cur_frac_num + '次压裂' + self.cur_layer + '第' + self.cur_period + '段'\n        temp_file_path = 'C:/a_transmission_data/' + self.cur_well + '/' + file_name + '.db'\n        # temp_file_path = 'D:/a_transmission_data/' + self.cur_well + '/' + file_name + '.db'\n        cur_time = datetime.datetime.now()\n        system_time = cur_time.strftime(\"%H:%M:%S\")\n        data = data + (system_time,)\n        # 连接到数据库（如果数据库文件）\n        conn = sqlite3.connect(temp_file_path)\n        conn.execute('PRAGMA journal_mode=WAL')\n        # 创建一个游标对象，用于执行SQL语句\n        cursor = conn.cursor()\n        # 根据列数生成占位符\n        placeholders = \", \".join([\"?\"] * (len(field_name) + 2))\n        columns = ','.join(field_name)\n        print(data)\n        print((len(field_name) + 2))\n        if len(data) == len(field_name) + 2:\n            cursor.execute(f'INSERT INTO LogData (Time,{columns},system_time) VALUES ({placeholders})', data)\n            # 提交更改\n            conn.commit()\n\n            cursor.close()\n            conn.close()\n\n    def save_data_copy(self, field_name, data, field_num):"
    new_sd = "    def save_data(self, field_name, data, field_num):\n        try:\n            file_name = self.cur_well + '第' + self.cur_frac_num + '次压裂' + self.cur_layer + '第' + self.cur_period + '段'\n            temp_file_path = 'C:/a_transmission_data/' + self.cur_well + '/' + file_name + '.db'\n            # temp_file_path = 'D:/a_transmission_data/' + self.cur_well + '/' + file_name + '.db'\n            cur_time = datetime.datetime.now()\n            system_time = cur_time.strftime(\"%H:%M:%S\")\n            data = data + (system_time,)\n            # 连接到数据库（如果数据库文件）\n            conn = sqlite3.connect(temp_file_path)\n            conn.execute('PRAGMA journal_mode=WAL')\n            # 创建一个游标对象，用于执行SQL语句\n            cursor = conn.cursor()\n            # 根据列数生成占位符\n            placeholders = \", \".join([\"?\"] * (len(field_name) + 2))\n            columns = ','.join(field_name)\n            print(data)\n            print((len(field_name) + 2))\n            if len(data) == len(field_name) + 2:\n                cursor.execute(f'INSERT INTO LogData (Time,{columns},system_time) VALUES ({placeholders})', data)\n                # 提交更改\n                conn.commit()\n\n                cursor.close()\n                conn.close()\n        except (sqlite3.Error, OSError, Exception) as e:\n            print(f\"save_data err: {e}\")\n            self.update_textEdit_2.emit(f\"save_data err: {e}\")\n\n    def save_data_copy(self, field_name, data, field_num):"
    if old_sd in s:
        s = s.replace(old_sd, new_sd, 1)
        print('thread: ReceiverThread save_data wrapped')
    else:
        print('thread: save_data block not found (skip)')

    # save_data_copy wrap
    old_sc = "    def save_data_copy(self, field_name, data, field_num):\n        print('我执行了2')\n        print(field_num)\n\n        file_name = self.cur_well + '第' + self.cur_frac_num + '次压裂' + self.cur_layer + '第' + self.cur_period + '段'\n        temp_file_path = 'C:/a_transmission_data/' + self.cur_well + '/' + file_name + '.db'\n        # temp_file_path = 'D:/a_transmission_data/' + self.cur_well + '/' + file_name + '.db'\n\n        cur_time = datetime.datetime.now()\n        system_time = cur_time.strftime(\"%H:%M:%S\")\n        data = data + (system_time,)\n        # 连接到数据库（如果数据库文件）\n        conn = sqlite3.connect(temp_file_path)\n        conn.execute('PRAGMA journal_mode=WAL')\n        # 创建一个游标对象，用于执行SQL语句\n        cursor = conn.cursor()\n        columns = ','.join(field_name)\n        # 根据列数生成占位符\n        placeholders = \", \".join([\"?\"] * (len(field_name) + 2))\n        # 插入数据\n        # placeholders = ', '.join(['?'] * len(data))  # 生成问号占位符\n        field_num = field_num + 1\n        if len(data) == field_num:\n            cursor.execute(f'INSERT INTO LogData (Time,{columns},system_time) VALUES ({placeholders})', data)\n            # 提交更改\n            conn.commit()\n            # 关闭连接\n            cursor.close()\n            conn.close()\n            print(f'{data[0]}秒数据已保存到数据库文件中')\n        else:\n            cursor.close()\n            conn.close()\n        self.update_textEdit.emit(data[0])\n\n    def save_data_31(self, field_name, data, field_num, field_index):"
    new_sc = "    def save_data_copy(self, field_name, data, field_num):\n        try:\n            print('我执行了2')\n            print(field_num)\n\n            file_name = self.cur_well + '第' + self.cur_frac_num + '次压裂' + self.cur_layer + '第' + self.cur_period + '段'\n            temp_file_path = 'C:/a_transmission_data/' + self.cur_well + '/' + file_name + '.db'\n            # temp_file_path = 'D:/a_transmission_data/' + self.cur_well + '/' + file_name + '.db'\n\n            cur_time = datetime.datetime.now()\n            system_time = cur_time.strftime(\"%H:%M:%S\")\n            data = data + (system_time,)\n            # 连接到数据库（如果数据库文件）\n            conn = sqlite3.connect(temp_file_path)\n            conn.execute('PRAGMA journal_mode=WAL')\n            # 创建一个游标对象，用于执行SQL语句\n            cursor = conn.cursor()\n            columns = ','.join(field_name)\n            # 根据列数生成占位符\n            placeholders = \", \".join([\"?\"] * (len(field_name) + 2))\n            # 插入数据\n            # placeholders = ', '.join(['?'] * len(data))  # 生成问号占位符\n            field_num = field_num + 1\n            if len(data) == field_num:\n                cursor.execute(f'INSERT INTO LogData (Time,{columns},system_time) VALUES ({placeholders})', data)\n                # 提交更改\n                conn.commit()\n                # 关闭连接\n                cursor.close()\n                conn.close()\n                print(f'{data[0]}秒数据已保存到数据库文件中')\n            else:\n                cursor.close()\n                conn.close()\n            self.update_textEdit.emit(data[0])\n        except (sqlite3.Error, OSError, Exception) as e:\n            print(f\"save_data_copy err: {e}\")\n            self.update_textEdit_2.emit(f\"save_data_copy err: {e}\")\n\n    def save_data_31(self, field_name, data, field_num, field_index):"
    if old_sc in s:
        s = s.replace(old_sc, new_sc, 1)
        print('thread: ReceiverThread save_data_copy wrapped')
    else:
        print('thread: save_data_copy block not found (skip)')

    # save_data_31 wrap: add try at start and except at end before "    def run(self):"
    old_31 = "    def save_data_31(self, field_name, data, field_num, field_index):\n        file_name = self.cur_well + '第' + self.cur_frac_num + '次压裂' + self.cur_layer + '第' + self.cur_period + '段'\n        temp_file_path = 'C:/a_transmission_data/' + self.cur_well + '/' + file_name + '.db'\n        # temp_file_path = 'D:/a_transmission_data/' + self.cur_well + '/' + file_name + '.db'\n\n        # 连接到数据库（如果数据库文件）\n        conn = sqlite3.connect(temp_file_path)"
    new_31 = "    def save_data_31(self, field_name, data, field_num, field_index):\n        try:\n            file_name = self.cur_well + '第' + self.cur_frac_num + '次压裂' + self.cur_layer + '第' + self.cur_period + '段'\n            temp_file_path = 'C:/a_transmission_data/' + self.cur_well + '/' + file_name + '.db'\n            # temp_file_path = 'D:/a_transmission_data/' + self.cur_well + '/' + file_name + '.db'\n\n            # 连接到数据库（如果数据库文件）\n            conn = sqlite3.connect(temp_file_path)"
    if old_31 in s:
        s = s.replace(old_31, new_31, 1)
    old_31_end = "        else:\n            cursor.close()\n            conn.close()\n        self.update_textEdit.emit(data_end[0])\n\n    def run(self):\n        # 配置串口参数\n        # port = 'COM6'  # 请根据实际情况修改串口号\n        port = self.port_name  # 请根据实际情况修改串口号\n        baudrate = 9600  # 波特率\n        timeout = 1  # 超时设置\n        # 设置数据位、校验位和停止位\n        data_bits = 8  # 数据位（5, 6, 7, 或 8）\n        parity = serial.PARITY_NONE  # 校验位（无校验）\n        stop_bits = serial.STOPBITS_ONE  # 停止位（1位）\n        # 暂存字符串 处理串口发送数据的异常\n        temp_str = ''\n        # 发送的字段数量 还需要加上时间字段，字段数量+1\n        field_num = len(self.field_name) + 1\n        # 文件路径\n        file_path1 = f'C:/a_transmission_data/{self.cur_well}/{self.cur_well}第{self.cur_frac_num}次压裂{self.cur_layer}第{self.cur_period}段_AllData.txt'"
    new_31_end = "            else:\n                cursor.close()\n                conn.close()\n            self.update_textEdit.emit(data_end[0])\n        except (sqlite3.Error, OSError, Exception) as e:\n            print(f\"save_data_31 err: {e}\")\n            self.update_textEdit_2.emit(f\"save_data_31 err: {e}\")\n\n    def run(self):\n        # 配置串口参数\n        # port = 'COM6'  # 请根据实际情况修改串口号\n        port = self.port_name  # 请根据实际情况修改串口号\n        baudrate = 9600  # 波特率\n        timeout = 1  # 超时设置\n        # 设置数据位、校验位和停止位\n        data_bits = 8  # 数据位（5, 6, 7, 或 8）\n        parity = serial.PARITY_NONE  # 校验位（无校验）\n        stop_bits = serial.STOPBITS_ONE  # 停止位（1位）\n        # 暂存字符串 处理串口发送数据的异常\n        temp_str = ''\n        # 发送的字段数量 还需要加上时间字段，字段数量+1\n        field_num = len(self.field_name) + 1\n        # 文件路径\n        file_path1 = f'C:/a_transmission_data/{self.cur_well}/{self.cur_well}第{self.cur_frac_num}次压裂{self.cur_layer}第{self.cur_period}段_AllData.txt'"
    if old_31_end in s:
        s = s.replace(old_31_end, new_31_end, 1)
        print('thread: ReceiverThread save_data_31 wrapped')
    # Indent save_data_31 body (conn.execute ... etc) - we only added try and changed the else block; the middle part needs +4 spaces. Actually the old_31 only added "try:\n            " at the start. So everything from "        file_name" to "        else:" in save_data_31 must get 4 more spaces. That's many lines. Let me do a more targeted replace: only add the except block and fix the else indentation. So replace the exact "        else:\n            cursor.close()\n            conn.close()\n        self.update_textEdit.emit(data_end[0])\n\n    def run(self):" with the new version. I already did that in new_31_end. But the try block body in save_data_31 - we need to indent all lines between "conn = sqlite3.connect(temp_file_path)" and "        else:" by 4 spaces. That's error-prone in one big string. Alternative: do multiple small replacements to add 4 spaces to each logical block. Actually re-reading the code: in save_data_31 the structure is:
    #         file_name = ...
    #         temp_file_path = ...
    #         conn = ...
    #         conn.execute(...)
    #         cursor = ...
    #         columns = ...
    #         placeholders = ...
    #         cur_time = ...
    #         data_ = ...
    #         for i in field_index: ... (with try/except inside)
    #         current_time_ = ...
    #         data_end = ...
    #         field_num = field_num + 1
    #         if len(data_end) == field_num:
    #             cursor.execute(...)
    #             conn.commit()
    #             cursor.close()
    #             conn.close()
    #             print(...)
    #         else:
    #             cursor.close()
    #             conn.close()
    #         self.update_textEdit.emit(data_end[0])
    # So we need to add 4 spaces to every line from "        conn.execute" to "        self.update_textEdit.emit(data_end[0])". That's a lot. Let me do one big replace that includes the full method body with correct indentation. I already added "try:\n            " before the first line (file_name). So now the line "        file_name" became "            file_name" in new_31 - no, in new_31 we have "        try:\n            file_name", so file_name has 12 spaces. But the original had "        file_name" (8 spaces). So we need the entire body from file_name to "        self.update_textEdit.emit" to be indented with 4 more spaces. The replace I did only replaced the first few lines. So the rest of save_data_31 (conn.execute, cursor, etc.) still has 8 spaces - they should have 12. So we need a second replace that indents the block. Actually the simplest is: replace the whole save_data_31 method with a version that has try + indented body + except. Let me read the file again and build the exact string. Actually in Python, the method body has 8 spaces. If we add "try:\n" we need the body to have 12 spaces. So every line that starts with "        " (8 spaces) in the method body should become "            " (12 spaces). So I need to replace in save_data_31 from the line after "conn = sqlite3.connect" through "self.update_textEdit.emit(data_end[0])" - add 4 spaces. Let me do a simpler approach: replace line by line the critical part. Actually the first replace old_31 only added "try:\n            " before "file_name = ". So now we have:
    #         try:
    #             file_name = ...
    #             temp_file_path = ...
    #             (rest unchanged - still 8 spaces) conn = ...
    # So conn, cursor, etc. are still 8 spaces - they need to be 12. So I need another replace that adds 4 spaces to each line from "        conn.execute" to "        self.update_textEdit.emit". Let me do that by replacing a contiguous block.
    old_mid = "        conn.execute('PRAGMA journal_mode=WAL')\n        # 创建一个游标对象，用于执行SQL语句\n        cursor = conn.cursor()\n        columns = ','.join(field_name)\n        # 根据列数生成占位符\n        placeholders = \", \".join([\"?\"] * (len(field_name)+2))\n        cur_time = datetime.datetime.now()\n        current_time = cur_time.strftime(\"%Y-%m-%d %H:%M:%S\")\n        data_ = [current_time]\n        for i in field_index:\n            # data_.append(data[i-1])\n            try:\n                # 尝试获取data[i-1]，如果索引超出范围则返回0\n                value = data[i - 1] if (i - 1) < len(data) else 0\n                data_.append(value)\n            except IndexError:\n                # 记录错误日志（可选）\n                print(f\"警告: 数据索引 {i - 1} 超出范围(数据长度={len(data)})，已使用默认值0\")\n                data_.append(0)\n        current_time_ = cur_time.strftime(\"%H:%M:%S\")\n        data_.append(current_time_)\n        data_end = tuple(data_)\n        # 插入数据\n        # placeholders = ', '.join(['?'] * len(data))  # 生成问号占位符\n        field_num = field_num + 1\n        if len(data_end) == field_num:\n            cursor.execute(f'INSERT INTO LogData (Time,{columns},system_time) VALUES ({placeholders})', data_end)\n            # 提交更改\n            conn.commit()\n            # 关闭连接\n            cursor.close()\n            conn.close()\n            print(f'{data_end[0]}秒数据已保存到数据库文件中')\n        else:\n            cursor.close()\n            conn.close()\n        self.update_textEdit.emit(data_end[0])"
    new_mid = "            conn.execute('PRAGMA journal_mode=WAL')\n            # 创建一个游标对象，用于执行SQL语句\n            cursor = conn.cursor()\n            columns = ','.join(field_name)\n            # 根据列数生成占位符\n            placeholders = \", \".join([\"?\"] * (len(field_name)+2))\n            cur_time = datetime.datetime.now()\n            current_time = cur_time.strftime(\"%Y-%m-%d %H:%M:%S\")\n            data_ = [current_time]\n            for i in field_index:\n                # data_.append(data[i-1])\n                try:\n                    # 尝试获取data[i-1]，如果索引超出范围则返回0\n                    value = data[i - 1] if (i - 1) < len(data) else 0\n                    data_.append(value)\n                except IndexError:\n                    # 记录错误日志（可选）\n                    print(f\"警告: 数据索引 {i - 1} 超出范围(数据长度={len(data)})，已使用默认值0\")\n                    data_.append(0)\n            current_time_ = cur_time.strftime(\"%H:%M:%S\")\n            data_.append(current_time_)\n            data_end = tuple(data_)\n            # 插入数据\n            # placeholders = ', '.join(['?'] * len(data))  # 生成问号占位符\n            field_num = field_num + 1\n            if len(data_end) == field_num:\n                cursor.execute(f'INSERT INTO LogData (Time,{columns},system_time) VALUES ({placeholders})', data_end)\n                # 提交更改\n                conn.commit()\n                # 关闭连接\n                cursor.close()\n                conn.close()\n                print(f'{data_end[0]}秒数据已保存到数据库文件中')\n            else:\n                cursor.close()\n                conn.close()\n            self.update_textEdit.emit(data_end[0])"
    if old_mid in s:
        s = s.replace(old_mid, new_mid, 1)
        print('thread: save_data_31 body indented')

    # --- ReceiverViscosityThread ---
    old_v1 = "        file_path1 = f'{self.file_path.split(\".\")[0]}_viscosity_AllData.txt'\n\n        try:\n            # 初始化串口\n            ser = serial.Serial(port, baudrate"
    new_v1 = "        file_path1 = f'{self.file_path.split(\".\")[0]}_viscosity_AllData.txt'\n        ser = None\n        try:\n            # 初始化串口\n            ser = serial.Serial(port, baudrate"
    if old_v1 in s:
        s = s.replace(old_v1, new_v1, 1)
        print('thread: ReceiverViscosityThread ser=None added')
    old_v2 = "                except Exception as e:\n                    self.update_textEdit.emit(f\"通信错误: {str(e)}\")\n        except serial.SerialException as e:\n            self.update_textEdit.emit(f'打开黏/密度串口错误: {e}')\n            print(f\"串口错误: {e}\")\n        except KeyboardInterrupt:\n            print(\"程序被用户终止。\")\n        finally:\n            if ser.is_open:\n                ser.close()  # 关闭串口\n                print(f\"串口 {port} 已关闭。\")\n                self.update_textEdit.emit(f\"串口 {port} 已关闭。\")\n\n    def stop(self):\n        self.running = False\n# 上传数据 线程 粘度、密度数据\nclass UploadViscosityThread(QThread):"
    new_v2 = "                except Exception as e:\n                    self.update_textEdit.emit(f\"通信错误: {str(e)}\")\n        except Exception as e:\n            self.update_textEdit.emit(f'viscosity recv err: {e}')\n            print(f\"viscosity recv err: {e}\")\n        except serial.SerialException as e:\n            self.update_textEdit.emit(f'打开黏/密度串口错误: {e}')\n            print(f\"串口错误: {e}\")\n        except KeyboardInterrupt:\n            print(\"程序被用户终止。\")\n        finally:\n            if ser is not None and getattr(ser, 'is_open', False):\n                ser.close()  # 关闭串口\n                print(f\"串口 {port} 已关闭。\")\n                self.update_textEdit.emit(f\"串口 {port} 已关闭。\")\n\n    def stop(self):\n        self.running = False\n# 上传数据 线程 粘度、密度数据\nclass UploadViscosityThread(QThread):"
    if old_v2 in s:
        s = s.replace(old_v2, new_v2, 1)
        print('thread: ReceiverViscosityThread except Exception + finally fixed')
    else:
        print('thread: ReceiverViscosityThread finally block not found')

    # ReceiverViscosityThread save_data wrap
    old_vs = "    def save_data(self, data):\n        temp_file_path = self.file_path\n        # 连接到数据库（如果数据库文件）\n        conn = sqlite3.connect(temp_file_path)\n        # 创建一个游标对象，用于执行SQL语句\n        cursor = conn.cursor()\n\n        # 根据列数生成占位符\n        placeholders = \", \".join([\"?\"] * (len(data)))\n        # 插入数据\n        cursor.execute(f'INSERT INTO LogData (viscosity,density,system_time) VALUES ({placeholders})', data)\n        # 提交更改\n        conn.commit()\n        # print(f\"No matching record found for viscosity_time={data[-1]}\")\n        # # 检查是否存在匹配的 time 记录\n        # cursor.execute('SELECT ID FROM LogData WHERE system_time = ?', (data[-1],))\n        # existing_record = cursor.fetchone()\n        #\n        # if existing_record:\n        #     # 如果找到匹配的记录，更新 viscosity 和 density\n        #     cursor.execute('''\n        #             UPDATE LogData\n        #             SET viscosity = ?, density = ?\n        #             WHERE system_time = ?\n        #         ''', (data[0], data[1], data[-1]))\n        #     conn.commit()\n        #     print(f\"Updated record with viscosity_time={data[-1]}\")\n        # else:\n        #     # 根据列数生成占位符\n        #     placeholders = \", \".join([\"?\"] * (len(data)))\n        #     # 插入数据\n        #     cursor.execute(f'INSERT INTO LogData (viscosity,density,system_time ) VALUES ({placeholders})', data)\n        #     # 提交更改\n        #     conn.commit()\n        #     print(f\"No matching record found for viscosity_time={data[-1]}\")\n        # 关闭连接\n        cursor.close()\n        conn.close()\n\n        # temp_file_path = self.file_path"
    new_vs = "    def save_data(self, data):\n        try:\n            temp_file_path = self.file_path\n            # 连接到数据库（如果数据库文件）\n            conn = sqlite3.connect(temp_file_path)\n            # 创建一个游标对象，用于执行SQL语句\n            cursor = conn.cursor()\n\n            # 根据列数生成占位符\n            placeholders = \", \".join([\"?\"] * (len(data)))\n            # 插入数据\n            cursor.execute(f'INSERT INTO LogData (viscosity,density,system_time) VALUES ({placeholders})', data)\n            # 提交更改\n            conn.commit()\n            # print(f\"No matching record found for viscosity_time={data[-1]}\")\n            # # 检查是否存在匹配的 time 记录\n            # cursor.execute('SELECT ID FROM LogData WHERE system_time = ?', (data[-1],))\n            # existing_record = cursor.fetchone()\n            #\n            # if existing_record:\n            #     # 如果找到匹配的记录，更新 viscosity 和 density\n            #     cursor.execute('''\n            #             UPDATE LogData\n            #             SET viscosity = ?, density = ?\n            #             WHERE system_time = ?\n            #         ''', (data[0], data[1], data[-1]))\n            #     conn.commit()\n            #     print(f\"Updated record with viscosity_time={data[-1]}\")\n            # else:\n            #     # 根据列数生成占位符\n            #     placeholders = \", \".join([\"?\"] * (len(data)))\n            #     # 插入数据\n            #     cursor.execute(f'INSERT INTO LogData (viscosity,density,system_time ) VALUES ({placeholders})', data)\n            #     # 提交更改\n            #     conn.commit()\n            #     print(f\"No matching record found for viscosity_time={data[-1]}\")\n            # 关闭连接\n            cursor.close()\n            conn.close()\n        except (sqlite3.Error, OSError, Exception) as e:\n            print(f\"viscosity save_data err: {e}\")\n            self.update_textEdit.emit(f\"viscosity save_data err: {e}\")\n\n        # temp_file_path = self.file_path"
    if old_vs in s:
        s = s.replace(old_vs, new_vs, 1)
        print('thread: ReceiverViscosityThread save_data wrapped')
    else:
        print('thread: ReceiverViscosityThread save_data block not found (skip)')

    with open(path, 'w', encoding=ENC) as f:
        f.write(s)
    print('thread.py written (GBK).')

if __name__ == '__main__':
    patch_openexe()
    patch_thread()
    print('Done. Encoding used: GBK only.')
