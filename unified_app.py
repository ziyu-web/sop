"""
EzOpen 海康互联工具 - 独立界面
只包含海康互联 (Hik-Connect) 固件升级工具，不再与萤石平台共用窗口
"""

import sys
import os
import tkinter as tk
from tkinter import ttk

# 确保当前目录在 sys.path 中，以便可以 import hikiot 和 ezviz
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def init_hikiot_module(master_frame):
    """初始化海康互联模块"""
    try:
        from hikiot.utils.log_manager import global_logger
        from hikiot.utils.path_manager import global_path_manager
        from hikiot.view.firmware_upgrade_application import global_firmware_upgrade_app
        from hikiot.controller.hikiot_open_firmware_upgrade_controller import global_firmware_upgrade_controller

        # 初始化路径和日志
        global_path_manager.ensure_directory_exists(global_path_manager.get_data_directory())
        logs_dir = os.path.join(global_path_manager.get_app_directory(), 'logs')
        global_path_manager.ensure_directory_exists(logs_dir)

        # 初始化UI (嵌入到 master_frame)
        global_logger.info("初始化海康互联 UI...")
        global_firmware_upgrade_app.initialize_ui(master=master_frame)

        # 绑定控制器
        global_firmware_upgrade_controller.view = global_firmware_upgrade_app
        global_firmware_upgrade_controller.set_view_callbacks()

        return global_firmware_upgrade_app
    except Exception as e:
        print(f"Error initializing Hikiot module: {e}")
        import traceback
        traceback.print_exc()
        return None


class UnifiedApp:
    def __init__(self):
        self.root = tk.Tk()
        # 仅海康互联工具
        self.root.title("EzOpen - 海康互联固件升级工具")
        self.root.geometry("1200x850")

        # 设置样式
        style = ttk.Style()
        style.theme_use('clam')

        # 创建单一 Tab 控件，只承载海康互联
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True, padx=5, pady=5)

        # Tab: 海康互联
        self.tab_hikiot = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_hikiot, text="  海康互联 (sop)  ")

        # 仅初始化海康互联模块
        self.app_hikiot = init_hikiot_module(self.tab_hikiot)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def run(self):
        self.root.mainloop()

    def on_close(self):
        # 清理资源
        try:
            from hikiot.controller.hikiot_open_firmware_upgrade_controller import global_firmware_upgrade_controller as hik_ctrl
            hik_ctrl.stop_all_tasks()
        except Exception:
            pass

        # 停止线程池调度，避免关闭窗口后仍有任务调度 _safe_after
        try:
            from hikiot.utils.thread_manager import global_thread_manager
            global_thread_manager.shutdown(wait=False)
        except Exception:
            pass

        self.root.destroy()
        sys.exit(0)


if __name__ == "__main__":
    app = UnifiedApp()
    app.run()
