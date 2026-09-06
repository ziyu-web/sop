import time
import threading
import socket
from collections import deque
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Callable, Tuple, Union
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib3.exceptions import ConnectionError as Urllib3ConnectionError

# 使用相对导入以解决运行时的模块导入问题
from .log_manager import global_logger

# 自定义HTTP异常类
class HttpException(Exception):
    """HTTP请求异常基类"""
    pass

class HttpRequestException(HttpException):
    """HTTP网络请求异常（对应requests.exceptions.RequestException）"""
    pass

class HttpClient:
    """HTTP客户端类，提供重试、超时、请求频率限制等功能"""
    
    def __init__(self, 
                 max_retries: int = 3, 
                 timeout: int = 30,
                 max_requests_per_second: int = 3, 
                 max_requests_per_minute: int = 200,
                 backoff_factor: float = 0.3):
        """
        初始化HTTP客户端
        
        参数:
            max_retries: 最大重试次数
            timeout: 请求超时时间(秒)
            max_requests_per_second: 每秒最大请求数
            max_requests_per_minute: 每分钟最大请求数
            backoff_factor: 重试间隔递增因子
        """
        # 创建会话对象
        self.session = requests.Session()
        
        # 配置重试策略
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],  # 这些状态码会触发重试
            allowed_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],  # 替代method_whitelist，支持的方法
            respect_retry_after_header=True  # 尊重服务器返回的Retry-After头
        )
        
        # 创建适配器并挂载到会话
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # 保存配置参数
        self.max_retries = max_retries
        self.timeout = timeout
        self.max_requests_per_second = max_requests_per_second
        self.max_requests_per_minute = max_requests_per_minute
        
        # 用于请求频率限制的计数器和锁 - 分离秒级和分钟级的请求时间戳
        self.minute_request_times = deque()  # 存储最近60秒的请求时间戳
        self.second_request_times = deque()  # 存储最近1秒的请求时间戳
        self.lock = threading.RLock()  # 可重入锁，用于线程安全
        self._cancel_events = {}  # 用于请求取消的事件字典
        
        # 模拟模式相关属性
        self._mock_mode = False
        self._mock_responses = {}
        
        # 参数验证
        if not isinstance(max_retries, int) or max_retries < 0:
            raise ValueError("max_retries必须是非负整数")
        
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("timeout必须是正数")
        
        if not isinstance(max_requests_per_second, int) or max_requests_per_second <= 0:
            raise ValueError("max_requests_per_second必须是正整数")
        
        if not isinstance(max_requests_per_minute, int) or max_requests_per_minute <= 0:
            raise ValueError("max_requests_per_minute必须是正整数")
        
        # 记录初始化日志
        global_logger.debug(f"HTTP客户端初始化完成: 最大重试次数={max_retries}, 超时时间={timeout}秒, 每秒最大请求数={max_requests_per_second}, 每分钟最大请求数={max_requests_per_minute}")
    
    def enable_mock_mode(self):
        """启用模拟模式"""
        self._mock_mode = True
        global_logger.debug("HTTP客户端已启用模拟模式")
    
    def disable_mock_mode(self):
        """禁用模拟模式"""
        self._mock_mode = False
        self._mock_responses.clear()
        global_logger.debug("HTTP客户端已禁用模拟模式")
    
    def set_mock_response(self, method: str, url: str, status_code: int = 200, 
                         content: str = "", headers: Optional[Dict[str, str]] = None):
        """设置模拟响应"""
        if not self._mock_mode:
            global_logger.warning("尝试在非模拟模式下设置模拟响应")
            return
        
        key = (method.upper(), url)
        self._mock_responses[key] = {
            'status_code': status_code,
            'content': content,
            'headers': headers or {}
        }
        global_logger.debug(f"已设置模拟响应: {method} {url} -> {status_code}")
    
    def cancel_request(self, request_id):
        """取消指定ID的请求"""
        if request_id in self._cancel_events:
            self._cancel_events[request_id].set()
            del self._cancel_events[request_id]
    
    
    def _check_rate_limit(self):
        """检查并应用请求频率限制 - 改进版"""
        with self.lock:
            # 获取当前时间
            current_time = time.time()
            
            # 清理分钟级过期的请求时间戳（只保留最近60秒的请求）
            while self.minute_request_times and current_time - self.minute_request_times[0] >= 60:
                self.minute_request_times.popleft()
            
            # 检查每分钟请求数限制
            if len(self.minute_request_times) >= self.max_requests_per_minute:
                oldest_time = self.minute_request_times[0]
                wait_time = 60 - (current_time - oldest_time) + 1  # 加上0.1秒的缓冲
                global_logger.warning(f"达到每分钟请求数限制({self.max_requests_per_minute})，等待{wait_time:.2f}秒")
                # 实际等待，而不是简单地移除时间戳
                time.sleep(wait_time)
                # 重新清理过期的请求时间戳
                current_time = time.time()  # 更新当前时间
                while self.minute_request_times and current_time - self.minute_request_times[0] >= 60:
                    self.minute_request_times.popleft()
            
            # 清理秒级过期的请求时间戳（只保留最近1秒的请求）
            while self.second_request_times and current_time - self.second_request_times[0] >= 1:
                self.second_request_times.popleft()
                
            # 检查每秒请求数限制 - 使用精确的计数
            if len(self.second_request_times) >= self.max_requests_per_second:
                # 计算需要等待的时间，确保请求频率不超过限制
                oldest_time = self.second_request_times[0]
                wait_time = 1 - (current_time - oldest_time) + 0.01  # 加上0.01秒的缓冲
                global_logger.warning(f"达到每秒请求数限制({self.max_requests_per_second})，等待{wait_time:.2f}秒")
                # 实际等待
                time.sleep(wait_time)
                # 重新清理过期的请求时间戳
                current_time = time.time()  # 更新当前时间
                while self.second_request_times and current_time - self.second_request_times[0] >= 1:
                    self.second_request_times.popleft()
            
            # 记录当前请求时间到两个队列
            self.minute_request_times.append(current_time)
            self.second_request_times.append(current_time)
    
    def _request(self, 
                 method: str, 
                 url: str, 
                 request_id: Optional[str] = None,
                 progress_callback: Optional[Callable[[int, int], None]] = None,
                 **kwargs) -> requests.Response:
        """
        发送HTTP请求的内部方法
        
        参数:
            method: 请求方法(GET, POST等)
            url: 请求URL
            request_id: 请求ID，用于取消请求
            progress_callback: 进度回调函数，接收当前下载字节数和总字节数
            **kwargs: 其他请求参数
        
        返回:
            requests.Response: 请求响应对象
            
        异常:
            HttpRequestException: HTTP网络请求异常
        """
        # 创建取消事件（如果提供了request_id）
        cancel_event = None
        if request_id:
            cancel_event = threading.Event()
            self._cancel_events[request_id] = cancel_event
        
        # 应用超时设置 - 确保传入的timeout参数被正确使用
        request_timeout = kwargs.get('timeout', self.timeout)
        kwargs['timeout'] = request_timeout
        
        # 检查频率限制
        self._check_rate_limit()
        
        # 检查是否已取消
        if cancel_event and cancel_event.is_set():
            raise HttpRequestException("请求已被取消")
        
        # 记录请求开始日志
        request_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        start_time = time.time()
        thread_id = threading.get_ident()
        request_data = kwargs.copy()
        
        # 提取deviceSerial - 修正：从params中提取deviceSerial
        device_serial = ""
        try:
            if isinstance(request_data.get('params'), dict):
                device_serial = request_data['params'].get('deviceSerial', '')
        except Exception:
            pass

        # 提取request_url - 修正：直接使用传入的url参数
        request_url = url  # 直接使用传入的URL参数

        # 提取request_method - 修正：从方法参数中获取
        request_method = method  # 直接使用传入的方法参数
        # 完整记录URL而不是只记录最后36个字符，确保URL格式一致性
        global_logger.info(f"设备序列号: {device_serial}, 请求时间: {request_timestamp}, 请求方式: {request_method}, URL: {request_url}")
        
        
        # 设置socket超时，确保底层连接也有超时控制
        original_socket_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(request_timeout)
        
        try:
            # 检查是否启用了模拟模式
            if self._mock_mode:
                mock_key = (method, url)
                if mock_key in self._mock_responses:
                    mock_response = self._mock_responses[mock_key]
                    global_logger.info(f"模拟模式: 返回预设响应 {method} {url}")
                    
                    # 创建模拟响应对象
                    response = requests.Response()
                    response.status_code = mock_response['status_code']
                    response._content = mock_response['content'].encode('utf-8')
                    response.headers.update(mock_response['headers'])
                    response.url = url
                    
                    # 记录响应日志
                    response_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                    elapsed_time = time.time() - start_time
                    global_logger.debug(f"线程ID {thread_id} - 设备序列号: {device_serial}, 返回时间: {response_timestamp}, 状态码: {response.status_code}, 耗时: {elapsed_time:.2f}秒")
                    
                    # 处理响应内容
                    response_content = response.text
                    global_logger.debug(f"线程ID {thread_id} - 设备序列号: {device_serial}, 响应内容: {response_content}")
                    
                    # 清理取消事件
                    if request_id and request_id in self._cancel_events:
                        del self._cancel_events[request_id]
                    
                    return response
            # 如果提供了进度回调函数，包装响应对象以支持进度报告
            if progress_callback:
                # 发送请求
                global_logger.debug(f"线程ID {thread_id} - 开始发送请求...")
                response = self.session.request(method, url, **kwargs)
                
                # 检查是否已取消
                if cancel_event and cancel_event.is_set():
                    raise HttpRequestException("请求已被取消")
                
                # 包装响应以支持进度回调
                original_iter_content = response.iter_content
                original_iter_lines = response.iter_lines
                
                def progress_iter_content(*args, **kwargs):
                    total_length = response.headers.get('content-length')
                    if total_length is not None:
                        total_length = int(total_length)
                    else:
                        total_length = 0
                    
                    downloaded = 0
                    for chunk in original_iter_content(*args, **kwargs):
                        # 检查是否已取消
                        if cancel_event and cancel_event.is_set():
                            raise HttpRequestException("请求已被取消")
                        
                        downloaded += len(chunk)
                        progress_callback(downloaded, total_length)
                        yield chunk
                
                def progress_iter_lines(*args, **kwargs):
                    total_length = response.headers.get('content-length')
                    if total_length is not None:
                        total_length = int(total_length)
                    else:
                        total_length = 0
                    
                    downloaded = 0
                    for line in original_iter_lines(*args, **kwargs):
                        # 检查是否已取消
                        if cancel_event and cancel_event.is_set():
                            raise HttpRequestException("请求已被取消")
                        
                        downloaded += len(line)
                        progress_callback(downloaded, total_length)
                        yield line
                
                response.iter_content = progress_iter_content
                response.iter_lines = progress_iter_lines
            else:
                # 发送请求
                global_logger.debug(f"线程ID {thread_id} - 开始发送请求...")
                response = self.session.request(method, url, **kwargs)
                
                # 检查是否已取消
                if cancel_event and cancel_event.is_set():
                    raise HttpRequestException("请求已被取消")
            
            # 记录请求完成日志
            response_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            elapsed_time = time.time() - start_time
            
            global_logger.debug(f"线程ID {thread_id} - 返回时间: {response_timestamp}, 状态码: {response.status_code}, 耗时: {elapsed_time:.2f}秒")
            
            # 处理响应内容，避免日志过大
            response_content = response.text
            global_logger.debug(f"线程ID {thread_id} - 响应内容: {response_content}")
            
            # 检查响应状态
            response.raise_for_status()
            
            # 清理取消事件
            if request_id and request_id in self._cancel_events:
                del self._cancel_events[request_id]
            
            return response
        except requests.exceptions.Timeout as e:
            # 清理取消事件
            if request_id and request_id in self._cancel_events:
                del self._cancel_events[request_id]
            
            # 提供更精确的超时错误信息
            timeout_type = "连接超时" if "connect" in str(e).lower() else "读取超时"
            error_msg = f"请求超时 ({timeout_type}): {method} {url} 超时时间为 {self.timeout} 秒"
            global_logger.error(error_msg)
            raise HttpRequestException(error_msg) from e
        except (requests.exceptions.ConnectionError, Urllib3ConnectionError) as e:
            # 清理取消事件
            if request_id and request_id in self._cancel_events:
                del self._cancel_events[request_id]
            
            # 特殊处理连接错误
            error_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            elapsed_time = time.time() - start_time
            
            # 提取deviceSerial
            device_serial = ""
            try:
                if isinstance(request_data.get('json'), dict):
                    device_serial = request_data['json'].get('deviceSerial', '')
                elif isinstance(request_data.get('data'), dict):
                    device_serial = request_data['data'].get('deviceSerial', '')
            except Exception:
                pass
            
            global_logger.error(f"线程ID {thread_id} - 设备序列号: {device_serial}, 错误时间: {error_timestamp}, 连接失败({str(e)}), 请检查网络连接或服务器可用性, 耗时: {elapsed_time:.2f}秒")
            global_logger.debug(f"线程ID {thread_id} - 设备序列号: {device_serial}, 请求参数: {request_data}")
            
            raise HttpRequestException(f"连接失败: {str(e)}") from e
        except requests.exceptions.RequestException as e:
            # 捕获所有其他requests异常并转换为我们的自定义异常
            if request_id and request_id in self._cancel_events:
                del self._cancel_events[request_id]
            
            error_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            elapsed_time = time.time() - start_time
            
            # 提取deviceSerial
            device_serial = ""
            try:
                if isinstance(request_data.get('json'), dict):
                    device_serial = request_data['json'].get('deviceSerial', '')
                elif isinstance(request_data.get('data'), dict):
                    device_serial = request_data['data'].get('deviceSerial', '')
            except Exception:
                pass
            
            global_logger.error(f"线程ID {thread_id} - 设备序列号: {device_serial}, 错误时间: {error_timestamp}, HTTP请求异常({str(e)}), 耗时: {elapsed_time:.2f}秒")
            global_logger.debug(f"线程ID {thread_id} - 设备序列号: {device_serial}, 请求参数: {request_data}")
            
            raise HttpRequestException(f"HTTP请求异常: {str(e)}") from e
        except Exception as e:
            # 清理取消事件
            if request_id and request_id in self._cancel_events:
                del self._cancel_events[request_id]
            
            # 记录其他异常
            error_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            elapsed_time = time.time() - start_time
            
            # 提取deviceSerial
            device_serial = ""
            try:
                if isinstance(request_data.get('json'), dict):
                    device_serial = request_data['json'].get('deviceSerial', '')
                elif isinstance(request_data.get('data'), dict):
                    device_serial = request_data['data'].get('deviceSerial', '')
            except Exception:
                pass
            
            global_logger.error(f"线程ID {thread_id} - 设备序列号: {device_serial}, 错误时间: {error_timestamp}, 请求失败({str(e)}), 耗时: {elapsed_time:.2f}秒")
            global_logger.debug(f"线程ID {thread_id} - 设备序列号: {device_serial}, 请求参数: {request_data}")
            
            raise
        finally:
            # 恢复原始socket超时设置
            socket.setdefaulttimeout(original_socket_timeout)
    
    def get(self, 
            url: str, 
            params: Optional[Dict[str, Any]] = None, 
            headers: Optional[Dict[str, str]] = None,
            request_id: Optional[str] = None,
            progress_callback: Optional[Callable[[int, int], None]] = None,
            **kwargs) -> requests.Response:
        """发送GET请求"""
        return self._request('GET', url, params=params, headers=headers, 
                           request_id=request_id, progress_callback=progress_callback, **kwargs)
    
    def post(self, 
             url: str, 
             data: Optional[Dict[str, Any]] = None, 
             json: Optional[Dict[str, Any]] = None, 
             headers: Optional[Dict[str, str]] = None,
             request_id: Optional[str] = None,
             progress_callback: Optional[Callable[[int, int], None]] = None,
             **kwargs) -> requests.Response:
        """发送POST请求"""
        return self._request('POST', url, data=data, json=json, headers=headers, 
                          request_id=request_id, progress_callback=progress_callback, **kwargs)
    
    def put(self, 
            url: str, 
            data: Optional[Dict[str, Any]] = None, 
            json: Optional[Dict[str, Any]] = None, 
            headers: Optional[Dict[str, str]] = None,
            request_id: Optional[str] = None,
            progress_callback: Optional[Callable[[int, int], None]] = None,
            **kwargs) -> requests.Response:
        """发送PUT请求"""
        return self._request('PUT', url, data=data, json=json, headers=headers, 
                         request_id=request_id, progress_callback=progress_callback, **kwargs)
    
    def delete(self, 
               url: str, 
               headers: Optional[Dict[str, str]] = None,
               request_id: Optional[str] = None,
               progress_callback: Optional[Callable[[int, int], None]] = None,
               **kwargs) -> requests.Response:
        """发送DELETE请求"""
        return self._request('DELETE', url, headers=headers, 
                          request_id=request_id, progress_callback=progress_callback, **kwargs)
    
    def patch(self, 
              url: str, 
              data: Optional[Dict[str, Any]] = None, 
              json: Optional[Dict[str, Any]] = None, 
              headers: Optional[Dict[str, str]] = None,
              request_id: Optional[str] = None,
              progress_callback: Optional[Callable[[int, int], None]] = None,
              **kwargs) -> requests.Response:
        """发送PATCH请求"""
        return self._request('PATCH', url, data=data, json=json, headers=headers, 
                          request_id=request_id, progress_callback=progress_callback, **kwargs)
    
    def head(self, 
             url: str, 
             headers: Optional[Dict[str, str]] = None,
             request_id: Optional[str] = None,
             progress_callback: Optional[Callable[[int, int], None]] = None,
             **kwargs) -> requests.Response:
        """发送HEAD请求"""
        return self._request('HEAD', url, headers=headers, 
                          request_id=request_id, progress_callback=progress_callback, **kwargs)
    
    def options(self, 
                url: str, 
                headers: Optional[Dict[str, str]] = None,
                request_id: Optional[str] = None,
                progress_callback: Optional[Callable[[int, int], None]] = None,
                **kwargs) -> requests.Response:
        """发送OPTIONS请求"""
        return self._request('OPTIONS', url, headers=headers, 
                          request_id=request_id, progress_callback=progress_callback, **kwargs)
    
    def set_proxy(self, proxy_dict: Dict[str, str]):
        """设置代理"""
        self.session.proxies = proxy_dict
        global_logger.info(f"HTTP客户端代理设置: {proxy_dict}")
    
    def set_headers(self, headers: Dict[str, str]):
        """设置默认请求头"""
        self.session.headers.update(headers)
        global_logger.info(f"HTTP客户端默认请求头更新")
    
    def set_auth(self, auth: Tuple[str, str]):
        """设置HTTP认证"""
        self.session.auth = auth
        global_logger.info(f"HTTP客户端认证设置")
    
    def close(self):
        """关闭会话"""
        self.session.close()
        global_logger.info("HTTP客户端会话已关闭")
    
    def reset(self):
        """重置HTTP客户端状态"""
        # 清理请求时间戳
        with self.lock:
            self.minute_request_times.clear()
            self.second_request_times.clear()
        
        # 清理取消事件
        for event in self._cancel_events.values():
            event.set()  # 设置所有事件以取消正在进行的请求
        self._cancel_events.clear()
        
        # 清理模拟响应
        self._mock_responses.clear()
        
        # 重置模拟模式
        self._mock_mode = False
        
        global_logger.info("HTTP客户端状态已重置")

# 创建全局HTTP客户端实例，使用默认配置
global_http_client = HttpClient()
