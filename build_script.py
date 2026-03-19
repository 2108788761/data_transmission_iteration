import os
import shutil
import subprocess
import sys
import glob

import ast
import importlib
import pkgutil
from pathlib import Path


class DependencyAnalyzer:
    """自动分析项目依赖"""

    @staticmethod
    def analyze_file(file_path):
        """分析单个文件的导入"""
        imports = set()

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            tree = ast.parse(content)

            for node in ast.walk(tree):
                # import module
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.add(alias.name.split('.')[0])  # 取顶级模块

                # from module import something
                elif isinstance(node, ast.ImportFrom):
                    if node.module:  # node.module 可能为 None
                        imports.add(node.module.split('.')[0])  # 取顶级模块

        except Exception as e:
            print(f"分析文件 {file_path} 出错: {e}")

        return imports

    @staticmethod
    def get_all_submodules(module_name):
        """获取模块的所有子模块"""
        submodules = set()

        try:
            # 尝试导入模块
            module = importlib.import_module(module_name)

            # 获取包路径
            if hasattr(module, '__file__') and module.__file__:
                module_path = Path(module.__file__).parent

                # 遍历包中的所有模块
                for _, name, is_pkg in pkgutil.iter_modules([str(module_path)]):
                    full_name = f"{module_name}.{name}"
                    submodules.add(full_name)

                    # 如果是包，递归获取子模块
                    if is_pkg:
                        submodules.update(DependencyAnalyzer.get_all_submodules(full_name))

        except ImportError:
            # 如果模块不存在，尝试获取可能的子模块名称
            submodules.add(module_name)
            # 添加常见子模块模式
            common_subs = [
                f"{module_name}.core",
                f"{module_name}.utils",
                f"{module_name}.tools",
                f"{module_name}.models",
                f"{module_name}.constants",
            ]
            submodules.update(common_subs)
        except Exception as e:
            print(f"获取 {module_name} 子模块出错: {e}")

        return submodules

    @staticmethod
    def expand_imports(imports):
        """扩展导入，包含可能的子模块"""
        expanded = set()

        for imp in imports:
            expanded.add(imp)
            # 对于第三方模块，添加可能的子模块
            if imp not in ['os', 'sys', 'json', 'time', 'datetime', 're', 'collections']:
                expanded.update(DependencyAnalyzer.get_all_submodules(imp))

        return sorted(expanded)


def analyze_project_dependencies():
    """分析整个项目的依赖"""
    print("=" * 60)
    print("分析项目依赖")
    print("=" * 60)

    analyzer = DependencyAnalyzer()
    all_imports = set()

    # 分析所有 .py 文件
    py_files = list(Path('.').glob('*.py'))

    print(f"分析 {len(py_files)} 个 Python 文件:")
    for py_file in py_files:
        if py_file.name.startswith('_'):
            continue

        file_imports = analyzer.analyze_file(py_file)
        if file_imports:
            print(f"  {py_file.name}: {sorted(file_imports)}")
            all_imports.update(file_imports)

    # 扩展导入
    expanded_imports = analyzer.expand_imports(all_imports)

    # 过滤掉标准库（如果需要的话）
    std_lib = {
        'os', 'sys', 'json', 'time', 'datetime', 're', 'collections',
        'typing', 'logging', 'math', 'statistics', 'functools', 'itertools',
        'hashlib', 'base64', 'random', 'string', 'pathlib', 'shutil', 'glob',
        'subprocess', 'threading', 'multiprocessing', 'queue', 'concurrent',
        'ssl', 'socket', 'urllib', 'http', 'email', 'csv', 'configparser',
        'xml', 'html', 'sqlite3', 'zipfile', 'tarfile', 'pickle', 'shelve',
        'decimal', 'fractions', 'numbers', 'array', 'struct', 'copy', 'pprint'
    }

    third_party = sorted([imp for imp in expanded_imports if imp.split('.')[0] not in std_lib])

    print(f"\n检测到的第三方依赖 ({len(third_party)} 个):")
    for i, imp in enumerate(third_party, 1):
        print(f"  {i:3d}. {imp}")

    return third_party

