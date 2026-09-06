# ©2025 Hikvision Digital Technology Co., Ltd. All Rights Reserved.

import time
from hikiot.utils.log_manager import global_logger
from hikiot.utils.http_client import global_http_client, HttpRequestException

class HikiotAuthModel:
    def __init__(self):
        # 接口文档指定的请求地址
        self.api_url = "https://open-api.hikiot.com/auth/exchangeAppToken"
        self.refresh_api_url = "https://open-api.hikiot.com/auth/refreshAppToken"
        # 缓存结构: {app_key: {'token': ..., 'expires_in': ..., 'acquired_time': ..., 'refresh_token': ...}}
        self.token_cache = {}
        # 使用全局HttpClient实例
        self.http_client = global_http_client

    def get_access_token(self, app_key, app_secret):
        """使用appKey和appSecret获取access token，实现缓存机制
        根据接口文档: 
        - 有效期大于1小时，返回原有token
        - 有效期小于等于1小时，返回新token
        - 最大有效期7*24小时
        """
        current_time = time.time()
        cache_key = app_key
        global_logger.debug(f"获取access token: app_key={app_key}, 缓存状态: {cache_key in self.token_cache}")

        # 检查缓存中是否有有效token
        if cache_key in self.token_cache:
            cache_data = self.token_cache[cache_key]
            global_logger.debug(f"缓存中存在token，当前时间: {current_time}, 获取时间: {cache_data['acquired_time']}")
            # 计算剩余有效时间(秒) = 总有效期(小时)*3600 - 已过去时间(秒)
            remaining_time = cache_data['expires_in'] * 3600 - (current_time - cache_data['acquired_time'])
            global_logger.debug(f"剩余有效时间: {remaining_time}秒")

            # 如果剩余时间 > 1小时(3600秒)，返回缓存的token
            if remaining_time > 3600:
                global_logger.debug(f"返回缓存的token: {cache_data['token'][:20]}...")
                return True, {
                    'app_access_token': cache_data['token'],
                    'expires_in': remaining_time / 3600,  # 转换为小时
                    'refresh_token': cache_data['refresh_token'],
                    'from_cache': True
                }
            else:
                global_logger.debug(f"缓存token即将过期，需要获取新token")
        else:
            global_logger.debug("缓存中不存在token，需要获取新token")

        # 缓存无效或不存在，请求新token
        try:
            # 接口要求JSON格式请求
            headers = {'Content-Type': 'application/json'}
            payload = {
                "appKey": app_key,
                "appSecret": app_secret
            }

            # 使用HttpClient发送POST请求
            response = self.http_client.post(self.api_url, json=payload, headers=headers)
            response.raise_for_status()  # 抛出HTTP错误状态码
            result = response.json()
            global_logger.debug(f"API响应结果: {result}")

            # 检查接口返回状态码
            if result.get('code') != 0:
                global_logger.error(f"API错误: {result.get('msg', '未知错误')}")
                return False, f"API错误: {result.get('msg', '未知错误')}"

            # 解析响应数据
            data = result.get('data', {})
            app_access_token = data.get('appAccessToken')
            expires_in = float(data.get('expiresIn', 0))
            refresh_token = data.get('refreshAppToken')

            # 验证必要字段
            if not app_access_token:
                global_logger.error("API返回数据中缺少appAccessToken字段")
                return False, "API返回数据中缺少appAccessToken字段"
            if expires_in <= 0:
                global_logger.error("API返回的有效期无效")
                return False, "API返回的有效期无效"

            # 更新缓存
            global_logger.debug(f"更新缓存: app_key={app_key}, token={app_access_token[:20]}..., expires_in={expires_in}小时")
            self.token_cache[cache_key] = {
                'token': app_access_token,
                'expires_in': expires_in,
                'acquired_time': current_time,
                'refresh_token': refresh_token
            }
            global_logger.debug(f"缓存更新成功，当前缓存内容: {self.token_cache}")

            # 返回新获取的token信息
            return True, {
                'app_access_token': app_access_token,
                'expires_in': expires_in,
                'refresh_token': refresh_token,
                'from_cache': False
            }

        except HttpRequestException as e:
            global_logger.error(f"网络请求错误: {str(e)}")
            return False, f"网络请求错误: {str(e)}"
        except Exception as e:
            global_logger.error(f"处理错误: {str(e)}")
            return False, f"处理错误: {str(e)}"

    def refresh_access_token(self, app_key, current_token, refresh_token):
        """刷新应用访问凭证
        根据接口文档：
        - 使用当前appAccessToken和refreshAppToken获取新token
        - 刷新后更新本地缓存的token信息
        - 老token在10分钟内仍然有效
        """
        current_time = time.time()
        cache_key = app_key
        global_logger.debug(f"刷新access token: app_key={app_key}, current_token={current_token[:20]}...")

        try:
            # 接口要求JSON格式请求
            headers = {'Content-Type': 'application/json'}
            payload = {
                "appAccessToken": current_token,
                "refreshAppToken": refresh_token
            }

            # 使用HttpClient发送POST请求
            response = self.http_client.post(self.refresh_api_url, json=payload, headers=headers)
            response.raise_for_status()  # 抛出HTTP错误状态码
            result = response.json()
            global_logger.debug(f"刷新API响应结果: {result}")

            # 检查接口返回状态码
            if result.get('code') != 0:
                global_logger.error(f"刷新Token失败: {result.get('msg', '未知错误')}")
                return False, f"刷新Token失败: {result.get('msg', '未知错误')}"

            # 解析响应数据
            data = result.get('data', {})
            new_access_token = data.get('appAccessToken')
            expires_in = float(data.get('expiresIn', 0))
            new_refresh_token = data.get('refreshAppToken')

            # 验证必要字段
            if not new_access_token:
                global_logger.error("刷新Token失败: API返回数据中缺少appAccessToken字段")
                return False, "刷新Token失败: API返回数据中缺少appAccessToken字段"
            if expires_in <= 0:
                global_logger.error("刷新Token失败: API返回的有效期无效")
                return False, "刷新Token失败: API返回的有效期无效"

            # 更新缓存
            global_logger.debug(f"更新缓存: app_key={app_key}, new_token={new_access_token[:20]}..., expires_in={expires_in}小时")
            if cache_key in self.token_cache:
                self.token_cache[cache_key].update({
                    'token': new_access_token,
                    'expires_in': expires_in,
                    'acquired_time': current_time,
                    'refresh_token': new_refresh_token
                })
                global_logger.debug(f"缓存已更新，当前缓存内容: {self.token_cache}")
            else:
                # 如果缓存中不存在，创建新的缓存记录
                self.token_cache[cache_key] = {
                    'token': new_access_token,
                    'expires_in': expires_in,
                    'acquired_time': current_time,
                    'refresh_token': new_refresh_token
                }
                global_logger.debug(f"创建新缓存记录，当前缓存内容: {self.token_cache}")

            # 返回新获取的token信息
            return True, {
                'app_access_token': new_access_token,
                'expires_in': expires_in,
                'refresh_token': new_refresh_token,
                'from_cache': False
            }

        except requests.exceptions.RequestException as e:
            global_logger.error(f"刷新Token网络请求错误: {str(e)}")
            return False, f"刷新Token网络请求错误: {str(e)}"
        except Exception as e:
            global_logger.error(f"刷新Token处理错误: {str(e)}")
            return False, f"刷新Token处理错误: {str(e)}"

# 创建全局实例供其他模块使用
global_app_access_token_model = HikiotAuthModel()
