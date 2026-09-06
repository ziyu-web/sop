import json
from typing import Dict, Optional, Any
from hikiot.utils.log_manager import global_logger
from hikiot.utils.http_client import global_http_client

class HikiotIsapiTransmissionModel:
    def __init__(self):
        self.base_url = "https://open-api.hikiot.com"
        # 使用全局HTTP客户端实例
        self.http_client = global_http_client
    
    def isapi_transparent_transmission(self, app_access_token: str, user_access_token: str, device_serial: str, 
                                      req_method: str, url: str, req_body: Optional[str] = None) -> tuple:
        """
        ISAPI协议指令透传功能
        :param app_access_token: 应用授权凭证
        :param user_access_token: 用户授权凭证
        :param device_serial: 设备序列号
        :param req_method: ISAPI协议上的请求方法类型（GET/POST/PUT/DELETE）
        :param url: ISAPI协议上的请求路径
        :param req_body: ISAPI协议上的请求内容（可选）
        :return: (是否成功, 响应数据/错误信息)
        """
        api_url = f"{self.base_url}/device/direct/v1/api/isapi"
        
        # 验证参数
        if not device_serial or len(device_serial) < 9 or len(device_serial) > 64:
            return False, "设备序列号格式错误，长度应为9-64位"
        
        valid_methods = ["GET", "POST", "PUT", "DELETE"]
        if req_method not in valid_methods:
            return False, f"请求方法必须是以下之一：{', '.join(valid_methods)}"
        
        if not url:
            return False, "ISAPI请求路径不能为空"
        
        headers = {
            "Content-Type": "application/json",
            "App-Access-Token": app_access_token,
            "User-Access-Token": user_access_token
        }
        
        payload = {
            "deviceSerial": device_serial,
            "reqMethod": req_method,
            "url": url
        }
        
        # 添加可选的请求体
        if req_body is not None:
            payload["reqBody"] = req_body
        
        try:
            if req_method == "GET":
                http_timeout = 10.0
            else:
                http_timeout = 20.0  # POST/PUT/DELETE 仍用 20s

            response = self.http_client.post(
                url=api_url,
                headers=headers,
                json=payload,
                timeout=http_timeout  # 传入动态 timeout
            )
            response.raise_for_status()
            result = response.json()
            raw_data = result.get('data', '')

            # 将字符串中的 \n \t 等转义符转换成真正的换行和制表符
            try:
                formatted_data = raw_data.encode('utf-8').decode('unicode_escape')
            except Exception as e:
                global_logger.warning(f"反转移失败: {e}")
                formatted_data = raw_data

            # 打印美化后的内容
            global_logger.debug(f"ISAPI透传响应:\n{formatted_data}")
            
            if result.get("code") != 0:
                error_msg = result.get("msg", "未知错误")
                return False, f"接口错误: {error_msg}"
            
            # 返回ISAPI协议返回报文
            return True, result.get("data", "")
            
        except Exception as e:
            # 利用HttpClient的错误处理机制
            error_msg = str(e)
            global_logger.error(f"ISAPI透传请求失败: {error_msg}")
            return False, f"请求异常: {error_msg}"
        
# 创建全局实例供其他模块使用
global_isapi_transmission_model = HikiotIsapiTransmissionModel()
