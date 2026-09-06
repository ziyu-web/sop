"""
海康威视海康互联开放平台 - 固件升级模型
功能：处理设备固件升级相关的API调用，包括创建升级任务和获取升级进度
遵循海康 ISAPI v2.0+ 在线升级协议
"""

import json
from typing import Dict, List, Optional, Any
from hikiot.utils.http_client import global_http_client
from hikiot.utils.log_manager import global_logger
from hikiot.utils.path_manager import global_path_manager
from hikiot.model.hikiot_open_isapi_transmission import HikiotIsapiTransmissionModel


class HikiotFirmwareUpgradeModel:
    """固件升级模型类 - 基于标准海康 ISAPI 协议"""

    def __init__(self):
        self.isapi_model = HikiotIsapiTransmissionModel()

    def create_upgrade_task(self, device_serial: str, firmware_info: Dict[str, Any],
                           app_access_token: str, user_access_token: str = "") -> Dict[str, Any]:
        """
        创建设备固件升级任务（基于标准 ISAPI onlineUpgrade 接口）

        Args:
            device_serial: 设备序列号（大写）
            firmware_info: 固件信息，包含 URL、MD5、是否延迟等
                示例: {
                    "url": "https://firmware.example.com/fw.bin?token=abc",
                    "md5": "d41d8cd98f00b204e9800998ecf8427e",
                    "delayed_upgrade": False,
                    "module_type": "cardReader",  # 可选组件类型
                    "custom_task_id": "my_task_001"
                }
            app_access_token: 应用级 access_token
            user_access_token: 用户级 access_token（可选）

        Returns:
            升级任务创建结果
        """
        try:
            global_logger.info(f"开始为设备 {device_serial} 创建固件升级任务")

            # 处理固件包准备（返回可访问的 URL）
            firmware_url = self._prepare_firmware_package(firmware_info)
            if not firmware_url:
                return {
                    'success': False,
                    'device_serial': device_serial,
                    'message': '固件包处理失败'
                }

            # 构建符合 ISAPI 标准的请求体（JSON 模式）
            request_body = self._build_upgrade_request_body(firmware_info, firmware_url)

            # 正确的 ISAPI 路径（支持 format=json）
            isapi_url = "/ISAPI/System/onlineUpgrade/task?format=json"

            success, result_data = self.isapi_model.isapi_transparent_transmission(
                app_access_token=app_access_token,
                user_access_token=user_access_token,
                device_serial=device_serial,
                req_method="POST",
                url=isapi_url,
                req_body=request_body,
            )

            if success:
                # 解析响应并提取 taskID
                task_id = self._extract_task_id_from_response(result_data)
                global_logger.info(f"设备 {device_serial} 升级任务创建成功，任务ID: {task_id}")
                return {
                    'success': True,
                    'device_serial': device_serial,
                    'task_id': task_id,
                    'message': '升级任务创建成功',
                    'raw_response': result_data
                }
            else:
                error_msg = f"创建升级任务失败: {result_data}"
                global_logger.error(error_msg)
                return {
                    'success': False,
                    'device_serial': device_serial,
                    'message': error_msg
                }

        except Exception as e:
            error_msg = f"创建升级任务时发生异常: {str(e)}"
            global_logger.error(error_msg)
            return {
                'success': False,
                'device_serial': device_serial,
                'message': error_msg
            }

    def get_upgrade_progress(self, device_serial: str, app_access_token: str,
                             user_access_token: str = "", task_id: Optional[str] = None) -> Dict[str, Any]:
        """
        获取设备固件升级进度

        Args:
            device_serial: 设备序列号
            app_access_token: 应用访问令牌
            user_access_token: 用户访问令牌
            task_id: 升级任务ID（可选）

        Returns:
            升级进度信息
        """
        try:
            global_logger.debug(f"查询设备 {device_serial} 的升级进度")

            # ✅ 正确的 ISAPI 查询路径
            isapi_url = "/ISAPI/System/onlineUpgrade/status/task?format=json"

            # 修复：移除不支持的 content_type 参数
            success, result_data = self.isapi_model.isapi_transparent_transmission(
                app_access_token=app_access_token,
                user_access_token=user_access_token,
                device_serial=device_serial,
                req_method="GET",
                url=isapi_url,
                req_body="",  # GET 请求无 body
            )

            if success:
                progress_data = self._parse_progress_response(result_data)
                return {
                    'success': True,
                    'device_serial': device_serial,
                    **progress_data,
                    'raw_data': result_data
                }
            else:
                error_msg = f"获取升级进度失败: {result_data}"
                global_logger.warning(error_msg)
                return {
                    'success': False,
                    'device_serial': device_serial,
                    'progress': 0,
                    'status': 'error',
                    'message': error_msg
                }

        except Exception as e:
            error_msg = f"获取升级进度时发生异常: {str(e)}"
            global_logger.error(error_msg)
            return {
                'success': False,
                'device_serial': device_serial,
                'progress': 0,
                'status': 'error',
                'message': error_msg
            }

    def batch_create_upgrade_tasks(self, device_list: List[Dict[str, str]], firmware_info: Dict[str, Any],
                                   app_access_token: str, user_access_token: str = "") -> List[Dict[str, Any]]:
        """批量创建升级任务"""
        results = []
        total = len(device_list)
        global_logger.info(f"批量创建升级任务，共 {total} 台设备")

        for idx, device in enumerate(device_list, 1):
            serial = device.get('serial', '')
            verify_code = device.get('verification_code', '')
            global_logger.info(f"[{idx}/{total}] 处理设备: {serial}")

            result = self.create_upgrade_task(serial, firmware_info, app_access_token, user_access_token)
            result.update({'index': idx, 'verification_code': verify_code})
            results.append(result)

        success_count = sum(1 for r in results if r['success'])
        fail_count = len(results) - success_count
        global_logger.info(f"批量任务完成: 成功={success_count}, 失败={fail_count}")
        return results

    def batch_get_upgrade_progress(self, device_serials: List[str], app_access_token: str,
                                   user_access_token: str = "") -> List[Dict[str, Any]]:
        """批量获取升级进度"""
        return [
            self.get_upgrade_progress(sn, app_access_token, user_access_token)
            for sn in device_serials
        ]

    def _prepare_firmware_package(self, firmware_info: Dict[str, Any]) -> Optional[str]:
        """准备固件包 URL"""
        try:
            url = firmware_info.get("url")
            file_path = firmware_info.get("path")
            global_logger.info(f"1.{url}")
            if url and (url.startswith("http://") or url.startswith("https://")):
                global_logger.info(f"使用远程URL: {url}")
                return url

            elif file_path and global_path_manager.file_exists(file_path):
                global_logger.warning("检测到本地文件路径，但未实现上传服务。请确保该路径可通过公网访问。")
                # TODO: 实现自动上传至对象存储或临时HTTP服务器
                return file_path

            else:
                global_logger.error("未能获取有效的固件包地址")
                return None
        except Exception as e:
            global_logger.error(f"准备固件包出错: {e}")
            return None

    def _build_upgrade_request_body(self, firmware_info: Dict[str, Any], final_url: str) -> str:
        """构建符合 ISAPI 标准的 JSON 请求体"""
        package_desc = {
            "URL": final_url,
            "name": firmware_info.get("name", "firmware.bin"),
        }

        # 可选字段添加
        if md5 := firmware_info.get("md5"):
            package_desc["MD5"] = md5
        if delayed := firmware_info.get("delayed_upgrade", True) is False:
            package_desc["delayedUpgrade"] = False  # 注意：false 表示延迟升级
        if module_type := firmware_info.get("module_type"):
            package_desc["moduleType"] = module_type
        if custom_id := firmware_info.get("custom_task_id"):
            package_desc["customTaskID"] = custom_id

        request_data = {
            "PackageDescription": package_desc
        }

        body = json.dumps(request_data, ensure_ascii=False, indent=2)
        global_logger.debug(f"构建的升级请求体:\n{body}")
        return body

    def _extract_task_id_from_response(self, response_data: Any) -> str:
        """从响应中提取 taskID，兼容 Dict/JSON/XML"""
        try:
            data = {}
            if isinstance(response_data, dict):
                data = response_data
            elif isinstance(response_data, str):
                try:
                    data = json.loads(response_data)
                except json.JSONDecodeError:
                    pass
            
            if data:
                if "taskID" in data:
                    return str(data.get("taskID", ""))
                if "errorCode" in data:
                    global_logger.warning(f"响应包含错误码: {data.get('errorCode')} - {data.get('errorMsg', '')}")
                    return ""

            # 如果上面没返回，且是字符串，尝试 XML 解析
            if isinstance(response_data, str):
                from hikiot.utils.xml_processor import global_xml_processor
                parse_result = global_xml_processor.parse_xml(response_data)
                if parse_result.success:
                    return global_xml_processor.extract_element_text_unified(
                        parse_result.data, 'taskID', ''
                    )

            return ""
        except Exception as e:
            global_logger.error(f"提取TaskID出错: {e}")
            return ""

    def _parse_progress_response(self, response_data: Any) -> Dict[str, Any]:
        """解析升级进度响应"""
        try:
            # === 第一步：提取真正的 body 字符串 ===
            raw_json_str = None

            if isinstance(response_data, str):
                # 如果已经是字符串，直接使用
                raw_json_str = response_data
            elif isinstance(response_data, dict):
                # 如果是字典，尝试取出 'body' 字段作为 JSON 字符串
                raw_json_str = response_data.get('body')
                if isinstance(raw_json_str, bytes):
                    raw_json_str = raw_json_str.decode('utf-8')
            elif isinstance(response_data, bytes):
                raw_json_str = response_data.decode('utf-8')
            else:
                return {
                    'progress': 0,
                    'status': 'error',
                    'message': f'不支持的数据类型: {type(response_data)}'
                }

            if not raw_json_str or not raw_json_str.strip():
                return {
                    'progress': 0,
                    'status': 'error',
                    'message': '响应体为空'
                }

            # === 第二步：解析 body 中的 JSON 字符串 ===
            try:
                data = json.loads(raw_json_str)  # ✅ 真正的 JSON 解析在这里
            except (json.JSONDecodeError, TypeError) as e:
                return {
                    'progress': 0,
                    'status': 'error',
                    'message': f'JSON解析失败: {str(e)[:50]}...'
                }

            # === 第三步：提取状态列表 ===
            status_list = data.get("onlineUpgradeStatusList", [])
            if not status_list:
                # 检查是否有错误码
                if "errorCode" in data:
                    return {
                        'progress': 0,
                        'status': 'error',
                        'message': f"错误 {data.get('errorCode')}: {data.get('errorMsg', '未知错误')}"
                    }
                return {
                    'progress': 0,
                    'status': 'idle',
                    'message': '无升级任务'
                }

            first_task = status_list[0]
            progress = int(first_task.get("percent", 0))
            raw_status = first_task.get("status", "unknown")

            # 状态映射表
            status_map = {
                "notUpgrade": "idle",
                "upgrading": "upgrading",
                "successful": "completed",
                "waitManualTrigger": "waiting_confirm",
                "upgradePreparing": "preparing",
                "languageMismatch": "failed",
                "writeFlashError": "failed",
                "packageTypeMismatch": "failed",
                "packageVersionMismatch": "failed",
                "netUnreachable": "network_error",
                "unknownError": "error"
            }
            mapped_status = status_map.get(raw_status, "unknown")

            message = first_task.get("statusDescription") or first_task.get("errorMsg", "")

            return {
                'progress': progress,
                'status': mapped_status,
                'message': message,
                'raw_status': raw_status,
                'task_id': first_task.get("taskID"),
                'package_name': first_task.get("packageName")
            }

        except Exception as e:
            global_logger.error(f"解析进度响应失败: {e}")
            return {
                'progress': 0,
                'status': 'error',
                'message': f"解析异常: {str(e)}"
            }


# 创建全局实例
global_firmware_upgrade_model = HikiotFirmwareUpgradeModel()