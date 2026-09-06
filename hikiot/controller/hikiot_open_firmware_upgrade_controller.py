# -*- coding: utf-8 -*-
"""
Hikvision IoT 平台 - 固件升级控制器
基于标准 ISAPI 协议实现设备固件升级任务创建与进度监控
支持多轮循环升级 + 自动 Token 管理
"""

import threading
import time
import json
from typing import Dict, List, Any, Optional
from hikiot.model.hikiot_open_auth_app_access_token import global_app_access_token_model
from hikiot.model.hikiot_open_auth_user_access_token import global_user_access_token_model
from hikiot.model.hikiot_open_device_management import global_device_management_model
from hikiot.model.hikiot_open_get_device_info import global_device_info_model
from hikiot.model.hikiot_open_firmware_upgrade import global_firmware_upgrade_model
from hikiot.utils.log_manager import global_logger
from hikiot.utils.thread_manager import global_thread_manager
from hikiot.utils.excel_processor import global_excel_processor


from datetime import datetime


class UpgradeRoundRecord:
    """单轮升级记录"""
    def __init__(self, round_idx: int):
        self.round_idx = round_idx
        self.success = False
        self.start_time = None
        self.end_time = None
        self.error_status = ""  # 错误状态码
        self.error_message = ""  # 错误消息
        self.is_timeout = False  # 是否超时
        self.timeout_start = None  # 超时开始时间
        self.timeout_end = None  # 超时结束时间
        # 新增：升级前/后的版本号，便于在报表中对比
        self.pre_version = ""    # 升级前版本
        self.post_version = ""   # 升级后版本


