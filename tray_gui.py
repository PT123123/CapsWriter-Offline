import sys
import os
import logging
import subprocess
import threading
import psutil
import traceback
import signal

try:
    from PyQt5.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QAction, QMainWindow, QTextEdit, QVBoxLayout, QWidget, QTabWidget, QLabel, QPushButton, QHBoxLayout
    from PyQt5.QtGui import QIcon, QTextCursor, QMouseEvent
    from PyQt5.QtCore import Qt, pyqtSignal, QObject, QTimer, QPoint
except ImportError as e:
    print(e)
    sys.exit(1)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('tray_gui.log', encoding='utf-8')
    ]
)

# 设置未捕获异常处理器
def handle_exception(exc_type, exc_value, exc_traceback):
    logging.error("未捕获的异常:", exc_info=(exc_type, exc_value, exc_traceback))
    logging.error("异常堆栈跟踪:\n%s", ''.join(traceback.format_tb(exc_traceback)))

sys.excepthook = handle_exception

# 设置信号处理器
def signal_handler(signum, frame):
    logging.error(f"收到信号 {signum}，程序即将退出")
    logging.error(f"堆栈跟踪:\n{''.join(traceback.format_stack(frame))}")
    sys.exit(1)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGABRT, signal_handler)

# 获取程序运行目录
BASE_DIR = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
def get_icon_path():
    try:
        # 首先尝试从PyInstaller打包后的资源目录加载
        if getattr(sys, 'frozen', False):
            icon_path = os.path.join(sys._MEIPASS, "assets", "icon.ico")
        else:
            # 开发环境下从当前目录加载
            icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.ico")
        
        if not os.path.exists(icon_path):
            logging.error(f"图标文件不存在：{icon_path}")
            # 尝试在其他可能的位置查找图标
            alt_paths = [
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.ico"),
                os.path.join(os.getcwd(), "assets", "icon.ico")
            ]
            for alt_path in alt_paths:
                if os.path.exists(alt_path):
                    logging.info(f"使用备选图标路径：{alt_path}")
                    return alt_path
            raise FileNotFoundError(f"无法找到图标文件，已尝试的路径：{[icon_path] + alt_paths}")
        return icon_path
    except Exception as e:
        logging.error(f"获取图标路径时出错：{str(e)}")
        return None

class LogHandler(logging.Handler):
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget
    
    def emit(self, record):
        try:
            msg = self.format(record)
            if hasattr(self.text_widget, 'append'):
                self.text_widget.append(msg)
        except RuntimeError:
            # Widget was deleted, remove this handler
            logging.getLogger().removeHandler(self)

