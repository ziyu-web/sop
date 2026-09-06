import requests
import json
import time
from hikiot.utils.account_management import ConfigLoader
from hikiot.utils.log_manager import global_logger
from hikiot.utils.http_client import global_http_client, HttpRequestException

class HikiotAuthUserAccessTokenModel:
    def __init__(self):
        self.config = ConfigLoader()
        self.base_url = "https://open-api.hikiot.com"
        self.default_redirect_url = 'https://open.hikiot.com/util'
        self.user_access_token_cache = {}
        # 使用全局HttpClient实例
        self.http_client = global_http_client

    def apply_auth_code(self, app_key, username, password, redirect_url=None):
        """
        申请授权码以换取用户访问凭证
        
        :param app_key: 应用appKey
        :param username: 登录账号手机号
        :param password: 用户密码
        :param redirect_url: 重定向回调地址(默认使用配置中的地址)
        :param state: 第三方业务参数,重定向时回传
        :return: 包含授权码信息的字典
        :raises Exception: 当接口调用失败时抛出异常
        """
        url = f"{self.base_url}/auth/third/applyAuthCode"
        headers = {
            "Content-Type": "application/json"
        }
   
        app_key = app_key
        username = username
        password = password
        # 使用默认重定向地址如果未提供
        actual_redirect_url = redirect_url or self.default_redirect_url

        # 构建请求参数
        payload = {
            "appKey": app_key,
            "userName": username,
            "password": password,
            "redirectUrl": actual_redirect_url
        }
        global_logger.debug(f"申请授权码请求参数: {payload}")
       
        try:
            response = self.http_client.post(url, headers=headers, json=payload)
            response_data = response.json()
            global_logger.debug(f"申请授权码请求URL: {url}")
            global_logger.debug(f"申请授权码请求头: {headers}")
            global_logger.debug(f"申请授权码请求体: {json.dumps(payload)}")
            global_logger.debug(f"申请授权码响应: {response_data}")

            if response_data.get("code") == 0 and "data" in response_data:
                # 解析返回的JSON字符串数据
                auth_code_info = response_data.get("data")
                global_logger.debug(f"授权码信息: {auth_code_info}")

                return True,{
                    "appKey": auth_code_info.get("appKey"),
                    "redirectUrl": auth_code_info.get("redirectUrl"),
                    "authCode": auth_code_info.get("authCode")
                }
            else:
                return False, f"申请授权码失败: {response_data.get('msg')}"

        except Exception as e:
            return False, f"申请授权码异常: {str(e)}"

    def code_to_user_access_token(self, app_access_token, auth_code):
        """
        通过授权码获取用户访问凭证(V1)
        授权码一次性有效，调用后立即失效
        :param app_access_token: 应用授权凭证(App-Access-Token)
        :param auth_code: 授权码
        :return: 用户访问凭证信息字典
        """
        url = f"{self.base_url}/auth/third/code2Token"
        headers = {
            "Content-Type": "application/json",
            "App-Access-Token": app_access_token
        }
        payload = {
            "authCode": auth_code
        }

        # 检查缓存中是否有有效token
        current_time = time.time()
        global_logger.debug(f"当前时间戳: {current_time}")

        # 首先尝试从传入的app_access_token获取app_key
        # 检查是否有app_access_token对应的app_key缓存
        app_key = None
        # 检查所有缓存项，找到与当前app_access_token相关的缓存项
        for cache_key, cache_data in self.user_access_token_cache.items():
            if isinstance(cache_data, dict) and 'appAccessToken' in cache_data and cache_data['appAccessToken'] == app_access_token:
                app_key = cache_data.get('appKey')
                break
        
        # 如果找不到，我们需要使用app_access_token作为缓存键，或者在成功获取token后使用返回的appKey
        cache_key = app_key if app_key else app_access_token
        global_logger.debug(f"缓存键: {cache_key}")
        
        # 初始化缓存中不存在token的标志
        cache_exists = False
        cache_data = None
        
        if cache_key in self.user_access_token_cache:
            global_logger.debug(f"缓存存在")
            global_logger.debug(f"缓存数据: {self.user_access_token_cache}")
            cache_data = self.user_access_token_cache[cache_key]
            cache_exists = True
            # 计算剩余有效时间(秒) = 总有效期(天)*24*3600 - 已过去时间(秒)
            # 注意：用户访问令牌的有效期单位是天
            expires_in_days = float(cache_data.get('expiresIn', 0))
            remaining_time = expires_in_days * 24 * 3600 - (current_time - cache_data.get('acquired_time', 0))

            # 如果剩余时间 > 1小时(3600秒)，返回缓存的token
            if remaining_time > 3600:
                return True, {
                    "appKey": cache_data.get("appKey"),
                    "userAccessToken": cache_data.get("userAccessToken"),
                    "refreshUserToken": cache_data.get("refreshUserToken"),
                    "expiresIn": cache_data.get("expiresIn"),
                    "teamNo": cache_data.get("teamNo"),
                    "personNo": cache_data.get("personNo"),
                    "accountNo": cache_data.get("accountNo"),
                    "from_cache": True
                }
            else:
                global_logger.debug(f"缓存token即将过期，需要获取新token")
        else:
            global_logger.debug("缓存中不存在token，需要获取新token")

        # 缓存无效或不存在，请求新token
        try:
            response = self.http_client.get(url, headers=headers, params=payload)
            global_logger.debug(f"获取用户访问凭证请求URL: {url}")
            global_logger.debug(f"获取用户访问凭证请求头: {headers}")
            global_logger.debug(f"获取用户访问凭证请求参数: {json.dumps(payload)}")
            global_logger.debug(f"响应对象: {response}")
            global_logger.debug(f"响应文本: {response.text}")


            response_data = response.json()
            global_logger.debug(f"响应数据: {response_data}")

            if response_data.get("code") == 0 and "data" in response_data:
                # 解析返回的JSON字符串数据
                user_token_info = response_data.get("data") 
                global_logger.debug(f"用户访问凭证信息: {user_token_info}")

                # 使用appKey作为缓存键，确保缓存稳定
                cache_key = user_token_info.get("appKey") if user_token_info.get("appKey") else app_access_token
                
                # 更新缓存，同时保存当前使用的app_access_token以便后续查找
                global_logger.debug(f"更新缓存: cache_key={cache_key}, user_token={user_token_info.get('userAccessToken')[:20]}..., expires_in={user_token_info.get('expiresIn')}天")
                self.user_access_token_cache[cache_key] = {
                    "appKey": user_token_info.get("appKey"),
                    "appAccessToken": app_access_token,  # 保存当前使用的app_access_token
                    "userAccessToken": user_token_info.get("userAccessToken"),
                    "refreshUserToken": user_token_info.get("refreshUserToken"),
                    "expiresIn": user_token_info.get("expiresIn"),
                    "teamNo": user_token_info.get("teamNo"),
                    "personNo": user_token_info.get("personNo"),
                    "accountNo": user_token_info.get("accountNo"),
                    "acquired_time": current_time
                }
                global_logger.debug(f"缓存更新成功，当前缓存内容: {self.user_access_token_cache}")

                # 修复返回键名不一致问题（统一使用appKey而不是appkey）
                return True,{
                    "appKey": user_token_info.get("appKey"),
                    "userAccessToken": user_token_info.get("userAccessToken"),
                    "refreshUserToken": user_token_info.get("refreshUserToken"),
                    "expiresIn": user_token_info.get("expiresIn"),
                    "teamNo": user_token_info.get("teamNo"),
                    "personNo": user_token_info.get("personNo"),
                    "accountNo": user_token_info.get("accountNo"),
                    "from_cache": False
                }
            else:
                global_logger.error(f"获取用户访问凭证失败: {response_data.get('msg')}")
                return False, f"获取用户访问凭证失败: {response_data.get('msg')}"

        except Exception as e:
            global_logger.error(f"获取用户访问凭证异常: {str(e)}")
            return False, f"获取用户访问凭证异常: {str(e)}"

    def refresh_user_access_token(self, app_access_token, user_access_token, refresh_user_token):
        """刷新UserAccessToken并更新本地存储的凭证

        Args:
            app_access_token (str): 应用授权凭证
            user_access_token (str): 当前用户访问凭证
            refresh_user_token (str): 用户刷新凭证

        Returns:
            dict: 包含新凭证信息的字典
        """
        current_time = time.time()
        
        # 查找合适的缓存键（优先使用appKey）
        cache_key = None
        for key, data in self.user_access_token_cache.items():
            if isinstance(data, dict) and data.get('appKey'):
                cache_key = data.get('appKey')
                break
        
        # 如果找不到appKey，则回退到使用app_access_token
        if not cache_key:
            cache_key = app_access_token
        
        global_logger.debug(f"刷新用户访问令牌: cache_key={cache_key}, current_token={user_access_token[:20]}...")

        url = f"{self.base_url}/auth/third/refreshUserAccessToken"
        headers = {
            "Content-Type": "application/json",
            "App-Access-Token": app_access_token
        }
        payload = {
            "userAccessToken": user_access_token,
            "refreshUserToken": refresh_user_token
        }

        try:
            response = self.http_client.post(url, headers=headers, json=payload)
            global_logger.debug(f"刷新用户访问凭证请求URL: {url}")
            global_logger.debug(f"刷新用户访问凭证请求头: {headers}")
            global_logger.debug(f"刷新用户访问凭证请求体: {json.dumps(payload)}")
            
            response_data = response.json()
            global_logger.debug(f"刷新用户访问凭证响应: {response_data}")

            if response_data.get("code") == 0 and "data" in response_data:
                # 解析data字段获取新凭证信息
                user_token_info = response_data.get("data") 
                global_logger.debug(f"刷新用户访问凭证信息: {user_token_info}")

                # 使用appKey作为缓存键，确保缓存稳定
                new_cache_key = user_token_info.get("appKey") if user_token_info.get("appKey") else app_access_token
                
                # 更新缓存
                global_logger.debug(f"更新缓存: cache_key={new_cache_key}, new_token={user_token_info.get('userAccessToken')[:20]}..., expires_in={user_token_info.get('expiresIn')}天")
                if new_cache_key in self.user_access_token_cache:
                    self.user_access_token_cache[new_cache_key].update({
                        'acquired_time': current_time,
                        "appKey": user_token_info.get("appKey"),
                        "userAccessToken": user_token_info.get("userAccessToken"),
                        "refreshUserToken": user_token_info.get("refreshUserToken"),
                        "expiresIn": user_token_info.get("expiresIn"),
                        "teamNo": user_token_info.get("teamNo"),
                        "personNo": user_token_info.get("personNo"),
                        "accountNo": user_token_info.get("accountNo")
                    })
                    global_logger.debug(f"缓存已更新，当前缓存内容: {self.user_access_token_cache}")
                else:
                    # 如果缓存中不存在，创建新的缓存记录
                    self.user_access_token_cache[new_cache_key] = {
                        'acquired_time': current_time,
                        "appKey": user_token_info.get("appKey"),
                        "userAccessToken": user_token_info.get("userAccessToken"),
                        "refreshUserToken": user_token_info.get("refreshUserToken"),
                        "expiresIn": user_token_info.get("expiresIn"),
                        "teamNo": user_token_info.get("teamNo"),
                        "personNo": user_token_info.get("personNo"),
                        "accountNo": user_token_info.get("accountNo")
                    }
                    global_logger.debug(f"创建新缓存记录，当前缓存内容: {self.user_access_token_cache}")

                return True, {
                    "appKey": user_token_info.get("appKey"),
                    "userAccessToken": user_token_info.get("userAccessToken"),
                    "refreshUserToken": user_token_info.get("refreshUserToken"),
                    "expiresIn": user_token_info.get("expiresIn"),
                    "teamNo": user_token_info.get("teamNo"),
                    "personNo": user_token_info.get("personNo"),
                    "accountNo": user_token_info.get("accountNo"),
                    'from_cache': False
                }
            else:
                global_logger.error(f"刷新用户访问凭证失败: {response_data.get('msg')}")
                return False, f"刷新用户访问凭证失败: {response_data.get('msg')}"

        except requests.exceptions.RequestException as e:
            global_logger.error(f"网络请求异常: {str(e)}")
            return False, f"网络请求异常: {str(e)}"
        except Exception as e:
            global_logger.error(f"刷新用户访问凭证异常: {str(e)}")
            return False, f"刷新用户访问凭证异常: {str(e)}"

    def get_user_access_token(self, app_key, username, password, app_access_token, redirect_url=None):
        """
        完整获取用户访问凭证流程: 先申请授权码,再换取访问令牌
        
        :param app_key: 应用appKey
        :param username: 登录账号手机号
        :param password: 用户密码
        :param app_access_token: 应用授权凭证(App-Access-Token)
        :param redirect_url: 重定向回调地址
        :param state: 第三方业务参数
        :return: 用户访问凭证信息字典
        """
        try:
            # 1. 申请授权码
            success, auth_code_info = self.apply_auth_code(
                app_key=app_key,
                username=username,
                password=password,
                redirect_url=redirect_url,
            )
            global_logger.debug(f"授权码信息: {auth_code_info}")

            if not success:
                return False, auth_code_info
            
            auth_code = auth_code_info.get('authCode')

            global_logger.debug(f"授权码: {auth_code}")
            global_logger.debug(f"应用访问令牌: {app_access_token}")
            # 2. 使用授权码换取用户访问令牌
            success,user_token_info = self.code_to_user_access_token(
                app_access_token=app_access_token,
                auth_code=auth_code
            )
            global_logger.debug(f"用户访问令牌信息: {user_token_info}")

            if not success:
                return False, user_token_info
            
            return True, user_token_info

        except Exception as e:
            return False, f"获取用户访问凭证完整流程失败: {str(e)}"

    def get_authorized_user_info(self, app_access_token, user_access_token):
        """
        查询授权用户基本信息
        
        :param app_access_token: 应用授权凭证(App-Access-Token)
        :param user_access_token: 用户访问凭证(User-Access-Token)
        :return: 包含用户详细信息的字典
        """
        url = f"{self.base_url}/auth/third/getAccountInfo"
        headers = {
            "Content-Type": "application/json",
            "App-Access-Token": app_access_token
        }
        # 根据接口说明，userAccessToken应该作为请求参数传递
        params = {
            "userAccessToken": user_access_token
        }

        global_logger.debug(f"查询授权用户基本信息请求URL: {url}")
        global_logger.debug(f"查询授权用户基本信息请求头: {headers}")
        global_logger.debug(f"查询授权用户基本信息请求参数: {params}")

        try:
            response = self.http_client.get(url, headers=headers, params=params)
            global_logger.debug(f"查询授权用户基本信息响应对象: {response}")
            global_logger.debug(f"查询授权用户基本信息响应文本: {response.text}")

            response_data = response.json()
            global_logger.debug(f"查询授权用户基本信息响应数据: {response_data}")

            if response_data.get("code") == 0 and "data" in response_data:
                # 解析返回的用户信息数据
                user_info = response_data.get("data") 
                global_logger.debug(f"用户信息: {user_info}")

                # 确保返回的数据包含接口说明中指定的字段
                # accountNo: 海康通行证账号
                # nickName: 昵称
                # phone: 手机号
                # registerPhone: 注册手机号
                # avatarUrl: 头像
                if isinstance(user_info, dict):
                    # 验证关键字段是否存在
                    if "accountNo" in user_info:
                        return True, user_info
                    else:
                        global_logger.warning(f"用户信息缺少关键字段: {user_info}")
                        return True, user_info
                else:
                    # 接口说明中提到data字段是string类型
                    global_logger.debug(f"用户信息为字符串格式: {user_info}")
                    try:
                        # 尝试将字符串解析为JSON
                        parsed_user_info = json.loads(user_info)
                        return True, parsed_user_info
                    except json.JSONDecodeError:
                        # 如果解析失败，直接返回原始字符串
                        return True, user_info
            else:
                global_logger.error(f"查询授权用户基本信息失败: {response_data.get('msg')}")
                return False, f"查询授权用户基本信息失败: {response_data.get('msg')}"

        except HttpRequestException as e:
            global_logger.error(f"查询授权用户基本信息网络请求异常: {str(e)}")
            return False, f"查询授权用户基本信息网络请求异常: {str(e)}"
        except Exception as e:
            global_logger.error(f"查询授权用户基本信息异常: {str(e)}")
            return False, f"查询授权用户基本信息异常: {str(e)}"

# 创建全局实例供其他模块使用
global_user_access_token_model = HikiotAuthUserAccessTokenModel()
