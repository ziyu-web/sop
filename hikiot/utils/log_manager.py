import os
import sys
import logging
import datetime
import threading
import queue
import pytz
import inspect
from logging.handlers import TimedRotatingFileHandler
from hikiot.utils.path_manager import global_path_manager

# 创建自定义格式化器，添加调用代码行信息
class CustomFormatter(logging.Formatter):
    def format(self, record):
        # 直接使用record中已经设置好的caller_info
        # 这些信息是在LogManager的日志方法中设置的
        if not hasattr(record, 'caller_info'):
            record.caller_info = "unknown:0"
        
        return super().format(record)

# 获取程序运行目录（已重定向到全局路径管理器）
def get_app_directory() -> str:
    return global_path_manager.get_app_directory()

class LogManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(LogManager, cls).__new__(cls)
                cls._instance._initialize()
            return cls._instance

    def _initialize(self):
        # 使用全局路径管理器获取日志目录
        self.log_dir = global_path_manager.get_logs_directory()
        
        # 设置东八区时区
        tz = pytz.timezone('Asia/Shanghai')
        # 生成日期格式的日志文件名（只包含年月日）
        date_str = datetime.datetime.now(tz).strftime('%Y%m%d')
        # 使用全局路径管理器获取完整的日志文件路径
        self.log_file = global_path_manager.get_file_path(self.log_dir, f'application_{date_str}.log')

        # 创建logger对象
        self.logger = logging.getLogger('HikiotOpen')
        self.logger.setLevel(logging.DEBUG)  # 设置最低日志级别为DEBUG
        # 防止日志重复输出
        if self.logger.handlers:
            self.logger.handlers.clear()

        # 创建格式化器，设置时间戳格式为'2025-09-20 12:56:28 +08'
        formatter = CustomFormatter('[%(asctime)s][%(caller_info)s][%(levelname)s]%(message)s', datefmt='%Y-%m-%d %H:%M:%S')

        # 创建控制台处理器，用于打印所有等级的日志到终端
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        
        # 创建文件处理器，指定UTF-8编码解决乱码问题
        file_handler = logging.FileHandler(self.log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)
        # 记录初始化日志，使用self.info()确保调用位置信息正确
        self.info(f"创建日志目录: {self.log_dir}")
        self.info(f"日志系统初始化完成，日志文件: {self.log_file}")

        # 初始化UI处理器为None
        self.ui_handler = None
        self.main_application = None

    def set_main_application(self, main_application):
        """设置主应用程序实例，用于UI日志显示"""
        self.main_application = main_application
        
        # 如果已经设置了UI处理器，先移除它
        if self.ui_handler:
            self.logger.removeHandler(self.ui_handler)
            self.ui_handler = None
        
        # 如果有main_application实例，创建UI处理器
        if main_application and hasattr(main_application, 'log_text'):
            self.ui_handler = UIHandler(main_application)
            self.ui_handler.setLevel(logging.DEBUG)  # 只显示非DEBUG级别的日志
            formatter = CustomFormatter('[%(asctime)s][%(caller_info)s][%(levelname)s]%(message)s', datefmt='%Y-%m-%d %H:%M:%S')
            self.ui_handler.setFormatter(formatter)
            self.logger.addHandler(self.ui_handler)

    def debug(self, message):
        """记录DEBUG级别的日志"""
        # 获取调用位置信息
        caller_info = self._get_caller_info()
        # 使用额外的参数传递调用位置信息
        self.logger.debug(message, extra={'caller_info': caller_info})

    def info(self, message):
        """记录INFO级别的日志"""
        # 获取调用位置信息
        caller_info = self._get_caller_info()
        # 使用额外的参数传递调用位置信息
        self.logger.info(message, extra={'caller_info': caller_info})

    def warning(self, message):
        """记录WARNING级别的日志"""
        # 获取调用位置信息
        caller_info = self._get_caller_info()
        # 使用额外的参数传递调用位置信息
        self.logger.warning(message, extra={'caller_info': caller_info})

    def error(self, message):
        """记录ERROR级别的日志"""
        # 获取调用位置信息
        caller_info = self._get_caller_info()
        # 使用额外的参数传递调用位置信息
        self.logger.error(message, extra={'caller_info': caller_info})

    def critical(self, message):
        """记录CRITICAL级别的日志"""
        # 获取调用位置信息
        caller_info = self._get_caller_info()
        # 使用额外的参数传递调用位置信息
        self.logger.critical(message, extra={'caller_info': caller_info})

    def _get_caller_info(self):
        """获取调用日志函数的代码位置信息"""
        try:
            # 获取当前调用栈
            stack = inspect.stack()
            
            # 定义特殊文件路径，这些是Python内部模块或导入机制相关的文件
            special_paths = ['importlib._bootstrap', '<frozen importlib._bootstrap>']
            
            # 从调用栈的第2层开始查找（跳过_get_caller_info自身）
            for frame_info in stack[2:]:
                frame = frame_info[0]
                filename = frame.f_code.co_filename
                line_number = frame.f_lineno
                
                # 检查是否是我们需要的业务代码调用
                if 'log_manager.py' not in filename:
                    # 对于导入阶段的调用，尝试获取更有意义的信息
                    simple_filename = os.path.basename(filename)
                    
                    # 检查是否是特殊路径
                    if any(special_path in filename for special_path in special_paths):
                        # 如果是导入阶段的调用，尝试从调用栈的其他部分获取更多上下文
                        # 这通常发生在模块初始化阶段
                        if hasattr(self, 'logger'):
                            return "log_manager.py:init"
                    
                    return f"{simple_filename}:{line_number}"
            
            # 如果找不到具体的调用位置，返回log_manager.py:init作为备选
            return "log_manager.py:init"
        except Exception:
            return "log_manager.py:init"