class DeviceUpgradeWorker:
    """设备独立升级工作器 - 每个设备一个实例"""
    
    # 失败状态列表（直接判定失败）
    FAILED_STATUSES = ['failed', 'languageMismatch', 'writeFlashError', 
                       'packageTypeMismatch', 'packageVersionMismatch', 'network_error']
    
    # 中间态状态列表（继续等待）
    INTERMEDIATE_STATUSES = ['idle', 'error', 'preparing', 'waiting_confirm', 
                            'notUpgrade', 'unknownError', 'upgradePreparing', 'waitManualTrigger']
    
    # 正常状态列表
    NORMAL_STATUSES = ['upgrading', 'completed']
    
    # 超时时间（900秒）
    UPGRADE_TIMEOUT = 900
    
    # 进度轮询间隔（秒）：适当增大可减少请求频率，提高稳定性（原 3 秒，现 5 秒）
    PROGRESS_POLL_INTERVAL = 3
    
    def __init__(self, serial: str, verification_code: str, total_rounds: int, 
                 controller: 'HikiotFirmwareUpgradeController'):
        self.serial = serial
        self.verification_code = verification_code
        self.total_rounds = total_rounds
        self.controller = controller
        
        # 状态变量
        self.current_round = 0
        self.success_count = 0
        self.fail_count = 0
        self.is_running = False
        self.stop_flag = False
        
        # 当前任务信息
        self.current_task_id = ""
        self.current_status = "待升级"
        self.current_progress = 0
        self.current_message = ""
        
        # 升级记录（用于导出Excel）
        self.round_records: List[UpgradeRoundRecord] = []
        
    def run(self):
        """执行设备的完整升级流程"""
        self.is_running = True
        global_logger.info(f"[{self.serial}] 开始独立升级流程，共{self.total_rounds}轮")
        
        try:
            for round_idx in range(1, self.total_rounds + 1):
                if self.stop_flag:
                    global_logger.info(f"[{self.serial}] 用户停止升级")
                    break
                
                # 创建本轮记录
                record = UpgradeRoundRecord(round_idx)
                record.start_time = datetime.now()
                self.round_records.append(record)
                
                self.current_round = round_idx
                self._update_ui_round_info()
                
                global_logger.info(f"[{self.serial}] 开始第 {round_idx}/{self.total_rounds} 轮升级")
                
                # 执行单轮升级
                success, error_status, error_msg, is_timeout, timeout_start, timeout_end = self._execute_single_round(round_idx)
                
                # 更新记录
                record.end_time = datetime.now()
                record.success = success
                record.error_status = error_status
                record.error_message = error_msg
                record.is_timeout = is_timeout
                record.timeout_start = timeout_start
                record.timeout_end = timeout_end
                
                if success:
                    self.success_count += 1
                    self._update_ui_success_count()
                    global_logger.info(f"[{self.serial}] 第{round_idx}轮升级成功，累计成功{self.success_count}次")
                else:
                    self.fail_count += 1
                    if is_timeout:
                        global_logger.warning(f"[{self.serial}] 第{round_idx}轮升级超时失败")
                    else:
                        global_logger.warning(f"[{self.serial}] 第{round_idx}轮升级失败: {error_status} - {error_msg}")
                
                # 不管成功失败，都等待设备重启后进入下一轮
                if round_idx < self.total_rounds and not self.stop_flag:
                    self._wait_for_device_reboot()
                    
        except Exception as e:
            global_logger.error(f"[{self.serial}] 升级流程异常: {e}")
        finally:
            self.is_running = False
            global_logger.info(f"[{self.serial}] 升级流程结束，成功{self.success_count}/{self.total_rounds}轮，失败{self.fail_count}轮")
            
            # 通知控制器本设备升级完成
            self.controller._on_device_upgrade_complete(self.serial)
    
    def _execute_single_round(self, round_idx: int) -> tuple:
        """
        执行单轮升级
        返回: (success, error_status, error_message, is_timeout, timeout_start, timeout_end)
        """
        error_status = ""
        error_msg = ""
        is_timeout = False
        timeout_start = None
        timeout_end = None
        
        try:
            # 获取Token
            app_token = self.controller._get_app_access_token()
            user_token = self.controller._get_user_access_token(app_token)              
            # 升级前查询一次设备信息：记录升级前版本，并在UI中展示
            try:
                success, info = global_device_info_model.get_device_info(
                    app_access_token=app_token,
                    user_access_token=user_token,
                    device_serial=self.serial
                )
                if success and info.get('status') == 1:
                    version = info.get('deviceVersion', '未知')
                    global_logger.info(f"[{self.serial}] 设备在线，版本: {version}")
                    self._update_ui_version(version)
                    # 记录升级前版本到当前轮记录（仅补充数据，不改变流程）
                    try:
                        for r in self.round_records:
                            if r.round_idx == round_idx:
                                r.pre_version = version or ""
                                break
                    except Exception:
                        pass
                    time.sleep(1)
            except Exception as e:
                global_logger.debug(f"[{self.serial}] 升级前查询设备信息失败: {e}")
            
            # 决定使用哪个固件包
            use_second = (round_idx % 2 == 0)
            firmware_info = self.controller._get_firmware_info(
                use_second=use_second,
                device_serial=self.serial  # 关键：告诉 controller 查哪台设备
            )
            
            # 创建升级任务
            result = global_firmware_upgrade_model.create_upgrade_task(
                device_serial=self.serial,
                firmware_info=firmware_info,
                app_access_token=app_token,
                user_access_token=user_token
            )
            
            if not result['success']:
                error_msg = result.get('message', '创建任务失败')
                self._update_ui_status("创建失败", 0, error_msg)
                return False, "create_failed", error_msg, False, None, None
            
            self.current_task_id = result.get('task_id', '')
            
            # 检查是否需要预重启等待
            raw_resp = result.get('raw_response', '')
            if self._check_need_reboot(raw_resp):
                global_logger.info(f"[{self.serial}] 检测到需要预重启，等待30秒...")
                self._update_ui_status("预重启中", 0, "设备准备重启...")
                for i in range(30):
                    if self.stop_flag:
                        return False, "user_stopped", "用户停止", False, None, None
                    time.sleep(1)
            
            # 监控升级进度（带超时和失败状态检测）
            success, error_status, error_msg, is_timeout, timeout_start, timeout_end = self._monitor_progress_enhanced(app_token, user_token)
            return success, error_status, error_msg, is_timeout, timeout_start, timeout_end
            
        except Exception as e:
            global_logger.error(f"[{self.serial}] 单轮升级异常: {e}")
            self._update_ui_status("异常", 0, str(e)[:50])
            return False, "exception", str(e)[:100], False, None, None
    
    def _monitor_progress_enhanced(self, app_token: str, user_token: str) -> tuple:
        """
        增强版进度监控 - 支持失败状态直接判定和15分钟超时
        返回: (success, error_status, error_message, is_timeout, timeout_start, timeout_end)
        """
        start_time = time.time()
        timeout_start = None
        has_seen_normal_status = False  # 是否曾经看到过正常状态
        
        while not self.stop_flag:
            elapsed = time.time() - start_time
            
            # 15分钟超时检测
            if elapsed > self.UPGRADE_TIMEOUT:
                timeout_end = datetime.now()
                global_logger.warning(f"[{self.serial}] 升级超时（15分钟内未出现正常状态）")
                self._update_ui_status("TIMEOUT", 0, "升级超时")
                return False, "TIMEOUT", "15分钟超时", True, timeout_start, timeout_end
            
            # 查询进度
            progress_result = global_firmware_upgrade_model.get_upgrade_progress(
                device_serial=self.serial,
                app_access_token=app_token,
                user_access_token=user_token
            )
            
            if progress_result['success']:
                progress = progress_result.get('progress', 0)
                status = progress_result.get('status', 'unknown')
                raw_status = progress_result.get('raw_status', status)  # 原始状态
                message = progress_result.get('message', '')
                
                self._update_ui_status(status, progress, message)
                
                # 与 UI 一致：日志也输出 status/progress/message，便于对照（UI 的“消息”列即 message，且会截断为 50 字）
                global_logger.debug(
                    f"[{self.serial}] 进度查询: status={status}, raw_status={raw_status}, progress={progress}%, message={message!r}"
                )
                
                # 1. 检查是否是失败状态 - 直接判定失败
                if status in self.FAILED_STATUSES or raw_status in self.FAILED_STATUSES:
                    global_logger.warning(f"[{self.serial}] 检测到失败状态: {raw_status}")
                    self._update_ui_status("失败", progress, f"错误: {raw_status}")
                    return False, raw_status, message or raw_status, False, None, None
                
                # 2. 检查是否完成升级
                if progress >= 100 and status == 'completed':
                    global_logger.info(f"[{self.serial}] 升级完成")
                    return True, "", "", False, None, None
                
                # 3. 检查是否是正常升级状态
                if status in self.NORMAL_STATUSES or raw_status in ['upgrading', 'successful']:
                    if not has_seen_normal_status:
                        has_seen_normal_status = True
                        global_logger.info(f"[{self.serial}] 检测到正常升级状态: {status}")
                
                # 4. 如果还没看到正常状态，记录超时开始时间
                if not has_seen_normal_status and timeout_start is None:
                    timeout_start = datetime.now()
                
                # 5. 如果看到了正常状态，重置超时计时
                if has_seen_normal_status:
                    timeout_start = None
            
            time.sleep(self.PROGRESS_POLL_INTERVAL)
        
        # 用户停止
        return False, "user_stopped", "用户停止", False, None, None
    
    def _wait_for_device_reboot(self):
        """等待设备重启并上线"""
        global_logger.info(f"[{self.serial}] 等待设备重启...")
        self._update_ui_status("等待重启", 100, "等待设备重启...")
        
        # 先等待设备下线
        initial_wait = 300            
        for s in range(initial_wait):
            if s % 60 == 0:
                sec=initial_wait-s
                global_logger.info(f"[{self.serial}]等待设备重启 ({sec}s)...")
            time.sleep(1)
        
        # 轮询设备上线  
        max_wait = 300
        start_time = time.time()
        
        while not self.stop_flag and (time.time() - start_time < max_wait):
            try:
                app_token = self.controller._get_app_access_token()
                user_token = self.controller._get_user_access_token(app_token)
                
                success, info = global_device_info_model.get_device_info(
                    app_access_token=app_token,
                    user_access_token=user_token,
                    device_serial=self.serial
                )
                
                if success and info.get('status') == 1:
                    version = info.get('deviceVersion', '未知')
                    global_logger.info(f"[{self.serial}] 设备已上线，版本: {version}")
                    self._update_ui_version(version)
                    # 记录升级后版本到最近一轮记录（仅补充数据，不改变流程）
                    try:
                        if self.round_records:
                            self.round_records[-1].post_version = version or ""
                    except Exception:
                        pass
                    time.sleep(5)  # 额外等待5秒确保稳定
                    return
            except Exception as e:
                global_logger.debug(f"[{self.serial}] 查询设备状态异常: {e}")
            
            time.sleep(5)
        
        global_logger.warning(f"[{self.serial}] 等待设备上线超时")
    
    def _check_need_reboot(self, raw_response: str) -> bool:
        """检查响应中是否需要预重启"""
        try:
            if isinstance(raw_response, str) and raw_response.strip():
                data = json.loads(raw_response)
                return data.get("statusCode") == 7
        except:
            pass
        return False
    
    def get_upgrade_summary(self) -> Dict[str, Any]:
        """获取升级摘要（用于导出Excel）"""
        return {
            'serial': self.serial,
            'verification_code': self.verification_code,
            'total_rounds': self.total_rounds,
            'success_count': self.success_count,
            'fail_count': self.fail_count,
            'records': self.round_records
        }
    
    def _update_ui_status(self, status: str, progress: int, message: str):
        """更新UI中的状态信息"""
        self.current_status = status
        self.current_progress = progress
        self.current_message = message
        self.controller._safe_after(0, self._do_update_ui_status)
    
    def _do_update_ui_status(self):
        """在主线程中更新UI状态"""
        try:
            if not self.controller.view or not self.controller.view.root or not self.controller.view.root.winfo_exists():
                return
            tree = self.controller.view.builder.get_object('Treeview_upgrade_devices')
            for item in tree.get_children():
                values = list(tree.item(item, 'values'))
                if len(values) >= 11 and values[1] == self.serial:
                    # 更新状态、进度、消息（索引：8=状态, 9=进度, 10=消息）
                    values[8] = self.current_status
                    values[9] = f"{self.current_progress}%"
                    values[10] = (self.current_message or "")[:50]
                    tree.item(item, values=values)
                    break
        except Exception as e:
            global_logger.error(f"更新UI状态失败: {e}")
    
    def _update_ui_round_info(self):
        """更新UI中的轮次信息"""
        self.controller._safe_after(0, self._do_update_ui_round_info)
    
    def _do_update_ui_round_info(self):
        """在主线程中更新轮次信息"""
        try:
            if not self.controller.view or not self.controller.view.root or not self.controller.view.root.winfo_exists():
                return
            tree = self.controller.view.builder.get_object('Treeview_upgrade_devices')
            for item in tree.get_children():
                values = list(tree.item(item, 'values'))
                if len(values) >= 8 and values[1] == self.serial:
                    values[6] = f"{self.current_round}/{self.total_rounds}"
                    tree.item(item, values=values)
                    break
        except Exception as e:
            global_logger.error(f"更新轮次信息失败: {e}")
    
    def _update_ui_success_count(self):
        """更新UI中的成功次数和失败次数"""
        self.controller._safe_after(0, self._do_update_ui_success_count)
    
    def _do_update_ui_success_count(self):
        """在主线程中更新成功次数（显示 成功/失败 格式）"""
        try:
            if not self.controller.view or not self.controller.view.root or not self.controller.view.root.winfo_exists():
                return
            tree = self.controller.view.builder.get_object('Treeview_upgrade_devices')
            for item in tree.get_children():
                values = list(tree.item(item, 'values'))
                if len(values) >= 8 and values[1] == self.serial:
                    values[7] = f"{self.success_count}/{self.fail_count}"
                    tree.item(item, values=values)
                    break
        except Exception as e:
            global_logger.error(f"更新成功次数失败: {e}")
    
    def _update_ui_version(self, version: str):
        """更新UI中的设备版本"""
        self.controller._safe_after(0, lambda: self.controller._update_device_version_in_tree(self.serial, version))
    
    def stop(self):
        """停止升级"""
        self.stop_flag = True