def generate_complete_hidden_imports():
    """生成完整的 hidden_imports 列表"""

    # 从分析中获取依赖
    detected_deps = analyze_project_dependencies()

    # 基础必须包含的模块（即使分析可能漏掉）
    base_imports = [
        # === 串口相关 ===
        "serial",
        "serial.tools",
        "serial.tools.list_ports",
        "serial.tools.list_ports_common",
        "serial.tools.list_ports_windows",
        "serial.tools.list_ports_linux",
        "serial.tools.list_ports_osx",
        "serial.serialutil",
        "serial.serialcli",
        "serial.serialjava",
        "serial.win32",
        "serial.rfc2217",
        "serial.threaded",
        "serial.urlhandler.protocol_rfc2217",
        "serial.urlhandler.protocol_socket",
        "serial.urlhandler.protocol_loop",
        "serial.urlhandler.protocol_cpes",

        # === 数据库相关 ===
        "pyodbc",
        "pyodbc.drivers",

        # === 数据处理 ===
        "pandas",
        "pandas._libs",
        "pandas._libs.tslibs",
        "pandas.core",
        "pandas.core.dtypes",
        "pandas.core.internals",
        "pandas.core.arrays",
        "pandas.io",
        "pandas.io.clipboard",
        "pandas.io.common",
        "pandas.io.formats",
        "pandas.io.json",
        "pandas.io.pytables",
        "pandas.io.sas",
        "pandas.io.spss",
        "pandas.io.sql",
        "pandas.io.stata",
        "pandas.io.xml",
        "pandas.plotting",
        "pandas.errors",
        "pandas.api",
        "pandas.api.extensions",
        "pandas.api.indexers",
        "pandas.api.types",
        "pandas.api.interchange",

        # === numpy 相关 ===
        "numpy",
        "numpy.core",
        "numpy.core._multiarray_umath",
        "numpy.core._dtype_ctypes",
        "numpy.core._multiarray_tests",
        "numpy.core._exceptions",
        "numpy.core._methods",
        "numpy.core._string_helpers",
        "numpy.core.arrayprint",
        "numpy.core.defchararray",
        "numpy.core.einsumfunc",
        "numpy.core.fromnumeric",
        "numpy.core.function_base",
        "numpy.core.getlimits",
        "numpy.core.memmap",
        "numpy.core.multiarray",
        "numpy.core.numeric",
        "numpy.core.numerictypes",
        "numpy.core.overrides",
        "numpy.core.records",
        "numpy.core.shape_base",
        "numpy.lib",
        "numpy.lib._datasource",
        "numpy.lib._iotools",
        "numpy.lib._version",
        "numpy.lib.arraypad",
        "numpy.lib.arraysetops",
        "numpy.lib.arrayterator",
        "numpy.lib.financial",
        "numpy.lib.format",
        "numpy.lib.histogramtools",
        "numpy.lib.index_tricks",
        "numpy.lib.mixins",
        "numpy.lib.nanfunctions",
        "numpy.lib.npyio",
        "numpy.lib.polynomial",
        "numpy.lib.scimath",
        "numpy.lib.stride_tricks",
        "numpy.lib.twodim_base",
        "numpy.lib.type_check",
        "numpy.lib.ufunclike",
        "numpy.lib.utils",
        "numpy.fft",
        "numpy.linalg",
        "numpy.linalg.lapack_lite",
        "numpy.random",
        "numpy.random._common",
        "numpy.random._generator",
        "numpy.random._mt19937",
        "numpy.random._pcg64",
        "numpy.random._philox",
        "numpy.random._sfc64",
        "numpy.random.bit_generator",
        "numpy.random.mtrand",
        "numpy.ma",

        # === 日期时间 ===
        "pytz",
        "dateutil",
        "dateutil.parser",
        "dateutil.relativedelta",
        "dateutil.tz",
        "dateutil.easter",
        "dateutil._version",
        "dateutil.utils",
        "dateutil.zoneinfo",

        # === PyQt5 系列 ===
        "PyQt5",
        "PyQt5.QtCore",
        "PyQt5.QtGui",
        "PyQt5.QtWidgets",
        "PyQt5.QtNetwork",
        "PyQt5.QtPrintSupport",
        "PyQt5.QtSerialPort",
        "PyQt5.QtSql",
        "PyQt5.QtTest",
        "PyQt5.QtWebEngine",
        "PyQt5.QtWebEngineCore",
        "PyQt5.QtWebEngineWidgets",
        "PyQt5.QtWebChannel",
        "PyQt5.QtXml",
        "PyQt5.QtXmlPatterns",
        "PyQt5.sip",
        "PyQt5.uic",
        "PyQt5.uic.widget-plugins",

        # === 系统操作 ===
        "wmi",
        "psutil",
        "psutil._common",
        "psutil._compat",
        "psutil._pswindows",
        "psutil._psutil_windows",

        # === 网络请求 ===
        "requests",
        "requests.adapters",
        "requests.auth",
        "requests.certs",
        "requests.compat",
        "requests.cookies",
        "requests.exceptions",
        "requests.hooks",
        "requests.models",
        "requests.packages",
        "requests.sessions",
        "requests.status_codes",
        "requests.structures",
        "requests.utils",
        "urllib3",
        "urllib3.connection",
        "urllib3.connectionpool",
        "urllib3.contrib",
        "urllib3.contrib.pyopenssl",
        "urllib3.contrib.socks",
        "urllib3.exceptions",
        "urllib3.fields",
        "urllib3.filepost",
        "urllib3.packages",
        "urllib3.packages.backports",
        "urllib3.packages.six",
        "urllib3.poolmanager",
        "urllib3.request",
        "urllib3.response",
        "urllib3.util",
        "urllib3.util.connection",
        "urllib3.util.proxy",
        "urllib3.util.queue",
        "urllib3.util.request",
        "urllib3.util.response",
        "urllib3.util.retry",
        "urllib3.util.ssl_",
        "urllib3.util.timeout",
        "urllib3.util.url",
        "urllib3.util.wait",

        # === 其他常用第三方 ===
        "decimal",
        "openpyxl",
        "openpyxl.chart",
        "openpyxl.chart.axis",
        "openpyxl.chart.bar_chart",
        "openpyxl.chart.bubble_chart",
        "openpyxl.chart.line_chart",
        "openpyxl.chart.pie_chart",
        "openpyxl.chart.pivot",
        "openpyxl.chart.radar_chart",
        "openpyxl.chart.reference",
        "openpyxl.chart.scatter_chart",
        "openpyxl.chart.series",
        "openpyxl.chart.stock_chart",
        "openpyxl.chart.surface_chart",
        "openpyxl.chart.title",
        "openpyxl.comments",
        "openpyxl.comments.comment_sheet",
        "openpyxl.comments.author",
        "openpyxl.comments.shape_writer",
        "openpyxl.descriptors",
        "openpyxl.descriptors.base",
        "openpyxl.descriptors.excel",
        "openpyxl.descriptors.nested",
        "openpyxl.descriptors.serialisable",
        "openpyxl.drawing",
        "openpyxl.drawing.colors",
        "openpyxl.drawing.fill",
        "openpyxl.drawing.geometry",
        "openpyxl.drawing.graphic",
        "openpyxl.drawing.line",
        "openpyxl.drawing.picture",
        "openpyxl.drawing.spreadsheet_drawing",
        "openpyxl.drawing.text",
        "openpyxl.formatting",
        "openpyxl.formatting.rule",
        "openpyxl.formula",
        "openpyxl.formula.translate",
        "openpyxl.packaging",
        "openpyxl.packaging.core",
        "openpyxl.packaging.extended",
        "openpyxl.packaging.manifest",
        "openpyxl.packaging.relationship",
        "openpyxl.packaging.workbook",
        "openpyxl.reader",
        "openpyxl.reader.excel",
        "openpyxl.styles",
        "openpyxl.styles.alignment",
        "openpyxl.styles.borders",
        "openpyxl.styles.colors",
        "openpyxl.styles.differential",
        "openpyxl.styles.fills",
        "openpyxl.styles.fonts",
        "openpyxl.styles.named_styles",
        "openpyxl.styles.numbers",
        "openpyxl.styles.protection",
        "openpyxl.styles.proxy",
        "openpyxl.styles.table",
        "openpyxl.utils",
        "openpyxl.utils.bound_dictionary",
        "openpyxl.utils.cell",
        "openpyxl.utils.datetime",
        "openpyxl.utils.exceptions",
        "openpyxl.utils.indexed_list",
        "openpyxl.utils.inference",
        "openpyxl.utils.units",
        "openpyxl.workbook",
        "openpyxl.workbook.child",
        "openpyxl.workbook.defined_name",
        "openpyxl.workbook.external_link",
        "openpyxl.workbook.function_group",
        "openpyxl.workbook.properties",
        "openpyxl.workbook.protection",
        "openpyxl.workbook.smart_tags",
        "openpyxl.workbook.views",
        "openpyxl.workbook.web",
        "openpyxl.worksheet",
        "openpyxl.worksheet._reader",
        "openpyxl.worksheet._writer",
        "openpyxl.worksheet.cell_range",
        "openpyxl.worksheet.cell_watch",
        "openpyxl.worksheet.datavalidation",
        "openpyxl.worksheet.dimensions",
        "openpyxl.worksheet.filters",
        "openpyxl.worksheet.formula",
        "openpyxl.worksheet.header_footer",
        "openpyxl.worksheet.hyperlink",
        "openpyxl.worksheet.merge",
        "openpyxl.worksheet.page",
        "openpyxl.worksheet.pagebreak",
        "openpyxl.worksheet.properties",
        "openpyxl.worksheet.protection",
        "openpyxl.worksheet.related",
        "openpyxl.worksheet.scenario",
        "openpyxl.worksheet.table",
        "openpyxl.worksheet.views",
        "openpyxl.writer",
        "openpyxl.writer.excel",
        "openpyxl.xml",
        "openpyxl.xml.constants",
        "openpyxl.xml.functions",

        # === 图像处理 ===
        "PIL",
        "PIL.Image",
        "PIL.ImageChops",
        "PIL.ImageCms",
        "PIL.ImageColor",
        "PIL.ImageDraw",
        "PIL.ImageDraw2",
        "PIL.ImageEnhance",
        "PIL.ImageFile",
        "PIL.ImageFilter",
        "PIL.ImageFont",
        "PIL.ImageGrab",
        "PIL.ImageMath",
        "PIL.ImageMode",
        "PIL.ImageMorph",
        "PIL.ImageOps",
        "PIL.ImagePalette",
        "PIL.ImagePath",
        "PIL.ImageQt",
        "PIL.ImageSequence",
        "PIL.ImageShow",
        "PIL.ImageStat",
        "PIL.ImageTk",
        "PIL.ImageWin",
        "PIL._imaging",
        "PIL._imagingcms",
        "PIL._imagingft",
        "PIL._imagingmath",
        "PIL._imagingtk",
        "PIL._webp",
        "matplotlib",
        "matplotlib._animation_data",
        "matplotlib._api",
        "matplotlib._cm",
        "matplotlib._color_data",
        "matplotlib._constrained_layout",
        "matplotlib._docstring",
        "matplotlib._enums",
        "matplotlib._fontconfig_pattern",
        "matplotlib._layoutgrid",
        "matplotlib._pylab_helpers",
        "matplotlib._tight_bbox",
        "matplotlib._tight_layout",
        "matplotlib._tri",
        "matplotlib.afm",
        "matplotlib.animation",
        "matplotlib.artist",
        "matplotlib.axes",
        "matplotlib.axis",
        "matplotlib.backend_bases",
        "matplotlib.backend_managers",
        "matplotlib.backend_tools",
        "matplotlib.backends",
        "matplotlib.backends.backend_agg",
        "matplotlib.backends.backend_cairo",
        "matplotlib.backends.backend_gtk3agg",
        "matplotlib.backends.backend_gtk3cairo",
        "matplotlib.backends.backend_gtk4agg",
        "matplotlib.backends.backend_gtk4cairo",
        "matplotlib.backends.backend_nbagg",
        "matplotlib.backends.backend_pdf",
        "matplotlib.backends.backend_ps",
        "matplotlib.backends.backend_qtagg",
        "matplotlib.backends.backend_qtcairo",
        "matplotlib.backends.backend_svg",
        "matplotlib.backends.backend_template",
        "matplotlib.backends.backend_tkagg",
        "matplotlib.backends.backend_webagg",
        "matplotlib.backends.backend_wxagg",
        "matplotlib.backends.backend_wxcairo",
        "matplotlib.backends.qt_editor",
        "matplotlib.bezier",
        "matplotlib.blocking_input",
        "matplotlib.category",
        "matplotlib.cbook",
        "matplotlib.cm",
        "matplotlib.collections",
        "matplotlib.colorbar",
        "matplotlib.container",
        "matplotlib.contour",
        "matplotlib.dates",
        "matplotlib.dviread",
        "matplotlib.figure",
        "matplotlib.font_manager",
        "matplotlib.fontconfig_pattern",
        "matplotlib.ft2font",
        "matplotlib.gridspec",
        "matplotlib.hatch",
        "matplotlib.image",
        "matplotlib.legend",
        "matplotlib.legend_handler",
        "matplotlib.lines",
        "matplotlib.markevery",
        "matplotlib.markers",
        "matplotlib.mathtext",
        "matplotlib.mlab",
        "matplotlib.offsetbox",
        "matplotlib.patches",
        "matplotlib.path",
        "matplotlib.pylab",
        "matplotlib.quiver",
        "matplotlib.rcsetup",
        "matplotlib.sankey",
        "matplotlib.scale",
        "matplotlib.sphinxext",
        "matplotlib.spines",
        "matplotlib.stackplot",
        "matplotlib.style",
        "matplotlib.table",
        "matplotlib.text",
        "matplotlib.textpath",
        "matplotlib.ticker",
        "matplotlib.tight_layout",
        "matplotlib.transforms",
        "matplotlib.tri",
        "matplotlib.type1font",
        "matplotlib.units",
        "matplotlib.widgets",

        # === 加密和安全 ===
        "cryptography",
        "cryptography.hazmat",
        "cryptography.hazmat.backends",
        "cryptography.hazmat.bindings",
        "cryptography.hazmat.primitives",
        "cryptography.x509",

        # === 日志和配置 ===
        "yaml",
        "toml",
        "configparser",
        "logging",
        "logging.config",
        "logging.handlers",

        # === Excel 处理 ===
        "xlrd",
        "xlwt",
        "xlsxwriter",

        # === 邮件处理 ===
        "smtplib",
        "email",
        "email.mime.text",
        "email.mime.multipart",
        "email.mime.application",
        "email.mime.image",
        "email.mime.audio",
        "email.mime.message",
        "email.mime.base",
        "email.header",
        "email.charset",
        "email.encoders",
        "email.utils",
        "email.iterators",
        "email.generator",
        "email.policy",
        "email.feedparser",

        # === 网络和通信 ===
        "socket",
        "ssl",
        "_ssl",
        "http",
        "http.client",
        "http.cookiejar",
        "http.cookies",
        "websocket",
        "websocket._abnf",
        "websocket._app",
        "websocket._core",
        "websocket._cookiejar",
        "websocket._exceptions",
        "websocket._handshake",
        "websocket._http",
        "websocket._logging",
        "websocket._socket",
        "websocket._ssl_compat",
        "websocket._url",
        "websocket._utils",
        "websocket.tests",

        # === 多线程和异步 ===
        "threading",
        "multiprocessing",
        "multiprocessing.connection",
        "multiprocessing.context",
        "multiprocessing.dummy",
        "multiprocessing.forkserver",
        "multiprocessing.heap",
        "multiprocessing.managers",
        "multiprocessing.pool",
        "multiprocessing.process",
        "multiprocessing.queues",
        "multiprocessing.reduction",
        "multiprocessing.resource_tracker",
        "multiprocessing.shared_memory",
        "multiprocessing.sharedctypes",
        "multiprocessing.spawn",
        "multiprocessing.synchronize",
        "multiprocessing.util",
        "concurrent",
        "concurrent.futures",
        "concurrent.futures._base",
        "concurrent.futures.process",
        "concurrent.futures.thread",
        "asyncio",
        "asyncio.base_events",
        "asyncio.base_subprocess",
        "asyncio.constants",
        "asyncio.coroutines",
        "asyncio.events",
        "asyncio.exceptions",
        "asyncio.format_helpers",
        "asyncio.futures",
        "asyncio.locks",
        "asyncio.log",
        "asyncio.proactor_events",
        "asyncio.protocols",
        "asyncio.queues",
        "asyncio.runners",
        "asyncio.selector_events",
        "asyncio.sslproto",
        "asyncio.staggered",
        "asyncio.streams",
        "asyncio.subprocess",
        "asyncio.taskgroups",
        "asyncio.tasks",
        "asyncio.transports",
        "asyncio.trsock",
        "asyncio.unix_events",
        "asyncio.windows_events",
        "asyncio.windows_utils",

        # === 数据处理和科学计算 ===
        "scipy",
        "sympy",
        "statsmodels",
        "sklearn",
        "tensorflow",
        "torch",
        "jax",

        # === 测试框架 ===
        "unittest",
        "unittest.mock",
        "unittest.async_case",
        "pytest",
        "doctest",
        "nose",

        # === 文档生成 ===
        "sphinx",
        "docutils",
        "pydoc",

        # === 打包和分发 ===
        "setuptools",
        "distutils",
        "wheel",
        "pip",

        # === 其他工具 ===
        "click",
        "typer",
        "rich",
        "tqdm",
        "progressbar",
        "colorama",
        "termcolor",
        "pygments",
        "markdown",
        "jinja2",
        "flask",
        "django",
        "fastapi",
        "bottle",
        "tornado",
        "aiohttp",
        "starlette",
        "uvicorn",
        "gunicorn",
        "celery",
        "redis",
        "pymongo",
        "sqlalchemy",
        "peewee",
        "dataset",
        "alembic",
        "marshmallow",
        "pydantic",
        "attrs",
        "dataclasses",
        "mypy",
        "pylint",
        "flake8",
        "black",
        "autopep8",
        "yapf",
        "isort",
        "rope",
        "jedi",
        "parso",
    ]

    # 合并所有导入
    all_imports = list(set(base_imports + detected_deps))
    all_imports.sort()

    return all_imports

