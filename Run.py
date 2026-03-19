# coding=gb2312
import sys
from PyQt5.QtWidgets import QApplication
# 直接导入主窗口类
from OpenExeWindow import OpenExeWindow
if __name__ == '__main__':
    app = QApplication(sys.argv)
    # 单机版：不再走登录流程，直接创建主窗口
    # 目前 OpenExeWindow 仍然接收一个 jwt_token 参数，这里传入一个占位字符串，例如 'LOCAL'
    main_window = OpenExeWindow(jwt_token='LOCAL')
    main_window.show()
    sys.exit(app.exec_())