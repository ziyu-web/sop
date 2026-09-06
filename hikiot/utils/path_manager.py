"""
路径管理模块
功能：统一管理应用程序的文件路径
"""

import os
import sys

class PathManager:
    """路径管理器类"""
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PathManager, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """初始化路径"""
        if getattr(sys, 'frozen', False):
            # 打包后的路径
            self.app_dir = os.path.dirname(sys.executable)
            # 资源路径（解压后的临时目录）
            self.resource_dir = getattr(sys, '_MEIPASS', self.app_dir)
            
            # 配置目录策略：优先外部，后备内部
            external_config = os.path.join(self.app_dir, 'config')
            if os.path.exists(external_config):
                self.config_dir = external_config
            else:
                # 内部资源中的 config (对应 --add-data "hikiot/config...;hikiot/config")
                self.config_dir = os.path.join(self.resource_dir, 'hikiot', 'config')
        else:
            # 开发环境路径
            # app_dir = .../EzOpen/hikiot
            self.app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            # resource_dir = .../EzOpen
            self.resource_dir = os.path.dirname(self.app_dir)
            self.config_dir = os.path.join(self.app_dir, 'config')
            
        self.logs_dir = os.path.join(self.app_dir, 'logs')
        self.data_dir = os.path.join(self.app_dir, 'data')
        
        # 确保基础目录存在 (只创建日志和数据，配置目录如果是内部的则只读无法创建)
        if not getattr(sys, 'frozen', False) or self.config_dir == os.path.join(self.app_dir, 'config'):
             self.ensure_directory_exists(self.config_dir)
             
        self.ensure_directory_exists(self.logs_dir)
        self.ensure_directory_exists(self.data_dir)
    
    def get_app_directory(self) -> str:
        """获取应用根目录（用户数据目录）"""
        return self.app_dir

    def get_resource_directory(self) -> str:
        """获取资源目录（静态文件目录）"""
        return self.resource_dir
    
    def get_config_directory(self) -> str:
        """获取配置目录"""
        return self.config_dir
        
    def get_logs_directory(self) -> str:
        """获取日志目录"""
        return self.logs_dir
        
    def get_data_directory(self) -> str:
        """获取数据目录"""
        return self.data_dir
        
    def ensure_directory_exists(self, directory_path: str):
        """确保目录存在，不存在则创建"""
        if not os.path.exists(directory_path):
            try:
                os.makedirs(directory_path)
            except Exception as e:
                print(f"创建目录失败 {directory_path}: {e}")
                
    def file_exists(self, file_path: str) -> bool:
        """检查文件是否存在"""
        return os.path.exists(file_path) and os.path.isfile(file_path)

    def get_file_path(self, directory: str, filename: str) -> str:
        """拼接目录和文件名获取完整路径"""
        return os.path.join(directory, filename)

# 全局路径管理器实例
global_path_manager = PathManager()