class UIHandler(logging.Handler):
    def __init__(self, main_application):
        super().__init__()
        self.main_application = main_application
        self.logger = global_logger  # 使用全局logger
        # 线程安全队列：工作线程只往队列放，主线程轮询取出并更新 UI，避免在非主线程调用 tkinter
        self._log_queue = queue.Queue()
        
        # 初始化颜色映射
        self.log_colors = {
            'INFO': 'black',        # info用黑色字体
            'WARNING': 'orange',    # warning用橙色字体
            'ERROR': 'red',         # error用红色字体
            'CRITICAL': 'red'       # critical也用红色字体
        }
        # 在主线程启动轮询（set_main_application 在主线程调用）
        try:
            root = getattr(main_application, 'root', None)
            if root and getattr(root, 'after', None):
                root.after(100, self._drain_log_queue)
        except Exception:
            pass

    def emit(self, record):
        """在UI中显示日志（可从任意线程调用，仅入队，不碰 tkinter）"""
        log_entry = self.format(record)
        level = record.levelname.upper()
        try:
            self._log_queue.put_nowait((log_entry, level))
        except queue.Full:
            pass

    def _drain_log_queue(self):
        """主线程轮询：取出队列中的日志并更新 UI，再调度下一次"""
        try:
            while True:
                try:
                    log_entry, level = self._log_queue.get_nowait()
                except queue.Empty:
                    break
                self._update_log_text(log_entry, level)
        except Exception:
            pass
        try:
            root = getattr(self.main_application, 'root', None)
            if root and getattr(root, 'winfo_exists', None) and root.winfo_exists():
                root.after(100, self._drain_log_queue)
        except Exception:
            pass

    def _update_log_text(self, log_entry, level):
        """在UI的Text_log中添加日志条目，并根据日志级别设置颜色"""
        if hasattr(self.main_application, 'log_text') and self.main_application.log_text:
            try:
                text_widget = self.main_application.log_text
                # 若为 disabled 状态需先设为 normal 才能插入
                was_disabled = text_widget.cget('state') == 'disabled'
                if was_disabled:
                    text_widget.configure(state='normal')
                try:
                    if tk is not None:
                        try:
                            if hasattr(text_widget, 'tag_config'):
                                for log_level, color in self.log_colors.items():
                                    text_widget.tag_config(log_level.lower(), foreground=color)
                            if hasattr(text_widget, 'insert'):
                                tag_name = level.lower()
                                if tag_name in [log_lvl.lower() for log_lvl in self.log_colors.keys()]:
                                    text_widget.insert(tk.END, log_entry + '\n', tag_name)
                                else:
                                    text_widget.insert(tk.END, log_entry + '\n')
                                text_widget.see(tk.END)
                        except Exception as inner_e:
                            self.logger.debug(f"设置日志颜色失败: {str(inner_e)}")
                            text_widget.insert(tk.END, log_entry + '\n')
                            text_widget.see(tk.END)
                    else:
                        text_widget.insert('end', log_entry + '\n')
                        text_widget.see('end')
                finally:
                    if was_disabled:
                        text_widget.configure(state='disabled')
            except Exception as e:
                self.logger.error(f"更新UI日志失败: {str(e)}")

# 创建全局日志管理器实例
global_logger = LogManager()

# 添加tkinter导入，确保UIHandler能正常工作
tk = None
try:
    import tkinter as tk
except ImportError:
    # 如果导入失败，记录一条警告
    global_logger.warning("无法导入tkinter模块，UI日志功能可能无法正常工作")