class LogEmitter(QObject):
    log_signal = pyqtSignal(str)  # 修改为只传递字符串
    
    def __init__(self):
        super().__init__()
        
    def emit_log(self, message):
        self.log_signal.emit(str(message))  # 确保传递的是字符串

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # 设置无边框窗口
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        
        # 设置暗色调色板
        palette = self.palette()
        palette.setColor(palette.Window, Qt.GlobalColor.black)
        palette.setColor(palette.WindowText, Qt.GlobalColor.white)
        self.setPalette(palette)
        
        # 用于窗口拖动的变量
        self._drag_pos = None
                
        # 初始化进程监控定时器
        self.process_monitor = QTimer()
        self.process_monitor.timeout.connect(self.check_processes)
        self.process_monitor.start(1000)  # 每秒检查一次进程状态
        
        # 设置暗色主题样式
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #121212;
                color: #e0e0e0;
            }
            QMainWindow::title {
                background-color: #1e1e1e;
                color: #e0e0e0;
            }
            QMainWindow::titlebar {
                background-color: #1e1e1e;
            }
            QMainWindow::titlebar-button {
                background-color: #2d2d2d;
                border: none;
                padding: 2px;
                margin: 2px;
            }
            QMainWindow::titlebar-button:hover {
                background-color: #404040;
            }
            QMainWindow::titlebar-close-button,
            QMainWindow::titlebar-normal-button,
            QMainWindow::titlebar-min-button,
            QMainWindow::titlebar-max-button {
                background-color: #2d2d2d;
            }
            QMainWindow::titlebar-close-button:hover,
            QMainWindow::titlebar-normal-button:hover,
            QMainWindow::titlebar-min-button:hover,
            QMainWindow::titlebar-max-button:hover {
                background-color: #404040;
            }
            QTextEdit {
                background-color: #1e1e1e;
                color: #e0e0e0;
                border: 1px solid #333;
            }
            QTabWidget::pane {
                border: 1px solid #333;
                background-color: #1e1e1e;
            }
            QTabWidget::tab-bar {
                left: 5px;
            }
            QTabBar::tab {
                background-color: #1e1e1e;
                color: #e0e0e0;
                padding: 8px 12px;
                margin-right: 2px;
                border: 1px solid #333;
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background-color: #2d2d2d;
                border-bottom: none;
            }
            QTabBar::tab:!selected {
                margin-top: 2px;
            }
        """)
        
        self.log_emitter = LogEmitter()
        self.server_process = None
        self.client_process = None
        self.server_emitter = LogEmitter()
        self.client_emitter = LogEmitter()
        self.setWindowTitle("CapsWriter-Offline")
        self.setMinimumSize(800, 600)
        
        # 创建UI组件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 创建自定义标题栏
        title_bar = QWidget()
        title_bar.setFixedHeight(32)
        title_bar.setStyleSheet("""
            QWidget {
                background-color: #1e1e1e;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QPushButton {
                background-color: transparent;
                border: none;
                color: #e0e0e0;
                padding: 4px 8px;
                font-family: "Segoe MDL2 Assets";
                font-size: 10px;
            }
            QPushButton:hover {
                background-color: #404040;
            }
            QPushButton#close_button:hover {
                background-color: #c42b1c;
            }
        """)
        
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(8, 0, 0, 0)
        title_layout.setSpacing(0)
        
        # 标题文本
        title_label = QLabel("CapsWriter-Offline")
        title_label.setStyleSheet("color: #e0e0e0; font-size: 12px;")
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        
        # 最小化、最大化、关闭按钮
        min_button = QPushButton("🗕")
        min_button.clicked.connect(self.showMinimized)
        max_button = QPushButton("🗖")
        max_button.clicked.connect(self.toggle_maximize)
        close_button = QPushButton("🗙")
        close_button.setObjectName("close_button")
        close_button.clicked.connect(self.hide)
        
        title_layout.addWidget(min_button)
        title_layout.addWidget(max_button)
        title_layout.addWidget(close_button)
        
        layout.addWidget(title_bar)
        
        # 内容容器
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(1, 0, 1, 1)  # 添加边框效果
        content_widget.setStyleSheet("""
            QWidget {
                background-color: #121212;
                border: 1px solid #333;
                border-top: none;
            }
        """)
        layout.addWidget(content_widget)
        
        # 创建标签页
        self.tab_widget = QTabWidget()
        self.server_log = QTextEdit()
        self.server_log.setReadOnly(True)
        self.client_log = QTextEdit()
        self.client_log.setReadOnly(True)
        
        self.tab_widget.addTab(self.server_log, "服务端日志")
        self.tab_widget.addTab(self.client_log, "客户端日志")
        content_layout.addWidget(self.tab_widget)
        
        # 初始化日志处理器
        self.server_emitter = LogEmitter()
        self.client_emitter = LogEmitter()
        self.server_emitter.log_signal.connect(self.append_server_log)
        self.client_emitter.log_signal.connect(self.append_client_log)
        
        # 添加初始等待提示
        self.client_log.append("正在等待服务端启动...")
        self.client_log.append("请耐心等待，首次加载可能需要较长时间")
        self.client_log.moveCursor(QTextCursor.End)
    def append_server_log(self, message):
        self.server_log.append(message)
        self.server_log.moveCursor(QTextCursor.End)
        if "------------------------ 开始服务 ----------" in message:
            self.start_client()
            
    def append_client_log(self, message):
        self.client_log.append(message)
        self.client_log.moveCursor(QTextCursor.End)
        
    def start_client(self):
        # 启动客户端进程
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf8'
        self.client_process = subprocess.Popen(
            [os.path.join(BASE_DIR, "start_client.exe")],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            env=env,
            bufsize=1
        )
        
        def read_client_output(stream, emitter):
            for line in iter(stream.readline, ''):
                logging.info(f"[Client] {line.strip()}")
                emitter.emit_log(line.strip())
            stream.close()
            
        threading.Thread(target=read_client_output, args=(self.client_process.stdout, self.client_emitter), daemon=True).start()
        threading.Thread(target=read_client_output, args=(self.client_process.stderr, self.client_emitter), daemon=True).start()
        self.client_emitter.emit_log("客户端启动成功，开始加载模型...")
        

        
        # 确保日志处理器只添加一次
        if not any(isinstance(h, LogHandler) for h in logging.getLogger().handlers):
            logging.getLogger().addHandler(LogHandler(self.client_log))
        
        try:
            self.setWindowIcon(QIcon(ICON_PATH))
        except Exception as e:
            logging.error(f"设置窗口图标失败：{str(e)}")
        
    def check_processes(self):
        # 检查服务端进程状态
        if self.server_process and self.server_process.poll() is not None:
            exit_code = self.server_process.poll()
            logging.error(f"服务端进程异常退出，退出码: {exit_code}")
            if exit_code != 0:
                self.server_log.append(f"警告：服务端进程异常退出，退出码: {exit_code}")
                self.server_log.moveCursor(QTextCursor.End)

        # 检查客户端进程状态
        if self.client_process and self.client_process.poll() is not None:
            exit_code = self.client_process.poll()
            logging.error(f"客户端进程异常退出，退出码: {exit_code}")
            if exit_code != 0:
                self.client_log.append(f"警告：客户端进程异常退出，退出码: {exit_code}")
                self.client_log.moveCursor(QTextCursor.End)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPos() - self.pos()
            event.accept()
    
    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() & Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self.move(event.globalPos() - self._drag_pos)
            event.accept()
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = None
            event.accept()
    
    def toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
    
    def closeEvent(self, event):
        # 如果是自定义事件对象
        if hasattr(event, 'spontaneous') and callable(event.spontaneous):
            try:
                if event.spontaneous():
                    event.ignore()
                    self.hide()
                    return
            except TypeError:
                pass
        
        # 停止进程监控
        self.process_monitor.stop()
        
        # 终止服务器和客户端进程
        if self.server_process:
            try:
                self.server_process.terminate()
                self.server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server_process.kill()
            except Exception as e:
                logging.error(f"终止服务端进程时出错：{str(e)}")
                
        if self.client_process:
            try:
                self.client_process.terminate()
                self.client_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.client_process.kill()
            except Exception as e:
                logging.error(f"终止客户端进程时出错：{str(e)}")
        
        # 检查并终止所有start_server.exe进程
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if proc.info['name'] == 'start_server.exe':
                    psutil.Process(proc.info['pid']).terminate()
                    logging.info(f"终止已存在的start_server.exe进程 (PID: {proc.info['pid']})")
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
                
        event.accept()

def start_core_server(log_emitter, window):
    # 记录当前工作目录和启动路径信息
    current_dir = os.getcwd()
    server_exe_path = os.path.join(BASE_DIR, "start_server.exe")
    logging.info(f"当前工作目录: {current_dir}")
    logging.info(f"服务器启动文件路径: {server_exe_path}")
    
    # 检查服务器可执行文件是否存在
    if not os.path.exists(server_exe_path):
        error_msg = f"错误：服务器可执行文件不存在: {server_exe_path}"
        logging.error(error_msg)
        log_emitter.emit_log(error_msg)
        return
    
    # 检查文件权限
    try:
        with open(server_exe_path, 'rb') as _:
            pass
        logging.info("服务器可执行文件权限检查通过")
    except PermissionError as e:
        error_msg = f"错误：无法访问服务器可执行文件，权限不足: {str(e)}"
        logging.error(error_msg)
        log_emitter.emit_log(error_msg)
        return
    
    # 在启动新进程前检查并清理已存在的start_server.exe进程
    existing_processes = []
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if proc.info['name'] == 'start_server.exe':
                existing_processes.append(proc.info['pid'])
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    
    if existing_processes:
        logging.info(f"发现{len(existing_processes)}个已存在的服务器进程")
        for pid in existing_processes:
            try:
                psutil.Process(pid).terminate()
                logging.info(f"已终止服务器进程 (PID: {pid})")
            except Exception as e:
                logging.warning(f"终止进程 {pid} 时出错: {str(e)}")
    
    logging.info("准备启动服务器进程...")
    command = [os.path.join(BASE_DIR, "start_server.exe")]
    logging.info(f"启动命令: {' '.join(command)}")
    log_emitter.emit_log("正在启动服务器进程...")
    
    try:
        window.server_process = subprocess.Popen(
            command,  # 直接运行exe
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            bufsize=1
        )
        success_msg = f"服务器进程已启动，PID: {window.server_process.pid}"
        logging.info(success_msg)
        log_emitter.emit_log(success_msg)
    except Exception as e:
        error_msg = f"启动服务器进程失败: {str(e)}"
        logging.error(error_msg)
        log_emitter.emit_log(error_msg)
        return
    
    def read_output(stream, emitter):
        for line in iter(stream.readline, ''):
            logging.info(f"[Core Server] {line.strip()}")
            emitter.emit_log(line.strip())
        stream.close()
    
    threading.Thread(target=read_output, args=(window.server_process.stdout, log_emitter), daemon=True).start()
    threading.Thread(target=read_output, args=(window.server_process.stderr, log_emitter), daemon=True).start()
    
    window.server_process.wait()

def main():
    try:
        # 获取图标路径
        icon_path = get_icon_path()
        if not icon_path:
            logging.warning("将使用默认图标继续运行")

        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)
        app.setStyleSheet("""
            QApplication {
                background-color: #121212;
                color: #e0e0e0;
            }
            QMenu {
                background-color: #1e1e1e;
                color: #e0e0e0;
                border: 1px solid #333;
            }
            QMenu::item:selected {
                background-color: #333;
            }
            QAction {
                color: #e0e0e0;
            }
        """)
        logging.info("应用程序初始化成功")
        
        # 启动core_server
        window = MainWindow()
        server_thread = threading.Thread(
            target=start_core_server,
            args=(window.server_emitter, window),
            daemon=True
        )
        server_thread.start()
        logging.info("主窗口创建成功")
        
        # 确保系统托盘可用
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logging.error("系统托盘不可用")
            sys.exit(1)

        tray = QSystemTrayIcon()
        if icon_path:
            icon = QIcon(icon_path)
            if icon.isNull():
                logging.error(f"无法加载图标文件：{icon_path}")
                icon = QIcon()
        else:
            icon = QIcon()
            
        tray.setIcon(icon)
        tray.setToolTip("CapsWriter-Offline")
        logging.info("系统托盘图标初始化成功")
        
        # 双击托盘图标显示主窗口
        tray.activated.connect(
            lambda reason: window.show() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None
        )

        # 创建菜单
        menu = QMenu()
        action_show = QAction("显示主界面")
        action_settings = QAction("设置")
        action_log = QAction("打开日志")
        action_quit = QAction("退出")

        # 菜单事件
        action_show.triggered.connect(window.show)
        action_settings.triggered.connect(lambda: logging.info("打开设置"))
        action_log.triggered.connect(lambda: window.show())
        action_quit.triggered.connect(lambda: (window.close(), app.quit()))

        menu.addAction(action_show)
        menu.addAction(action_settings)
        menu.addAction(action_log)
        menu.addSeparator()
        menu.addAction(action_quit)

        tray.setContextMenu(menu)
        tray.show()
        logging.info("托盘菜单创建成功")

        return app.exec()
    except Exception as e:
        logging.error(f"程序运行时出现异常：{str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