def simple_encrypt_build(names):
    """批量加密构建"""
    print("开始批量加密构建...")

    # 清理旧的加密文件和构建产物
    cleanup_items = ["build", "dist"]

    # 清理旧的.pyd文件
    for name in names:
        pyd_files = glob.glob(f"{name}.*.pyd")
        for pyd in pyd_files:
            try:
                os.remove(pyd)
                print(f"已删除旧的加密文件: {pyd}")
            except Exception as e:
                print(f"删除 {pyd} 失败: {e}")

    for folder in cleanup_items:
        if os.path.exists(folder):
            shutil.rmtree(folder)
            print(f"已清理目录: {folder}")

    # 批量加密
    for name in names:
        print(f"加密 {name}.py ...")
        try:
            result = subprocess.run([
                sys.executable, "-c",
                f"from distutils.core import setup; "
                f"from Cython.Build import cythonize; "
                f"setup(ext_modules=cythonize('{name}.py', "
                f"compiler_directives={{'language_level': 3}}))",
                "build_ext", "--inplace"
            ], check=True, capture_output=True, text=True)
            print(f"✓ {name}.py 加密成功")
        except subprocess.CalledProcessError as e:
            print(f"✗ {name}.py 加密失败: {e.stderr}")
            return False

    print("所有文件加密完成！")
    return True


