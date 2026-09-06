"""
海康威视海康互联开放平台 - 固件升级压力测试工具主程序
功能：启动固件升级压力测试工具
"""

import sys
import os
import threading
from hikiot.utils.log_manager import global_logger
from hikiot.utils.thread_manager import global_thread_manager
from hikiot.utils.path_manager import global_path_manager
from hikiot.view.firmware_upgrade_application import global_firmware_upgrade_app
from hikiot.controller.hikiot_open_firmware_upgrade_controller import global_firmware_upgrade_controller


def initialize_application():
    """初始化应用程序"""
    try:
        global_logger.info("=" * 60)
        global_logger.info("海康威视海康互联开放平台 - 固件升级压力测试工具启动")
        global_logger.info("=" * 60)
        
        # 确保必要的目录存在
        global_path_manager.ensure_directory_exists(global_path_manager.get_data_directory())
        
        # 日志目录可能已经被log_manager创建，但确保它存在
        logs_dir = os.path.join(global_path_manager.get_app_directory(), 'logs')
        global_path_manager.ensure_directory_exists(logs_dir)
        
        # 初始化UI
        global_logger.info("正在初始化用户界面...")
        global_firmware_upgrade_app.initialize_ui()
        
        # 设置控制器
        global_logger.info("正在设置控制器...")
        global_firmware_upgrade_controller.view = global_firmware_upgrade_app
        global_firmware_upgrade_controller.set_view_callbacks()
        
        global_logger.info("应用程序初始化完成")
        return True
        
    except Exception as e:
        error_msg = f"初始化应用程序时出错: {str(e)}"
        global_logger.error(error_msg)
        print(f"错误: {error_msg}")
        return False


def cleanup_application():
    """清理应用程序资源"""
    try:
        global_logger.info("正在清理应用程序资源...")
        
        # 停止所有后台业务任务
        global_firmware_upgrade_controller.stop_all_tasks()
        
        # 停止线程管理器（不等待任务完成，防止后台sleep导致卡死）
        global_thread_manager.shutdown(wait=False)
        
        # 关闭应用窗口
        global_firmware_upgrade_app.close()
        
        global_logger.info("应用程序资源清理完成")
        global_logger.info("=" * 60)
        global_logger.info("海康威视海康互联开放平台 - 固件升级压力测试工具已退出")
        global_logger.info("=" * 60)
        
    except Exception as e:
        global_logger.error(f"清理应用程序资源时出错: {str(e)}")


def main():
    """主函数"""
    try:
        # 初始化应用程序
        if not initialize_application():
            sys.exit(1)
        
        # 设置退出处理
        import atexit
        atexit.register(cleanup_application)
        
        # 运行应用程序
        global_logger.info("启动用户界面...")
        global_firmware_upgrade_app.run()
        
    except KeyboardInterrupt:
        global_logger.info("用户中断程序执行")
    except Exception as e:
        error_msg = f"程序运行时发生未知错误: {str(e)}"
        global_logger.error(error_msg)
        print(f"错误: {error_msg}")
        sys.exit(1)
    finally:
        cleanup_application()


if __name__ == "__main__":
    main()
