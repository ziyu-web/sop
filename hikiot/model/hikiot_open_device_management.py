# ©2025 Hikvision Digital Technology Co., Ltd. All Rights Reserved.

import time
from hikiot.utils.log_manager import global_logger
from hikiot.utils.http_client import global_http_client, HttpRequestException


class HikiotDeviceMgrModel:
    def __init__(self):
        self.base_url = "https://open-api.hikiot.com"
        # 添加设备接口
        self.add_device_url = f"{self.base_url}/device/mgr/v1/add"
        # 删除设备接口
        self.delete_device_url = f"{self.base_url}/device/mgr/v1/delete"
        # 使用全局HTTP客户端
        self.http_client = global_http_client

    def add_device(self, app_access_token: str, user_access_token: str,
                   device_serial: str, validate_code: str, qr_code: str,
                   add_method: str = "DeviceToken",
                   third_category_name: str = None,
                   longitude: str = None, latitude: str = None) -> tuple:
        """
        添加设备到当前团队
        :param app_access_token: 应用访问凭证
        :param user_access_token: 用户访问凭证
        :param device_serial: 设备序列号
        :param validate_code: 添加码（验证密码）
        :param qr_code: 扫码添加时的二维码内容
        :param add_method: 添加方式，支持 "DeviceToken" 或 "CODE"
        :param third_category_name: 三级类目名称（可选）
        :param longitude: 经度（可选）
        :param latitude: 纬度（可选）
        :return: (是否成功, 响应数据或错误信息)
        """
        url = self.add_device_url
        headers = {
            "Content-Type": "application/json",
            "App-Access-Token": app_access_token,
            "User-Access-Token": user_access_token
        }
        payload = {
            "deviceSerial": device_serial,
            "validateCode": validate_code,
            "qrCode": qr_code,
            "addMethod": add_method
        }

        # 可选字段
        if third_category_name:
            payload["thirdCategoryName"] = third_category_name
        if longitude is not None:
            payload["longitude"] = str(longitude)
        if latitude is not None:
            payload["latitude"] = str(latitude)

        global_logger.debug(f"添加设备请求地址: {url}")
        global_logger.debug(f"添加设备请求头: {headers}")
        global_logger.debug(f"添加设备请求体: {payload}")

        try:
            response = self.http_client.post(url, json=payload, headers=headers, timeout=15)
            response.raise_for_status()
            result = response.json()
            global_logger.debug(f"添加设备响应: {result}")

            if result.get("code") != 0:
                msg = result.get("msg", "未知错误")
                global_logger.error(f"添加设备失败: {msg}")
                return False, f"添加设备失败: {msg}"

            data = result.get("data", {})
            sub_code = data.get("subCode", -1)
            remark = data.get("remark", "")
            global_logger.info(f"设备[{device_serial}]添加结果: subCode={sub_code}, 说明={remark}")

            return True, {
                "subCode": sub_code,
                "remark": remark,
                "deviceSerial": data.get("deviceSerial"),
                "validateCode": data.get("validateCode"),
                "needInit": data.get("needInit", False),
                "needUserSync": data.get("needUserSync", False)
            }

        except HttpRequestException as e:
            global_logger.error(f"网络请求失败: {str(e)}")
            return False, f"网络请求失败: {str(e)}"
        except Exception as e:
            global_logger.error(f"添加设备异常: {str(e)}")
            return False, f"内部错误: {str(e)}"

    def delete_device(self, app_access_token: str, user_access_token: str,
                     device_serials: list) -> tuple:
        """
        从当前团队中删除一个或多个设备
        :param app_access_token: 应用访问凭证
        :param user_access_token: 用户访问凭证
        :param device_serials: 要删除的设备序列号列表
        :return: (是否成功, 响应数据或错误信息)
        """
        url = self.delete_device_url
        headers = {
            "Content-Type": "application/json",
            "App-Access-Token": app_access_token,
            "User-Access-Token": user_access_token
        }
        payload = {
            "deviceSerials": device_serials
        }

        global_logger.debug(f"删除设备请求地址: {url}")
        global_logger.debug(f"删除设备请求头: {headers}")
        global_logger.debug(f"删除设备请求体: {payload}")

        if not device_serials:
            global_logger.warning("删除设备请求中设备列表为空")
            return False, "设备序列号列表不能为空"

        try:
            response = self.http_client.post(url, json=payload, headers=headers, timeout=15)
            response.raise_for_status()
            result = response.json()
            global_logger.debug(f"删除设备响应: {result}")

            if result.get("code") != 0:
                msg = result.get("msg", "未知错误")
                global_logger.error(f"删除设备失败: {msg}")
                return False, f"删除设备失败: {msg}"

            data = result.get("data", {})
            devices = data.get("devices", [])
            del_reason_options = data.get("delReasonOptions", [])

            global_logger.info(f"成功删除 {len(devices)} 个设备: {device_serials}")

            return True, {
                "devices": devices,
                "delReasonOptions": del_reason_options
            }

        except HttpRequestException as e:
            global_logger.error(f"网络请求失败: {str(e)}")
            return False, f"网络请求失败: {str(e)}"
        except Exception as e:
            global_logger.error(f"删除设备异常: {str(e)}")
            return False, f"内部错误: {str(e)}"


# 创建全局实例供其他模块调用
global_device_management_model = HikiotDeviceMgrModel()