def find_encrypt_files(names):
    """查找加密文件并进行验证"""
    arr = []

    for name in names:
        # 查找.pyd文件（支持不同平台的后缀）
        patterns = [
            f"{name}.*.pyd",  # Windows
            f"{name}.*.so",  # Linux/Mac
        ]

        found = False
        for pattern in patterns:
            pyd_files = glob.glob(pattern)
            if pyd_files:
                pyd_file = max(pyd_files, key=os.path.getmtime)  # 取最新的
                if os.path.exists(pyd_file):
                    print(f"✓ 找到加密文件: {pyd_file}")
                    arr.append(pyd_file)
                    found = True
                    break

        if not found:
            print(f"✗ 未找到 {name} 的加密文件")
            # 尝试查找其他可能的文件
            all_files = glob.glob(f"{name}.*")
            if all_files:
                print(f"  找到的相关文件: {all_files}")
            return None

    if len(arr) != len(names):
        print(f"警告: 只找到 {len(arr)}/{len(names)} 个加密文件")

    return arr


def dabao(main_file, encrypt_files):
    """打包主程序"""
    if not encrypt_files:
        print("错误: 没有可用的加密文件")
        return False

    print(f"开始打包，主文件: {main_file}.py")

    # 构建命令
    cmd = [
        "pyinstaller",
        "--name=QtTestApp",
        # "--windowed",
        "--console",
        "--onefile",
        "--clean",  # 清理缓存
    ]

    # 添加加密文件
    for ef in encrypt_files:
        cmd.extend(["--add-data", f"{ef};."])

    # 添加必要的隐式导入 - 特别注意添加 pyodbc
    # 添加必要的隐式导入 - 特别注意添加 serial (pyserial)
    hidden_imports = [
            # 第三方模块（PyInstaller 可能无法自动检测的）
            "pyodbc",  # import pyodbc
            "pandas",  # import pandas as pd
            "requests",  # import requests
            "serial",  # import serial
            "serial.tools.list_ports",  # import serial.tools.list_ports
            "crcmod",  # from crcmod import crcmod
            "numpy",  # import numpy as np

            # PyQt5 子模块（需要明确指定）
            "PyQt5.QtWebSockets",  # from PyQt5.QtWebSockets import QWebSocket
            "PyQt5.QtNetwork",  # from PyQt5.QtNetwork import QNetworkRequest

            # PyQt5 核心模块（通常需要）
            "PyQt5.QtCore",
            "PyQt5.QtGui",
            "PyQt5.QtWidgets",

            # 你的自定义模块（如果 PyInstaller 找不到）
            "uploadMainWindow",  # import uploadMainWindow
            "login",  # import login

            # 确保包含可能动态导入的模块
            "sqlite3",  # import sqlite3（虽然是标准库，但确保包含）
            "configparser",  # import configparser
            "csv",  # import csv
            "json",  # import json
            "struct",  # import struct
            "datetime",  # import datetime

            # requests 可能需要的子模块
            "requests.auth",
            "requests.models",
            "requests.sessions",
            "urllib3",  # requests 的依赖

            # pandas 可能需要的子模块
            "numpy.core",  # pandas 依赖 numpy
            "pytz",  # pandas 可能用到
            "dateutil",  # pandas 可能用到

            # pyodbc 可能需要
            "pyodbc.drivers",

            # serial 的其他常用子模块
            "serial.tools",
            "serial.serialutil",

            # 网络相关
            "socket",  # import socket
    ]

    for hi in hidden_imports:
        cmd.extend(["--hidden-import", hi])

    # 添加主文件
    cmd.append(f"{main_file}.py")

    # 添加图标和版本信息（如果有的话）
    if os.path.exists("icon.ico"):
        cmd.extend(["--icon", "icon.ico"])

    print("打包命令:", " ".join(cmd))
    print("打包中...")

    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("✅ 打包完成！")
        print(f"可执行文件位置: dist/QtTestApp.exe")

        # 检查生成的文件大小
        exe_path = "dist/QtTestApp.exe"
        if os.path.exists(exe_path):
            size = os.path.getsize(exe_path) / (1024 * 1024)
            print(f"生成文件大小: {size:.2f} MB")

        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ 打包失败: {e.stderr}")
        return False


def main(encrypt_files, main_file):
    """主函数"""
    print("=" * 50)
    print("Cython 加密打包工具")
    print("=" * 50)

    # 1. 加密
    print("\n步骤 1: 批量加密")
    if not simple_encrypt_build(encrypt_files):
        print("加密失败，退出")
        return

    # 2. 查找加密文件
    print("\n步骤 2: 查找加密文件")
    found_files = find_encrypt_files(encrypt_files)
    if not found_files:
        print("找不到加密文件，退出")
        return

    # 3. 打包
    print("\n步骤 3: 打包")
    if dabao(main_file, found_files):
        print("\n🎉 全部完成！")
    else:
        print("\n❌ 打包失败")


if __name__ == "__main__":
    # 加密模块
    encrypt_files = ['OpenExeWindow', 'thread', 'LoginWindow', 'login', 'uploadMainWindow']
    # 入口文件
    main_file = 'Run'
    main(encrypt_files, main_file)

