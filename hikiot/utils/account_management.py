# ©2025 Hikvision Digital Technology Co., Ltd. All Rights Reserved.

import os
import json
from typing import Tuple, Optional, List, Dict
from hikiot.utils.log_manager import global_logger
from hikiot.utils.path_manager import global_path_manager

class ConfigLoader:

    @staticmethod
    def get_default_account(config_path: Optional[str] = None) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        """获取默认账户的app_key、app_secret、username和password

        Args:
            config_path: 配置文件路径，默认使用config目录下的config.json

        Returns:
            Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]: (app_key, app_secret, username, password)
            如果没有找到有效的默认账户，返回(None, None, None, None)
        """
        try:
            # 构建默认配置文件路径
            if not config_path:
                config_dir = global_path_manager.get_config_directory()
                config_path = global_path_manager.get_file_path(config_dir, 'config.json')
            
            if not global_path_manager.ensure_file_exists(config_path, create_empty=False):
                raise FileNotFoundError(f"配置文件不存在: {config_path}")
            
            # 加载配置文件
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # 查找default为true的账户
            for account in config:
                details = account.get('details', {})
                if details.get('default', False):
                    app_key = details.get('app_key')
                    app_secret = details.get('app_secret')
                    username = details.get('username')
                    password = details.get('password')
                    return app_key, app_secret, username, password
            
            # 如果没有找到default为true的账户，返回第一个账户（如果有）
            if config and len(config) > 0:
                first_account = config[0]
                details = first_account.get('details', {})
                app_key = details.get('app_key')
                app_secret = details.get('app_secret')
                username = details.get('username')
                password = details.get('password')
                return app_key, app_secret, username, password
            
            # 没有找到任何账户
            return None, None, None, None
        except (FileNotFoundError, json.JSONDecodeError, Exception) as e:
            global_logger.error(f"获取默认账户失败: {str(e)}")
            return None, None, None, None

    @staticmethod
    def get_all_accounts(config_path: Optional[str] = None) -> List[Dict[str, str]]:
        """获取所有账户信息

        Args:
            config_path: 配置文件路径，默认使用config目录下的config.json

        Returns:
            List[Dict[str, str]]: 包含所有账户信息的列表，每个账户包含username、app_key、app_secret和password
        """
        try:
            # 构建默认配置文件路径
            if not config_path:
                config_dir = global_path_manager.get_config_directory()
                config_path = global_path_manager.get_file_path(config_dir, 'config.json')
            
            if not global_path_manager.ensure_file_exists(config_path, create_empty=False):
                raise FileNotFoundError(f"配置文件不存在: {config_path}")
            
            # 加载配置文件
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # 提取所有账户信息
            accounts = []
            for account in config:
                details = account.get('details', {})
                account_info = {
                    'username': details.get('username'),
                    'app_key': details.get('app_key'),
                    'app_secret': details.get('app_secret'),
                    'password': details.get('password')
                }
                # 只添加包含必要信息的账户
                if all(account_info.values()):
                    accounts.append(account_info)
            
            return accounts
        except (FileNotFoundError, json.JSONDecodeError, Exception) as e:
            global_logger.error(f"获取所有账户失败: {str(e)}")
            return []

    @staticmethod
    def get_account_by_username(username: str, config_path: Optional[str] = None) -> Optional[Dict[str, str]]:
        """根据用户名获取账户详情

        Args:
            username: 要查找的用户名
            config_path: 配置文件路径，默认使用config目录下的config.json

        Returns:
            Optional[Dict[str, str]]: 账户详情，包含username、app_key、app_secret和password；如果未找到返回None
        """
        try:
            # 构建默认配置文件路径
            if not config_path:
                config_dir = global_path_manager.get_config_directory()
                config_path = global_path_manager.get_file_path(config_dir, 'config.json')
            
            if not global_path_manager.ensure_file_exists(config_path, create_empty=False):
                raise FileNotFoundError(f"配置文件不存在: {config_path}")
            
            # 加载配置文件
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # 根据用户名查找账户
            for account in config:
                details = account.get('details', {})
                if details.get('username') == username:
                    return {
                        'username': details.get('username'),
                        'app_key': details.get('app_key'),
                        'app_secret': details.get('app_secret'),
                        'password': details.get('password')
                    }
            
            # 未找到匹配的账户
            return None
        except (FileNotFoundError, json.JSONDecodeError, Exception) as e:
            global_logger.error(f"根据用户名获取账户详情失败: {str(e)}")
            return None

    @staticmethod
    def get_all_usernames(config_path: Optional[str] = None) -> List[str]:
        """获取所有用户名列表

        Args:
            config_path: 配置文件路径，默认使用config目录下的config.json

        Returns:
            List[str]: 所有用户名的列表
        """
        try:
            accounts = ConfigLoader.get_all_accounts(config_path)
            return [account['username'] for account in accounts if 'username' in account]
        except Exception as e:
            global_logger.error(f"获取所有用户名失败: {str(e)}")
            return []
