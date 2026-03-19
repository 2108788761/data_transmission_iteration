# coding=gb2312
import os

from PyQt5 import *
from PyQt5 import Qt

import login
from OpenExeWindow import OpenExeWindow
import requests
from PyQt5.QtWidgets import *
# 登录窗口的类
class LoginWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)  # 调用父类构造函数，创建窗体
        self.ui = login.Ui_MainWindow()  # 创建UI对象
        self.ui.setupUi(self)  # 构造UI界面
        self.jwt_token = ''
        # 登录按钮！
        self.ui.pushButton.clicked.connect(self.login_success)
        company = ['中石油煤层气公司']
        for item in company:
            self.ui.comboBox.addItem(item)
        # self.ui.comboBox.setCurrentIndex(-1)
        self.ui.lineEdit_username.setText('test1'),
        self.ui.lineEdit_pwd.setText('h46ZWtvD?U&;'),
    def login_success(self):
        # 获取当前电脑CPU序列号
        cpu_serial_number = ''
        with os.popen('wmic cpu get processorid') as p:
            for line in p.readlines():
                if line.strip() and line.strip() != "ProcessorId":
                    cpu_serial_number = line.strip()
        print("CPU序列号:", cpu_serial_number)
        # 获取当前电脑MAC地址
        import uuid
        mac = uuid.uuid1().hex[-12:]
        mac_address = ':'.join([mac[e:e + 2] for e in range(0, 12, 2)])
        if self.ui.lineEdit_username.text() == '':
            QMessageBox.information(self.ui.centralwidget, '提示', "请输入账号！")
            return
        elif self.ui.lineEdit_pwd.text() == '':
            QMessageBox.information(self.ui.centralwidget, '提示', "请输入密码！")
            return
        elif self.ui.comboBox.currentIndex() == -1:
            QMessageBox.information(self.ui.centralwidget, '提示', "请选择油田！")
            return
        print('MAC地址:', mac_address)
        # login_url = "http://localhost:8000/api/v2/token/"
        login_url = "http://39.101.202.11/api/v2/token/"
        # login_url = "http://10.51.50.77:55555/api/v2/token/"
        # login_url = "http://10.51.50.99/api/v2/token/"

        # 用户认证信息2
        auth_info = {
            'username': self.ui.lineEdit_username.text(),
            'password': self.ui.lineEdit_pwd.text(),
            'company': self.ui.comboBox.currentText(),  # 油田信息
        }

        # 发送POST请求到登录接口，增加超时设置和异常处理
        try:
            # 发送POST请求到登录接口
            response = requests.post(login_url, json=auth_info, timeout=10)
            # 检查响应状态码
            if response.status_code == 200:
                res_json = response.json()
                if res_json.get('code'):  # 后端认证出错了，返回错误编码了
                    code = res_json.get('code')
                    mes = res_json.get('data')
                    QMessageBox.warning(self.ui.centralwidget, '警告', mes)
                    return
                else:   # 认证通过，返回access
                    # 提取JWT Token
                    jwt_token = response.json().get('access')  # 假设Token在响应的JSON中的键是'access'
                    print("JWT Token obtained:", jwt_token)
                    self.jwt_token = jwt_token

                    # 开启新的窗口
                    self.main_window = OpenExeWindow(self.jwt_token)
                    self.main_window.show()
                    # 当前窗口关闭
                    self.close()
            else:
                print(f"认证失败，状态码: {response.status_code}")
                print("Failed to authenticate:", response.text)
                QMessageBox.warning(self.ui.centralwidget, '认证失败',
                                    f"服务器返回错误: {response.status_code}")

        except requests.exceptions.Timeout:
            QMessageBox.warning(self.ui.centralwidget, '网络错误',
                                "连接超时，请检查网络连接或稍后重试！")
        except requests.exceptions.ConnectionError:
            QMessageBox.warning(self.ui.centralwidget, '网络错误',
                                "无法连接到服务器，请检查网络连接和服务器地址！")
        except requests.exceptions.RequestException as e:
            QMessageBox.warning(self.ui.centralwidget, '网络错误',
                                f"网络请求失败: {str(e)}")
        except Exception as e:
            QMessageBox.warning(self.ui.centralwidget, '错误',
                                f"发生未知错误: {str(e)}")
        finally:
            QApplication.restoreOverrideCursor()


