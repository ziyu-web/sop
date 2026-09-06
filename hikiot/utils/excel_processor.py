import os
import re
from typing import List, Optional
import pandas as pd
from .log_manager import global_logger

class ExcelProcessor:
    """
    Excel文件处理器，提供解析Excel文件并提取数据的功能
    """
    
    def __init__(self):
        """初始化Excel处理器"""
        self.logger = global_logger
        self.logger.debug("Excel处理器初始化完成")
    
    def is_valid_url(self, text: str) -> bool:
        """
        检查文本是否为有效的URL格式或ISAPI路径
        
        参数:
            text: 待检查的文本
            
        返回:
            bool: 是否为有效URL或ISAPI路径
        """
        if not text or not isinstance(text, str):
            return False
        
        # 去除首尾空白
        text = text.strip()
        
        # 检查是否为ISAPI路径（以/ISAPI/开头）
        if text.startswith('/ISAPI/'):
            return True
        
        # 简单的URL格式验证正则表达式
        url_pattern = re.compile(
            r'^(https?://)?'  # 可选的http://或https://
            r'([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'  # 域名
            r'(/.*)?$'  # 可选的路径
        )
        
        return bool(url_pattern.match(text))
    
    def extract_urls_from_first_column(self, excel_path: str) -> tuple:
        """
        从Excel文件的第一个sheet中提取第一列的URL
        
        参数:
            excel_path: Excel文件路径
            
        返回:
            tuple: (是否成功, URL列表/错误信息)
        """
        try:
            # 验证文件路径
            if not os.path.exists(excel_path):
                error_msg = f"Excel文件不存在: {excel_path}"
                self.logger.error(error_msg)
                return False, error_msg
            
            # 验证文件扩展名
            _, ext = os.path.splitext(excel_path)
            if ext.lower() not in ['.xlsx', '.xls']:
                error_msg = f"不支持的文件格式，仅支持.xlsx和.xls: {ext}"
                self.logger.error(error_msg)
                return False, error_msg
            
            self.logger.info(f"开始解析Excel文件: {excel_path}")
            
            # 读取Excel文件的第一个sheet
            df = pd.read_excel(excel_path, sheet_name=0)
            
            if df.empty:
                self.logger.warning("Excel文件的第一个sheet为空")
                return True, []
            
            # 获取第一列数据
            first_column = df.iloc[:, 0]
            
            # 提取URL列表
            urls = []
            for index, value in enumerate(first_column):
                if pd.notna(value):  # 跳过空值
                    text = str(value).strip()
                    if self.is_valid_url(text):
                        urls.append(text)
                    else:
                        self.logger.debug(f"第{index+1}行的值不是有效的URL: {text}")
            
            self.logger.info(f"成功从Excel文件中提取到{len(urls)}个URL")
            return True, urls
            
        except PermissionError:
            error_msg = f"没有权限访问Excel文件: {excel_path}"
            self.logger.error(error_msg)
            return False, error_msg
        except pd.errors.EmptyDataError:
            error_msg = "Excel文件的第一个sheet没有数据"
            self.logger.error(error_msg)
            return False, error_msg
        except pd.errors.ParserError:
            error_msg = "Excel文件格式错误，无法解析"
            self.logger.error(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"解析Excel文件时发生异常: {str(e)}"
            self.logger.error(error_msg)
            return False, error_msg
    
    def extract_all_from_first_column(self, excel_path: str) -> tuple:
        """
        从Excel文件的第一个sheet中提取第一列的所有非空值（不做URL验证）
        
        参数:
            excel_path: Excel文件路径
            
        返回:
            tuple: (是否成功, 数据列表/错误信息)
        """
        try:
            # 验证文件路径
            if not os.path.exists(excel_path):
                error_msg = f"Excel文件不存在: {excel_path}"
                self.logger.error(error_msg)
                return False, error_msg
            
            # 验证文件扩展名
            _, ext = os.path.splitext(excel_path)
            if ext.lower() not in ['.xlsx', '.xls']:
                error_msg = f"不支持的文件格式，仅支持.xlsx和.xls: {ext}"
                self.logger.error(error_msg)
                return False, error_msg
            
            self.logger.info(f"开始提取Excel文件第一列数据: {excel_path}")
            
            # 读取Excel文件的第一个sheet
            df = pd.read_excel(excel_path, sheet_name=0)
            
            if df.empty:
                self.logger.warning("Excel文件的第一个sheet为空")
                return True, []
            
            # 获取第一列数据
            first_column = df.iloc[:, 0]
            
            # 提取非空值列表
            data_list = []
            for value in first_column:
                if pd.notna(value):  # 跳过空值
                    data_list.append(str(value).strip())
            
            self.logger.info(f"成功从Excel文件中提取到{len(data_list)}个数据项")
            return True, data_list
            
        except Exception as e:
            error_msg = f"提取Excel数据时发生异常: {str(e)}"
            self.logger.error(error_msg)
            return False, error_msg

    def process_excel_file(self, excel_path: str) -> List[tuple]:
        """
        处理设备列表Excel文件，提取设备序列号、验证码和固件路径
        默认列含义：
            第1列: 设备序列号
            第2列: 验证码（可选）
            第3列: 升级包1路径（可选）
            第4列: 升级包2路径（可选）

        参数:
            excel_path: Excel文件路径

        返回:
            list: [(serial, verification_code, firmware1, firmware2), ...]
        """
        try:
            if not os.path.exists(excel_path):
                self.logger.error(f"Excel文件不存在: {excel_path}")
                return []

            df = pd.read_excel(excel_path, sheet_name=0)
            if df.empty:
                return []

            # 转换为字符串类型，防止数字被读为int
            df = df.astype(str)

            result = []
            for index, row in df.iterrows():
                # 获取第一列（序列号）
                serial = row.iloc[0].strip() if pd.notna(row.iloc[0]) else ""

                # 跳过无效序列号
                if not serial or serial.lower() == 'nan':
                    continue

                # 获取第二列（验证码），如果存在
                code = ""
                if len(row) > 1 and pd.notna(row.iloc[1]):
                    code = row.iloc[1].strip()
                    if code.lower() == 'nan':
                        code = ""

                # 获取第三列（升级包1路径），如果存在
                fw1 = ""
                if len(row) > 2 and pd.notna(row.iloc[2]):
                    fw1 = row.iloc[2].strip()
                    if fw1.lower() == 'nan':
                        fw1 = ""

                # 获取第四列（升级包2路径），如果存在
                fw2 = ""
                if len(row) > 3 and pd.notna(row.iloc[3]):
                    fw2 = row.iloc[3].strip()
                    if fw2.lower() == 'nan':
                        fw2 = ""

                result.append((serial, code, fw1, fw2))

            self.logger.info(f"成功从Excel提取 {len(result)} 条设备信息")
            return result

        except Exception as e:
            self.logger.error(f"处理Excel文件失败: {str(e)}")
            return []

# 创建全局Excel处理器实例供其他模块使用
global_excel_processor = ExcelProcessor()
