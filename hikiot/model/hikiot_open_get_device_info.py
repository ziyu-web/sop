# ©2025 Hikvision Digital Technology Co., Ltd. All Rights Reserved.

import time
from hikiot.utils.log_manager import global_logger
from hikiot.utils.http_client import global_http_client, HttpRequestException


class HikiotDeviceInfoModel:
    def __init__(self):
        self.base_url = "https://open-api.hikiot.com"
        # 查询设备详情接口
        self.device_info_url = f"{self.base_url}/device/v1/info"
        # 使用全局HTTP客户端
        self.http_client = global_http_client

    def get_device_info(self, app_access_token: str, user_access_token: str, device_serial: str) -> tuple:
        """
        根据设备序列号查询团队下该设备的详细信息
        :param app_access_token: 应用访问凭证
        :param user_access_token: 用户访问凭证
        :param device_serial: 设备序列号（长度9-64位）
        :return: (是否成功, 响应数据或错误信息)
        """
        url = self.device_info_url
        headers = {
            "Content-Type": "application/json",
            "App-Access-Token": app_access_token,
            "User-Access-Token": user_access_token
        }
        params = {
            "deviceSerial": device_serial
        }

        # 参数校验
        if not device_serial or len(device_serial) < 9 or len(device_serial) > 64:
            error_msg = "设备序列号格式错误，长度应为9-64位"
            global_logger.error(error_msg)
            return False, error_msg

        global_logger.debug(f"查询设备详情请求地址: {url}")
        global_logger.debug(f"查询设备详情请求头: {headers}")
        global_logger.debug(f"查询设备详情请求参数: {params}")

        try:
            response = self.http_client.get(url, headers=headers, params=params, timeout=15)
            response.raise_for_status()
            result = response.json()
            global_logger.debug(f"查询设备详情响应: {result}")

            if result.get("code") != 0:
                msg = result.get("msg", "未知错误")
                global_logger.error(f"查询设备详情失败: {msg}")
                return False, f"查询失败: {msg}"

            data = result.get("data", {})
            if not data:
                global_logger.warning(f"设备[{device_serial}]返回数据为空")
                return False, "返回数据为空"

            # 解析字段
            device_info = {
                "deviceSerial": data.get("deviceSerial"),
                "name": data.get("name"),
                "model": data.get("model"),
                "deviceVersion": data.get("deviceVersion"),
                "status": data.get("status"),  # 0:离线 1:在线
                "isEncrypt": data.get("isEncrypt"),  # 0:未加密 1:加密
                "channelNum": data.get("channelNum")
            }

            global_logger.info(f"成功获取设备[{device_serial}]信息: 模型={device_info['model']}, 状态={'在线' if device_info['status'] == 1 else '离线'}")

            return True, device_info

        except HttpRequestException as e:
            global_logger.error(f"网络请求失败: {str(e)}")
            return False, f"网络请求失败: {str(e)}"
        except Exception as e:
            global_logger.error(f"查询设备详情异常: {str(e)}")
            return False, f"内部错误: {str(e)}"


# 创建全局实例供其他模块调用
global_device_info_model = HikiotDeviceInfoModel()