class HikiotFirmwareUpgradeController:
    """Hikiot平台固件升级控制器"""

    def __init__(self, view=None):
        self.view = view
        self.upgrade_tasks: Dict[str, Dict[str, Any]] = {}  # {serial: task_info}
        self.success_stats: Dict[str, int] = {}            # 成功次数统计
        self.is_monitoring = False                         # 是否正在监控进度
        self.stop_event = threading.Event()               # 控制任务终止
        self.current_app_token = ""                        # 当前有效的 AppAccessToken
        self.current_user_token = ""                       # 当前有效的 UserAccessToken
        self.firmware_path1 = ""                           # Excel中读取的升级包1路径
        self.firmware_path2 = ""                           # Excel中读取的升级包2路径
        
        # 新增：设备独立升级管理
        self.device_workers: Dict[str, DeviceUpgradeWorker] = {}  # {serial: worker}
        
        # 新增：升级完成统计
        self.completed_devices_count = 0
        self.total_devices_count = 0
        self.completed_lock = threading.Lock()
        
        # 升级开始时间（用于导出文件命名）
        self.upgrade_start_time = None

    def set_view_callbacks(self):
        """绑定所有UI控件事件"""
        if not self.view:
            return

        try:
            builder = self.view.builder

            # 主要功能按钮
            builder.get_object('Button_select_firmware').configure(command=self.on_select_firmware_clicked)
            builder.get_object('Button_load_device_list').configure(command=self.on_load_device_list_clicked)
            builder.get_object('Button_start_upgrade').configure(command=self.on_start_upgrade_clicked)
            builder.get_object('Button_stop_upgrade').configure(command=self.on_stop_upgrade_clicked)


            # 获取双Token按钮（调试用）
            try:
                builder.get_object('get_app_access_token_button').configure(command=self.on_get_token_clicked)
            except Exception:
                pass

            # 批量添加设备
            try:
                builder.get_object('Button_batch_add_devices').configure(command=self.on_batch_add_devices_clicked)
            except Exception:
                pass

            # 绑定删除设备按钮
            if hasattr(self.view, 'btn_delete_device'):
                self.view.btn_delete_device.configure(command=self.on_delete_device_clicked)

            # 绑定全选设备按钮
            if hasattr(self.view, 'btn_select_all'):
                self.view.btn_select_all.configure(command=self.on_select_all_devices_clicked)

            # 配置Treeview列（防御性编程）
            self._configure_treeview_columns()

            # 加载默认凭据
            self._load_default_credentials()

            global_logger.info("Hikiot固件升级控制器：初始化完成")

        except Exception as e:
            global_logger.error(f"设置回调失败: {str(e)}")

    def _configure_treeview_columns(self):
        """配置设备列表Treeview"""
        try:
            tree = self.view.builder.get_object('Treeview_upgrade_devices')
            # 列顺序：0选择 1序列号 2验证码 3设备名称 4当前版本 5当前状态 6当前轮次 7成功/失败 8状态 9进度 10消息
            cols = (
                'Column_select',
                'Column_device_serial',
                'Column_verification_code',
                'Column_device_name',      # 新增：设备名称
                'Column_device_version',
                'Column_device_status',    # 新增：设备在线状态
                'Column_current_round',
                'Column_success_count',
                'status',
                'Column_progress',
                'Column_message',
            )
            tree['columns'] = cols
            tree['displaycolumns'] = cols

            headers = {
                'Column_select': '选择',
                'Column_device_serial': '设备序列号',
                'Column_verification_code': '验证码',
                'Column_device_name': '设备名称',
                'Column_device_version': '当前版本',
                'Column_device_status': '设备状态',
                'Column_current_round': '当前轮次',
                'Column_success_count': '成功/失败',
                'status': '升级状态',
                'Column_progress': '进度',
                'Column_message': '消息'
            }
            widths = {
                'Column_select': (50, 'center'),
                'Column_device_serial': (150, 'center'),
                'Column_verification_code': (120, 'center'),
                'Column_device_name': (150, 'w'),
                'Column_device_version': (120, 'center'),
                'Column_device_status': (100, 'center'),
                'Column_current_round': (80, 'center'),
                'Column_success_count': (80, 'center'),
                'status': (100, 'center'),
                'Column_progress': (80, 'center'),
                'Column_message': (220, 'w')
            }

            for col, text in headers.items():
                tree.heading(col, text=text)
                width, anchor = widths[col]
                tree.column(col, width=width, anchor=anchor)

        except Exception as e:
            global_logger.error(f"配置Treeview失败: {e}")

    def _load_default_credentials(self):
        """从JSON加载默认账号信息"""
        try:
            import os
            from hikiot.utils.path_manager import global_path_manager

            config_dir = global_path_manager.get_config_directory()
            cred_file = os.path.join(config_dir, 'default_credentials.json')

            if not os.path.exists(cred_file):
                return

            with open(cred_file, 'r', encoding='utf-8') as f:
                creds = json.load(f)

            mapping = {
                'appkey_entry': 'app_key',
                'appsecret_entry': 'app_secret',
                'username_Combobox': 'username',
                'password_entry': 'password'
            }

            for widget_name, key in mapping.items():
                if key in creds:
                    widget = self.view.builder.get_object(widget_name)
                    if hasattr(widget, 'delete'):
                        widget.delete(0, 'end')
                    if hasattr(widget, 'insert'):
                        widget.insert(0, creds[key])

            global_logger.info("已加载默认登录凭证")

        except Exception as e:
            global_logger.error(f"加载默认凭证失败: {e}")

    def _safe_after(self, delay: int, func, *args, **kwargs):
        """安全调度主线程UI更新"""
        try:
            if self.view and self.view.root and self.view.root.winfo_exists():
                self.view.root.after(delay, lambda: func(*args, **kwargs))
        except Exception:
            pass

    def _get_ui_value(self, name: str) -> str:
        """安全获取UI组件值"""
        try:
            return self.view.builder.get_object(name).get().strip()
        except Exception:
            return ""

    def _update_status_label(self, text: str):
        """更新主状态标签"""
        try:
            if not self.view or not self.view.root or not self.view.root.winfo_exists():
                return
            label = self.view.builder.get_object('Label_upgrade_status')
            label.configure(text=f"状态: {text}")
            global_logger.info(f"升级状态: {text}")
        except Exception:
            pass

    def _format_status_with_firmware(self, status_text: str) -> str:
        """组合状态文本和当前固件路径，显示在底部状态栏"""
        try:
            base = f"状态: {status_text}"
            fw1 = (self.firmware_path1 or "").strip()
            fw2 = (self.firmware_path2 or "").strip()

            extra_lines = []
            if fw1:
                extra_lines.append(f"升级包1: {fw1}")
            if fw2:
                extra_lines.append(f"升级包2: {fw2}")

            if extra_lines:
                return base + "\n" + "\n".join(extra_lines)
            return base
        except Exception:
            return f"状态: {status_text}"


    def _show_error_message(self, message: str):
        """弹窗显示错误"""
        try:
            from tkinter import messagebox
            messagebox.showerror("错误", message)
            global_logger.error(message)
        except Exception as e:
            global_logger.error(f"显示错误消息失败: {e}")

    # ==================== 按钮事件 ====================

    def on_get_token_clicked(self):
        """一键获取 AppToken + UserToken（仅用于调试/验证）"""

        def task():
            # --- 1. 获取 AppAccessToken ---
            appkey = self._get_ui_value('appkey_entry')
            appsecret = self._get_ui_value('appsecret_entry')

            if not appkey or not appsecret:
                self._safe_after(0, self._update_status_label, "❌ 失败: AppKey/Secret为空")
                return

            self._safe_after(0, self._update_status_label, "🔄 获取AppToken...")

            success_app, result_app = global_app_access_token_model.get_access_token(appkey, appsecret)

            if not success_app:
                msg = str(result_app)
                self._safe_after(0, self._update_status_label, f"❌ App失败: {msg[:100]}")
                return

            app_token = result_app['app_access_token']
            expires_in = result_app['expires_in']
            self.current_app_token = app_token
            global_logger.info(f"AppToken获取成功: {app_token[:10]}..., 剩余{expires_in:.1f}h")

            # --- 2. 获取 UserAccessToken ---
            username = self._get_ui_value('username_Combobox')
            password = self._get_ui_value('password_entry')

            if not username or not password:
                self._safe_after(0, self._update_status_label, "⚠️ User缺失: 用户名或密码为空")
                return

            self._safe_after(0, self._update_status_label, "🔄 获取UserToken...")

            success_user, result_user = global_user_access_token_model.get_user_access_token(
                app_key=appkey,
                username=username,
                password=password,
                app_access_token=app_token
            )

            if not success_user:
                msg = str(result_user)
                self._safe_after(0, self._update_status_label, f"❌ User失败: {msg[:100]}")
                return

            user_token = result_user['userAccessToken']
            self.current_user_token = user_token
            global_logger.info(f"UserToken获取成功: {user_token[:10]}...")

            self._safe_after(0, self._update_status_label, "✅ 全部成功: App+User令牌就绪")

        global_thread_manager.submit_task(task)

    def on_delete_device_clicked(self):
        """删除选中设备按钮点击事件"""
        def task():
            if not self.current_app_token or not self.current_user_token:
                self._safe_after(0, self._update_status_label, "请先获取AppToken和UserToken")
                return

            selected_devices = self._get_selected_devices()
            if not selected_devices:
                self._safe_after(0, self._update_status_label, "请选择要删除的设备")
                return

            # 提取设备序列号列表
            device_serials_to_delete = [d['serial'] for d in selected_devices]

            self._safe_after(0, self._update_status_label, f"正在删除 {len(device_serials_to_delete)} 个设备...")
            global_logger.info(f"开始删除设备: {device_serials_to_delete}")

            success, result = global_device_management_model.delete_device(
                app_access_token=self.current_app_token,
                user_access_token=self.current_user_token,
                device_serials=device_serials_to_delete
            )

            def update_ui():
                if success:
                    global_logger.info(f"设备 {device_serials_to_delete} 删除成功")
                    self._update_status_label(f"删除成功: {len(device_serials_to_delete)} 个设备")
                    # 从Treeview中移除已删除的设备
                    try:
                        tree = self.view.builder.get_object('Treeview_upgrade_devices')
                        for item_id in tree.get_children():
                            values = tree.item(item_id, 'values')
                            if values and len(values) > 1 and values[1] in device_serials_to_delete:
                                tree.delete(item_id)
                    except Exception as e:
                        global_logger.error(f"UI更新失败: {e}")
                else:
                    error_msg = str(result)
                    global_logger.error(f"删除设备失败: {error_msg}")
                    self._update_status_label(f"删除失败: {error_msg[:100]}")
            
            self._safe_after(0, update_ui)

        global_thread_manager.submit_task(task)

    def on_select_all_devices_clicked(self):
        """全选所有设备按钮点击事件"""
        try:
            if hasattr(self.view, '_select_all_devices'):
                # 调用视图的全选方法
                self.view._select_all_devices(True)
                self._update_status_label("已选中所有设备")
        except Exception as e:
            global_logger.error(f"全选设备失败: {str(e)}")

    def on_select_firmware_clicked(self):
        """选择固件文件"""
        try:
            from tkinter import filedialog
            path = filedialog.askopenfilename(
                title="选择固件包",
                filetypes=[("BIN/PKG", "*.bin *.pkg"), ("All Files", "*.*")]
            )
            if path:
                entry = self.view.builder.get_object('Entry_firmware_path')
                entry.delete(0, 'end')
                entry.insert(0, path)
        except Exception as e:
            global_logger.error(f"选择固件失败: {e}")

    def on_load_device_list_clicked(self):
        """加载Excel设备列表"""
        try:
            from tkinter import filedialog
            path = filedialog.askopenfilename(
                title="选择设备列表Excel",
                filetypes=[("Excel", "*.xlsx *.xls")]
            )
            if path:
                entry = self.view.builder.get_object('Entry_device_list_path')
                entry.delete(0, 'end')
                entry.insert(0, path)
                self._load_device_list_from_excel(path)
        except Exception as e:
            global_logger.error(f"加载设备列表失败: {e}")

    def on_batch_add_devices_clicked(self):
        """批量添加设备到团队"""
        def task():
            if not self.current_app_token:
                self._safe_after(0, self._update_status_label, "请先获取AppAccessToken")
                return

            device_tree = self.view.builder.get_object('Treeview_upgrade_devices')
            items = device_tree.get_children()

            if not items:
                self._safe_after(0, self._update_status_label, "设备列表为空")
                return

            self._safe_after(0, self._update_status_label, "正在添加设备...")
            added_count = 0
            failed_count = 0

            for item_id in items:
                values = device_tree.item(item_id)['values']
                if len(values) < 3:
                    continue
                serial = values[1].strip()
                code = values[2].strip()

                if not code:
                    self._safe_after(0, self._set_row_message, device_tree, item_id, "缺少验证码")
                    failed_count += 1
                    continue

                self._safe_after(0, self._set_row_status, device_tree, item_id, "添加中")

                success, result = global_device_management_model.add_device(
                    app_access_token=self.current_app_token,
                    user_access_token=self.current_user_token,  
                    device_serial=serial,
                    validate_code=code,
                    qr_code="",
                    add_method="DeviceToken"
                )
                # 替换原来的判断逻辑
                if success:
                    sub_code = result.get('subCode', 0)
                    if sub_code == 0:
                        self._safe_after(0, self._set_row_status, device_tree, item_id, '已添加')
                        self._safe_after(0, self._set_row_message, device_tree, item_id, '新增成功')
                        added_count += 1
                    elif sub_code == 11:
                        self._safe_after(0, self._set_row_status, device_tree, item_id, '失败')
                        self._safe_after(0, self._set_row_message, device_tree, item_id, '跨平台占用')
                        failed_count += 1

                    msg = str(result)
                    if "20017" in msg or "设备已添加在当前团队下" in msg:
                        self._safe_after(0, self._set_row_status, device_tree, item_id, "已存在")
                        self._safe_after(0, self._set_row_message, device_tree, item_id, "设备已在团队")
                        added_count += 1
                else:
                    failed_count += 1
                    msg = str(result)
                    self._safe_after(0, self._set_row_status, device_tree, item_id, "失败")
                    self._safe_after(0, self._set_row_message, device_tree, item_id, msg[:50])

                time.sleep(0.2)

                # 成功或已存在的设备，尝试查询设备信息并更新到 UI（设备名称 / 版本 / 在线状态）
                try:
                    if success:
                        self._fetch_and_update_device_info(serial)
                except Exception:
                    pass

            self._safe_after(0, self._update_status_label, f"添加完成: 成功={added_count}, 失败={failed_count}")

        global_thread_manager.submit_task(task)

    def on_start_upgrade_clicked(self):
        """开始独立升级 - 每个设备独立运行"""
        try:
            if not self._validate_params():
                return
            
            # 获取升级轮次
            try:
                loop_count = int(self._get_ui_value('Entry_loop_count'))
                if loop_count < 1:
                    loop_count = 1
            except (ValueError, TypeError):
                loop_count = 1
            
            # 获取选中的设备
            devices = self._get_selected_devices()
            if not devices:
                self._show_error_message("请选择要升级的设备")
                return
            
            # 清除之前的工作器
            self.device_workers.clear()
            self.stop_event.clear()
            
            # 初始化完成计数器
            self.completed_devices_count = 0
            self.total_devices_count = len(devices)
            self.upgrade_start_time = datetime.now()
            
            global_logger.info(f"开始独立升级模式：{len(devices)}台设备，每台{loop_count}轮")
            self._update_status_label(f"启动独立升级：{len(devices)}台设备")
            
            # 为每个设备创建独立的工作器并启动
            for device in devices:
                serial = device['serial']
                verification_code = device.get('verification_code', '')
                
                # 创建工作器
                worker = DeviceUpgradeWorker(
                    serial=serial,
                    verification_code=verification_code,
                    total_rounds=loop_count,
                    controller=self
                )
                self.device_workers[serial] = worker
                
                # 在独立线程中运行
                global_thread_manager.submit_task(worker.run, priority=1)
            
            global_logger.info(f"已启动{len(self.device_workers)}个设备的独立升级任务")

        except Exception as e:
            global_logger.error(f"启动升级失败: {e}")

    def on_stop_upgrade_clicked(self):
        """停止所有设备的升级任务"""
        self.is_monitoring = False
        self.stop_event.set()
        
        # 停止所有设备工作器
        for serial, worker in self.device_workers.items():
            worker.stop()
            global_logger.info(f"已发送停止信号给设备: {serial}")
        
        self._update_status_label("已停止所有设备升级")
        global_logger.info("用户停止了所有升级任务")


    # ==================== 核心逻辑 ====================

    def _validate_params(self) -> bool:
        """验证必要参数"""
        # 固件路径仅从Excel读取
        if not hasattr(self, 'device_firmware_map') or not self.device_firmware_map:
            self._show_error_message("请在Excel中为至少一台设备提供升级包路径（C列）")
            return False

        # ✅ 检查是否有设备的 firmware1 非空
        has_valid_firmware = any(
            fw.get('firmware1', '').strip() != ""
            for fw in self.device_firmware_map.values()
        )
        if not has_valid_firmware:
            self._show_error_message("Excel中所有设备的升级包路径（C列）均为空，请填写有效URL或文件路径")
            return False

        if not self._get_ui_value('Entry_device_list_path'):
            self._show_error_message("请选择设备列表")
            return False

        return True

    def _load_device_list_from_excel(self, path: str):
        """从Excel加载设备数据"""
        try:
            data = global_excel_processor.process_excel_file(path)
            # 从Excel数据中提取全局固件路径（升级包1/2）
            self._extract_firmware_paths_from_data(data)
            self._update_device_tree(data)
            # 更新状态栏，展示当前固件路径
            self._update_status_label("设备列表已加载")
        except Exception as e:
            self._show_error_message(f"加载失败: {e}")

    def _extract_firmware_paths_from_data(self, data: List[tuple]):
        """从Excel数据中提取固件路径（第3、4列）"""
        try:
            # 改为存储设备级映射，而非全局变量
            self.device_firmware_map = {}  # 新增字段：{serial: firmware_url}

            if not data:
                return

            for row in data:
                if not row:
                    continue
                serial = str(row[0]).strip() if len(row) > 0 else ""
                if not serial:
                    continue

                # 提取本行 firmware1（C列）
                fw1 = ""
                if len(row) > 2 and isinstance(row[2], str):
                    fw1 = row[2].strip()

                # 提取本行 firmware2（D列，可选）
                fw2 = ""
                if len(row) > 3 and isinstance(row[3], str):
                    fw2 = row[3].strip()

                # 存储：serial → (fw1, fw2)，供后续按设备查询
                self.device_firmware_map[serial] = {
                    'firmware1': fw1,
                    'firmware2': fw2
                }

            for serial, fw in self.device_firmware_map.items():
                global_logger.debug(f"  [{serial}] firmware1='{fw['firmware1']}', firmware2='{fw['firmware2']}'")

        except Exception as e:
            global_logger.error(f"❌ 解析设备固件映射失败: {e}")
    def _update_device_tree(self, data: List[tuple]):
        """更新设备树：UI 显示设备基础信息，固件URL仅存入隐藏列供逻辑使用"""
        tree = self.view.builder.get_object('Treeview_upgrade_devices')
        for item in tree.get_children():
            tree.delete(item)
        
        for row in data:
            serial = row[0] if len(row) > 0 else ""
            code = row[1] if len(row) > 1 else ""
            # 提取本行固件（C列=firmware1，D列=firmware2，用于设备级选择）
            fw1 = row[2] if len(row) > 2 else ""
            fw2 = row[3] if len(row) > 3 else ""
            
            # UI 不再展示 URL，只展示名称/版本/状态；URL 仍保存在隐藏列方便逻辑使用
            tree.insert('', 'end', values=(
                '☐',        # 0: 选择
                serial,     # 1: 序列号
                code,       # 2: 验证码
                '',         # 3: 设备名称（稍后通过 get_device_info 填充）
                '',         # 4: 当前版本
                '',         # 5: 设备状态（在线/离线等）
                '0/0',      # 6: 当前轮次
                '0',        # 7: 成功/失败
                '待升级',   # 8: 升级状态
                '0%',       # 9: 进度
                '',         # 10: 消息
                fw1,        # 11: 【隐藏】本行 firmware1（设备级）
                fw2         # 12: 【隐藏】本行 firmware2（设备级）
            ))

    def _set_row_status(self, tree, item_id, status: str):
        """更新 Treeview 某行状态列；若窗口/控件已销毁或 item 已不存在则静默返回"""
        try:
            if not tree or not tree.winfo_exists():
                return
            values = list(tree.item(item_id, 'values'))
            if len(values) < 9:
                return
            values[8] = status
            tree.item(item_id, values=values)
        except Exception:
            pass

    def _set_row_message(self, tree, item_id, msg: str):
        """更新 Treeview 某行消息列；若窗口/控件已销毁或 item 已不存在则静默返回"""
        try:
            if not tree or not tree.winfo_exists():
                return
            values = list(tree.item(item_id, 'values'))
            if len(values) < 11:
                return
            values[10] = msg
            tree.item(item_id, values=values)
        except Exception:
            pass

    def _get_selected_devices(self) -> List[Dict[str, str]]:
        """获取选中的设备"""
        selected = []
        tree = self.view.builder.get_object('Treeview_upgrade_devices')
        for item in tree.get_children():
            values = tree.item(item, 'values')
            if values and values[0] == '☑':
                selected.append({
                    'serial': values[1],
                    'verification_code': values[2]
                })
        return selected

    def _update_device_version_in_tree(self, serial: str, version: str):
        try:
            if not self.view or not self.view.root or not self.view.root.winfo_exists():
                return
            tree = self.view.builder.get_object('Treeview_upgrade_devices')
            for item in tree.get_children():
                values = list(tree.item(item, 'values'))
                if len(values) > 4 and values[1] == serial:
                    # 新列顺序：3=设备名称, 4=设备版本
                    values[4] = version or ""
                    tree.item(item, values=values)
                    break
        except Exception as e:
            global_logger.error(f"更新设备版本显示失败: {e}")

    def _update_device_info_in_tree(self, serial: str, name: str, status_text: str, version: str):
        """更新设备名称 / 版本 / 在线状态"""
        try:
            if not self.view or not self.view.root or not self.view.root.winfo_exists():
                return
            tree = self.view.builder.get_object('Treeview_upgrade_devices')
            for item in tree.get_children():
                values = list(tree.item(item, 'values'))
                if len(values) > 5 and values[1] == serial:
                    # 3=设备名称, 4=版本, 5=设备状态
                    if name is not None:
                        values[3] = name or ""
                    if version is not None:
                        values[4] = version or ""
                    if status_text is not None:
                        values[5] = status_text or ""
                    tree.item(item, values=values)
                    break
        except Exception as e:
            global_logger.error(f"更新设备信息显示失败: {e}")

    def _get_firmware_info(self, use_second: bool = False, device_serial: str = None) -> Dict[str, Any]:
        """根据设备序列号和轮次，返回其固件信息"""
        # ✅ 从设备映射字典中查找
        fw_config = self.device_firmware_map.get(device_serial)
        if not fw_config:
            global_logger.error(f"❌ 未找到设备 {device_serial} 的固件配置")
            return {'path': ''}

        # ✅ 决策逻辑：如果 firmware2 存在且为偶数轮，用 firmware2；否则用 firmware1
        if use_second and fw_config['firmware2']:
            path = fw_config['firmware2']
        else:
            path = fw_config['firmware1']

        path = (path or "").strip()
        if not path:
            global_logger.warning(f"⚠️ 设备 {device_serial} 未配置有效固件路径")
            return {'path': ''}

        return {'url': path} if path.startswith(('http://', 'https://')) else {'path': path}

    def _fetch_and_update_device_info(self, device_serial: str):
        """查询设备信息并更新到 UI（名称 / 版本 / 在线状态）"""
        try:
            app_token = self._get_app_access_token()
            if not app_token:
                return
            user_token = self._get_user_access_token(app_token)
            if not user_token:
                return

            success, info = global_device_info_model.get_device_info(
                app_access_token=app_token,
                user_access_token=user_token,
                device_serial=device_serial
            )
            if not success or not info:
                return

            name = info.get('deviceName', '') or info.get('name', '')
            version = info.get('deviceVersion', '未知')
            online = info.get('status')
            status_text = '在线' if online == 1 else '离线'

            # 在主线程更新 UI
            self._safe_after(0, self._update_device_info_in_tree, device_serial, name, status_text, version)
        except Exception as e:
            global_logger.debug(f"获取设备信息失败 [{device_serial}]: {e}")


    def _get_app_access_token(self) -> Optional[str]:
        """自动获取有效的AppAccessToken"""
        try:
            appkey = self._get_ui_value('appkey_entry').strip()
            appsecret = self._get_ui_value('appsecret_entry').strip()
            if not appkey or not appsecret:
                global_logger.warning("AppKey/Secret缺失")
                return None
            success, result = global_app_access_token_model.get_access_token(appkey, appsecret)
            if success and isinstance(result, dict):
                token = result['app_access_token']
                self.current_app_token = token
                return token
            else:
                global_logger.error(f"获取AppToken失败: {result}")
                return None
        except Exception as e:
            global_logger.error(f"获取AppToken异常: {e}")
            return None

    def _get_user_access_token(self, app_token: str) -> Optional[str]:
        """获取UserAccessToken"""
        try:
            username = self._get_ui_value('username_Combobox').strip()
            password = self._get_ui_value('password_entry').strip()
            appkey = self._get_ui_value('appkey_entry').strip()
            if not username or not password:
                global_logger.warning("用户名或密码为空")
                return None
            success, result = global_user_access_token_model.get_user_access_token(
                app_key=appkey,
                username=username,
                password=password,
                app_access_token=app_token
            )
            if success and isinstance(result, dict):
                token = result['userAccessToken']
                self.current_user_token = token
                return token
            else:
                global_logger.error(f"获取UserToken失败: {result}")
                return None
        except Exception as e:
            global_logger.error(f"获取UserToken异常: {e}")
            return None


    def _update_progress_display(self, results: List[Dict]):
        """更新UI进度（旧方法，新架构不再使用）"""
        tree = self.view.builder.get_object('Treeview_upgrade_devices')
        for item in tree.get_children():
            values = list(tree.item(item, 'values'))
            serial = values[1]
            for res in results:
                if res['device_serial'] == serial:
                    # 新列索引: 0=选择, 1=序列号, 2=验证码, 3=版本, 4=URL1, 5=URL2, 6=当前轮次, 7=成功次数, 8=状态, 9=进度, 10=消息
                    values[8] = res['status']
                    values[9] = f"{res['progress']}%"
                    values[10] = res.get('message', '')[:50]
                    tree.item(item, values=values)
                    break
    
    def stop_all_tasks(self):
        """停止所有后台任务"""
        try:
            self.is_monitoring = False
            self.stop_event.set()
            
            # 停止所有设备工作器
            for serial, worker in self.device_workers.items():
                worker.stop()
            
            global_logger.info("已发出停止信号，正在终止所有任务...")
        except Exception as e:
            global_logger.error(f"停止任务时异常: {str(e)}")
    
    def _on_device_upgrade_complete(self, serial: str):
        """设备升级完成回调 - 检查是否所有设备都完成，然后导出Excel"""
        with self.completed_lock:
            self.completed_devices_count += 1
            completed = self.completed_devices_count
            total = self.total_devices_count
        
        global_logger.info(f"[{serial}] 升级完成，已完成 {completed}/{total} 台设备")
        
        # 更新状态栏
        self._safe_after(0, lambda: self._update_status_label(f"进度: {completed}/{total} 台设备已完成"))
        
        # 检查是否所有设备都完成
        if completed >= total:
            global_logger.info("所有设备升级完成，开始导出结果...")
            self._safe_after(0, self._export_upgrade_results_to_excel)
    
    def _export_upgrade_results_to_excel(self):
        """导出升级结果到Excel文件"""
        try:
            # 窗口已关闭时不再弹窗/更新 UI，避免异常
            try:
                if not self.view or not self.view.root or not self.view.root.winfo_exists():
                    return
            except Exception:
                return
            import pandas as pd
            import os
            from hikiot.utils.path_manager import global_path_manager
            
            # 收集所有设备的升级数据
            summary_data = []
            # 详细记录改为按设备拆分到多个子表：serial -> [record_dict, ...]
            device_records: Dict[str, List[Dict[str, Any]]] = {}
            
            for serial, worker in self.device_workers.items():
                summary = worker.get_upgrade_summary()
                
                # 摘要数据
                summary_data.append({
                    '设备序列号': summary['serial'],
                    '验证码': summary['verification_code'],
                    '总轮次': summary['total_rounds'],
                    '成功次数': summary['success_count'],
                    '失败次数': summary['fail_count'],
                    '成功率': f"{(summary['success_count'] / summary['total_rounds'] * 100):.1f}%" if summary['total_rounds'] > 0 else "0%"
                })
                
                # 详细记录：增加升级前/后版本
                device_records.setdefault(serial, [])
                for record in summary['records']:
                    record_data = {
                        '轮次': record.round_idx,
                        '结果': '成功' if record.success else '失败',
                        '升级前版本': getattr(record, 'pre_version', ''),
                        '升级后版本': getattr(record, 'post_version', ''),
                        '开始时间': record.start_time.strftime('%Y-%m-%d %H:%M:%S') if record.start_time else '',
                        '结束时间': record.end_time.strftime('%Y-%m-%d %H:%M:%S') if record.end_time else '',
                        '错误状态': record.error_status if not record.success else '',
                        '错误消息': record.error_message if not record.success else '',
                        '是否超时': '是' if record.is_timeout else '否',
                        '超时开始时间': record.timeout_start.strftime('%Y-%m-%d %H:%M:%S') if record.timeout_start else '',
                        '超时结束时间': record.timeout_end.strftime('%Y-%m-%d %H:%M:%S') if record.timeout_end else ''
                    }
                    device_records[serial].append(record_data)
            
            # 生成文件名和目录
            timestamp = self.upgrade_start_time.strftime('%Y%m%d_%H%M%S') if self.upgrade_start_time else datetime.now().strftime('%Y%m%d_%H%M%S')
            data_dir = global_path_manager.get_data_directory()
            # 新建 report 目录专门存放报表
            report_dir = os.path.join(data_dir, 'report')
            os.makedirs(report_dir, exist_ok=True)
            excel_path = os.path.join(report_dir, f'upgrade_result_{timestamp}.xlsx')
            
            # 创建Excel写入器：摘要 + 每个设备一个子表
            with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
                # 写入摘要表
                df_summary = pd.DataFrame(summary_data)
                df_summary.to_excel(writer, sheet_name='升级摘要', index=False)
                
                # 为每个设备创建独立子表，便于回溯单设备的每轮记录
                for serial, records in device_records.items():
                    if not records:
                        continue
                    df_device = pd.DataFrame(records)
                    # Excel 子表名有限制，做一次简单清洗 + 截断
                    safe_name = ''.join(ch for ch in serial if ch not in r'[]:*?/\\')
                    if not safe_name:
                        safe_name = "device"
                    sheet_name = safe_name[:31]
                    df_device.to_excel(writer, sheet_name=sheet_name, index=False)
            
            global_logger.info(f"升级结果已导出到: {excel_path}")
            
            # ==================== 额外导出本次压力升级的日志副本 ====================
            try:
                # data 目录下为本次升级创建一个子目录，按设备/轮次切分日志
                run_log_root = os.path.join(data_dir, f'upgrade_logs_{timestamp}')
                os.makedirs(run_log_root, exist_ok=True)
                
                # 主日志文件路径（来自 log_manager），可能不存在则跳过
                log_path = getattr(global_logger, 'log_file', None)
                if log_path and os.path.exists(log_path):
                    # 一次性读入所有日志行，后续按设备/轮次过滤
                    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                        all_lines = f.readlines()
                    
                    # 简单的时间解析函数：从一行日志中提取时间戳（与 CustomFormatter 对应）
                    def _parse_log_time(line: str):
                        try:
                            if line.startswith('[') and len(line) >= 21:
                                ts_str = line[1:20]  # 'YYYY-MM-DD HH:MM:SS'
                                return datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
                        except Exception:
                            return None
                        return None
                    
                    # 为每个设备、每轮创建单独的日志文件
                    for serial, worker in self.device_workers.items():
                        if not worker.round_records:
                            continue
                        device_dir = os.path.join(run_log_root, serial)
                        os.makedirs(device_dir, exist_ok=True)
                        
                        for record in worker.round_records:
                            # 轮次日志文件名：round_01.log 这种
                            round_name = f"round_{record.round_idx:02d}.log"
                            round_path = os.path.join(device_dir, round_name)
                            
                            # 过滤出本设备、本轮时间窗口内的日志（若有开始/结束时间）
                            round_lines = []
                            for line in all_lines:
                                if f"[{serial}]" not in line:
                                    continue
                                if record.start_time and record.end_time:
                                    ts = _parse_log_time(line)
                                    if ts is None:
                                        continue
                                    if not (record.start_time <= ts <= record.end_time):
                                        continue
                                round_lines.append(line)
                            
                            # 写入文件（允许为空，表示该轮没有日志命中）
                            with open(round_path, 'w', encoding='utf-8', errors='ignore') as rf:
                                rf.writelines(round_lines)
                else:
                    global_logger.warning("未找到主日志文件路径，跳过本次升级日志副本导出")
            except Exception as e:
                global_logger.error(f"导出本次升级日志副本失败: {e}")
            
            # 弹窗通知用户
            from tkinter import messagebox
            
            # 计算总体统计
            total_success = sum(w.success_count for w in self.device_workers.values())
            total_fail = sum(w.fail_count for w in self.device_workers.values())
            total_rounds = sum(w.total_rounds for w in self.device_workers.values())
            success_rate = (total_success / total_rounds * 100) if total_rounds else 0.0
            
            report = f"""升级完成！

设备数量: {len(self.device_workers)}
总轮次: {total_rounds}
成功: {total_success}
失败: {total_fail}
成功率: {success_rate:.1f}%

结果已导出到:
{excel_path}"""

            # 弹窗与更新状态栏前再次确认窗口仍存在
            if self.view and self.view.root and self.view.root.winfo_exists():
                messagebox.showinfo("升级完成", report)
                self._update_status_label(f"升级完成，成功{total_success}/{total_rounds}轮，结果已导出")
            
        except Exception as e:
            global_logger.error(f"导出升级结果失败: {e}")
            import traceback
            traceback.print_exc()
            self._update_status_label(f"导出结果失败: {str(e)[:50]}")


# 创建全局实例
global_firmware_upgrade_controller = HikiotFirmwareUpgradeController()
