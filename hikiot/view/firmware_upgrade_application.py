"""
海康威视海康互联开放平台 - 固件升级应用视图
功能：固件升级压力测试工具的主界面
"""

import tkinter as tk
import pygubu
from hikiot.utils.log_manager import global_logger
from hikiot.utils.path_manager import global_path_manager


class FirmwareUpgradeApplication:
    """固件升级应用视图类"""
    
    def __init__(self):
        self.root = None
        self.builder = None
        self.log_text = None  # 日志输出文本框
        
    def initialize_ui(self, master=None):
        """初始化用户界面"""
        try:
            # 创建PyGubu构建器
            self.builder = pygubu.Builder()
            
            # 加载UI文件
            import os
            ui_file_path = os.path.join(
                global_path_manager.get_resource_directory(),
                'hikiot',
                'view',
                'firmware_upgrade.ui'
            )
            
            self.builder.add_from_file(ui_file_path)
            
            if master:
                # 嵌入模式：加载 MainFrame 到 master
                self.root = master  # root 指向父容器
                self.main_window = self.builder.get_object('MainFrame', master)
                # 手动 Pack MainFrame
                self.main_window.pack(fill='both', expand=True)
            else:
                # 独立模式
                self.root = tk.Tk()
                self.root.withdraw()  # 隐藏默认的根窗口
                self.main_window = self.builder.get_object('FirmwareUpgradeWindow', self.root)
                self.main_window.protocol("WM_DELETE_WINDOW", self.close)
                
                # 设置窗口属性
                self.main_window.title("海康威视海康互联开放平台 - 固件升级压力测试工具")
                
                # 设置窗口图标
                try:
                    icon_path = os.path.join(
                        global_path_manager.get_resource_directory(),
                        'hikiot',
                        'resources',
                        'icon.ico'
                    )
                    if os.path.exists(icon_path):
                        self.main_window.iconbitmap(icon_path)
                except Exception:
                    pass
            
            # 配置滚动条
            self._configure_scrollbars()
            
            # 配置设备树的点击事件
            self._configure_device_tree()
            
            # 动态添加删除按钮
            self._add_extra_components()
            
            # 隐藏固件选择相关控件（统一从Excel读取固件路径）
            self._hide_firmware_controls()
            
            # 隐藏不再使用的控件
            self._hide_unused_controls()
            
            # 隐藏刷新进度按钮（改为自动3秒刷新）
            self._hide_refresh_progress_button()
            
            # 配置日志文本框
            self._configure_log_text()
            
            # 确保主布局与日志区随窗口等比缩放
            self._configure_resize_behavior()
            
            global_logger.info("固件升级应用UI初始化完成")
            
        except Exception as e:
            global_logger.error(f"初始化固件升级应用UI时出错: {str(e)}")
            raise

    def _add_extra_components(self):
        """动态添加额外的UI组件"""
        try:
            # 在FileFrame中添加删除设备按钮
            file_frame = self.builder.get_object('FileFrame')
            import tkinter.ttk as ttk

            if file_frame:
                self.btn_delete_device = ttk.Button(file_frame, text="删除选中设备")
                # 布局在 row=1, column=4 (紧跟在批量添加设备后面)
                self.btn_delete_device.grid(row=1, column=4, padx=5, pady=2, sticky='w')

                self.btn_select_all = ttk.Button(file_frame, text="全选所有")
                # 布局在 row=1, column=5
                self.btn_select_all.grid(row=1, column=5, padx=5, pady=2, sticky='w')
        except Exception as e:
            global_logger.warning(f"添加额外组件失败: {e}")

    def _hide_unused_controls(self):
        """隐藏不再使用的Token状态标签"""
        try:
            label_token_status = self.builder.get_object('Label_token_status')
            if label_token_status:
                try:
                    label_token_status.grid_remove()
                except Exception:
                    try:
                        label_token_status.pack_forget()
                    except Exception:
                        pass
        except Exception as e:
            global_logger.warning(f"隐藏Token状态标签失败: {e}")
    
    def _hide_refresh_progress_button(self):
        """隐藏刷新进度按钮（改为自动3秒刷新）"""
        try:
            btn_refresh = self.builder.get_object('Button_refresh_progress')
            if btn_refresh:
                try:
                    btn_refresh.grid_remove()
                except Exception:
                    try:
                        btn_refresh.pack_forget()
                    except Exception:
                        pass
                global_logger.info("已隐藏刷新进度按钮")
        except Exception as e:
            global_logger.warning(f"隐藏刷新进度按钮失败: {e}")
    
    def _configure_resize_behavior(self):
        """配置主布局与日志区随窗口等比缩放（避免缩放时日志区宽度不变）"""
        try:
            # MainFrame 内部用 grid 放置左侧区与右侧日志区，显式设置列/行权重确保缩放时分配空间
            main = self.main_window
            if main:
                main.grid_columnconfigure(0, weight=3)   # 左侧配置+设备列表
                main.grid_columnconfigure(1, weight=1)   # 右侧日志区
                main.grid_rowconfigure(0, weight=1)      # 顶部配置行
                main.grid_rowconfigure(1, weight=3)      # 下方设备列表行
            log_frame = self.builder.get_object('LogFrame')
            if log_frame:
                log_frame.grid_columnconfigure(0, weight=1)  # 日志文本框列参与缩放
                log_frame.grid_rowconfigure(0, weight=1)     # 日志行参与缩放
        except Exception as e:
            global_logger.warning(f"配置缩放行为失败: {e}")

    def _configure_log_text(self):
        """配置右侧日志文本框"""
        try:
            text_log = self.builder.get_object('Text_log')
            scrollbar_log = self.builder.get_object('Scrollbar_log')
            if text_log and scrollbar_log:
                # 绑定滚动条
                text_log.configure(yscrollcommand=scrollbar_log.set)
                scrollbar_log.configure(command=text_log.yview)
                # 设置字体
                text_log.configure(font=('Consolas', 9))
                # 暴露给日志管理器使用
                self.log_text = text_log
                global_logger.set_main_application(self)
                global_logger.info("日志文本框已就绪")
        except Exception as e:
            global_logger.warning(f"配置日志文本框失败: {e}")
            self.log_text = None

    def _hide_firmware_controls(self):
        try:
            label = self.builder.get_object('Label_firmware')
            btn = self.builder.get_object('Button_select_firmware')
            entry = self.builder.get_object('Entry_firmware_path')
            for widget in (label, btn, entry):
                if not widget:
                    continue
                try:
                    widget.grid_remove()
                except Exception:
                    try:
                        widget.pack_forget()
                    except Exception:
                        pass
        except Exception as e:
            global_logger.warning(f"隐藏固件选择控件失败: {e}")

    
    def _configure_scrollbars(self):
        """配置滚动条"""
        try:
            # 获取树形控件和滚动条
            treeview = self.builder.get_object('Treeview_upgrade_devices')
            v_scrollbar = self.builder.get_object('Scrollbar_vertical')
            h_scrollbar = self.builder.get_object('Scrollbar_horizontal')
            
            # 配置垂直滚动条
            if treeview and v_scrollbar:
                treeview.configure(yscrollcommand=v_scrollbar.set)
                v_scrollbar.configure(command=treeview.yview)
            
            # 配置水平滚动条
            if treeview and h_scrollbar:
                treeview.configure(xscrollcommand=h_scrollbar.set)
                h_scrollbar.configure(command=treeview.xview)
                
        except Exception as e:
            global_logger.warning(f"配置滚动条时出错: {str(e)}")
    
    def _configure_device_tree(self):
        """配置设备树的交互功能"""
        try:
            treeview = self.builder.get_object('Treeview_upgrade_devices')
            if treeview:
                # 绑定双击事件来切换选择状态
                treeview.bind('<Double-1>', self._on_device_tree_double_click)
                # 绑定右键菜单
                treeview.bind('<Button-3>', self._on_device_tree_right_click)
                
        except Exception as e:
            global_logger.warning(f"配置设备树时出错: {str(e)}")
    
    def _on_device_tree_double_click(self, event):
        """设备树双击事件处理"""
        try:
            treeview = event.widget
            item = treeview.selection()[0] if treeview.selection() else None
            
            if item:
                # 获取当前值
                values = list(treeview.item(item, 'values'))
                
                # 切换选择状态
                if values[0] == '☐':
                    values[0] = '☑'
                elif values[0] == '☑':
                    values[0] = '☐'
                
                # 更新显示
                treeview.item(item, values=values)
                
        except Exception as e:
            global_logger.warning(f"处理设备树双击事件时出错: {str(e)}")
    
    def _on_device_tree_right_click(self, event):
        """设备树右键菜单事件处理"""
        try:
            treeview = event.widget
            
            # 创建右键菜单
            context_menu = tk.Menu(self.root, tearoff=0)
            context_menu.add_command(label="全选", command=lambda: self._select_all_devices(True))
            context_menu.add_command(label="全不选", command=lambda: self._select_all_devices(False))
            context_menu.add_separator()
            context_menu.add_command(label="刷新", command=self._refresh_device_tree)
            
            # 显示菜单
            context_menu.post(event.x_root, event.y_root)
            
        except Exception as e:
            global_logger.warning(f"处理设备树右键菜单时出错: {str(e)}")
    
    def _select_all_devices(self, select_all: bool):
        """全选或全不选设备"""
        try:
            treeview = self.builder.get_object('Treeview_upgrade_devices')
            if not treeview:
                return
            
            select_symbol = '☑' if select_all else '☐'
            
            for item in treeview.get_children():
                values = list(treeview.item(item, 'values'))
                values[0] = select_symbol
                treeview.item(item, values=values)
                
            action = "全选" if select_all else "全不选"
            global_logger.info(f"设备列表{action}完成")
            
        except Exception as e:
            global_logger.error(f"设备列表选择操作时出错: {str(e)}")
    
    def _refresh_device_tree(self):
        """刷新设备树"""
        try:
            # 这里可以添加刷新设备树的逻辑
            global_logger.info("刷新设备树")
            
        except Exception as e:
            global_logger.error(f"刷新设备树时出错: {str(e)}")
    
    def get_ui_component(self, component_name: str):
        """获取UI组件"""
        try:
            return self.builder.get_object(component_name)
        except Exception as e:
            global_logger.warning(f"获取UI组件 {component_name} 时出错: {str(e)}")
            return None
    
    def show_message(self, title: str, message: str, message_type: str = "info"):
        """显示消息对话框"""
        try:
            from tkinter import messagebox
            
            if message_type == "info":
                messagebox.showinfo(title, message)
            elif message_type == "warning":
                messagebox.showwarning(title, message)
            elif message_type == "error":
                messagebox.showerror(title, message)
            else:
                messagebox.showinfo(title, message)
                
        except Exception as e:
            global_logger.error(f"显示消息对话框时出错: {str(e)}")
    
    def run(self):
        """运行应用"""
        try:
            if self.root:
                self.root.mainloop()
            else:
                global_logger.error("应用未初始化，无法运行")
                
        except Exception as e:
            global_logger.error(f"运行固件升级应用时出错: {str(e)}")
    
    def close(self):
        """关闭应用"""
        try:
            if self.root:
                self.root.quit()
                self.root.destroy()
                global_logger.info("固件升级应用已关闭")
                
        except Exception as e:
            global_logger.error(f"关闭固件升级应用时出错: {str(e)}")


# 创建全局实例
global_firmware_upgrade_app = FirmwareUpgradeApplication()
