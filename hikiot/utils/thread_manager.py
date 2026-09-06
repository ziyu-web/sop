import queue
import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Callable, Dict, List, Any, Optional, Union
from enum import Enum
from hikiot.utils.log_manager import global_logger

class TaskPriority(Enum):
    """任务优先级枚举类"""
    LOW = 3
    MEDIUM = 2
    HIGH = 1
    CRITICAL = 0

class PriorityQueueItem:
    """优先级队列项，用于包装任务及其优先级"""
    def __init__(self, priority: Union[TaskPriority, int], task: Callable, args: tuple = None, kwargs: dict = None):
        self.priority = priority.value if isinstance(priority, TaskPriority) else priority
        self.task = task
        self.args = args or ()
        self.kwargs = kwargs or {}
        # 添加时间戳用于相同优先级的FIFO排序
        self.timestamp = time.time()
        
    def __lt__(self, other):
        # 优先比较优先级，优先级相同时比较时间戳
        if self.priority == other.priority:
            return self.timestamp < other.timestamp
        return self.priority < other.priority

class ThreadManager:
    """线程管理模块，用于高效管理线程池和处理高并发任务"""
    _instance = None
    _lock = threading.RLock()
    
    def __new__(cls, *args, **kwargs):
        """实现单例模式"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ThreadManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, max_workers: int = None, queue_size: int = 1000):
        """
        初始化线程管理器
        
        :param max_workers: 最大工作线程数，默认为CPU核心数*2
        :param queue_size: 任务队列大小限制，默认为1000
        """
        # 确保单例初始化只会执行一次
        with self._lock:
            if not hasattr(self, '_initialized'):
                # 如果未指定最大线程数，使用CPU核心数*2
                if max_workers is None:
                    import os
                    max_workers = os.cpu_count() * 2 if os.cpu_count() else 4
                    
                self.max_workers = max_workers
                self.queue_size = queue_size
                
                # 创建线程池执行器
                self.executor = ThreadPoolExecutor(
                    max_workers=max_workers,
                    thread_name_prefix="ThreadManager",
                    initializer=self._worker_initializer,
                    initargs=(self._lock,)
                )
                
                # 创建优先级任务队列
                self.priority_queue = queue.PriorityQueue(maxsize=queue_size)
                
                # 线程池状态
                self._running = True
                
                # 用于跟踪任务的字典
                self.tasks: Dict[str, Future] = {}
                
                # 任务计数器，用于生成唯一任务ID
                self._task_counter = 0
                self._task_counter_lock = threading.Lock()
                
                # 启动任务调度线程
                self._scheduler_thread = threading.Thread(
                    target=self._scheduler,
                    daemon=True,
                    name="SchedulerThread"
                )
                self._scheduler_thread.start()
                
                # 统计信息
                self._stats = {
                    "tasks_submitted": 0,
                    "tasks_completed": 0,
                    "tasks_failed": 0,
                    "queue_length": 0
                }
                self._stats_lock = threading.Lock()
                
                # 初始化标记
                self._initialized = True
                
                global_logger.info(f"线程管理器初始化成功: 最大线程数={max_workers}, 队列大小={queue_size}")
    
    def _worker_initializer(self, lock):
        """工作线程初始化函数"""
        # 可以在这里设置线程的一些属性
        pass
    
    def _scheduler(self):
        """任务调度器，从队列中获取任务并提交给线程池"""
        while self._running:
            try:
                # 从队列中获取优先级最高的任务
                priority_item = self.priority_queue.get(timeout=1)
                
                try:
                    # 提交任务到线程池
                    future = self.executor.submit(
                        self._task_wrapper,
                        priority_item.task,
                        priority_item.args,
                        priority_item.kwargs
                    )
                    
                    # 生成唯一任务ID并记录任务
                    task_id = self._generate_task_id()
                    with self._lock:
                        self.tasks[task_id] = future
                    
                    # 设置回调函数
                    future.add_done_callback(lambda f, tid=task_id: self._task_completed(tid, f))
                    
                    # 更新统计信息
                    with self._stats_lock:
                        self._stats["queue_length"] = self.priority_queue.qsize()
                except Exception as e:
                    task_name = priority_item.task.__name__ if hasattr(priority_item.task, '__name__') else 'anonymous'
                    global_logger.error(f"提交任务到线程池失败 [{task_name}]: {str(e)}")
                finally:
                    # 无论如何都要通知队列任务已处理，避免队列阻塞
                    self.priority_queue.task_done()
                    
            except queue.Empty:
                # 队列为空时继续循环
                continue
            except Exception as e:
                global_logger.error(f"任务调度器异常: {str(e)}")
    
    def _generate_task_id(self) -> str:
        """生成唯一任务ID"""
        with self._task_counter_lock:
            self._task_counter += 1
            return f"task_{self._task_counter}_{int(time.time() * 1000)}"
    
    def _task_wrapper(self, task: Callable, args: tuple, kwargs: dict) -> Any:
        """任务包装器，用于捕获和处理任务执行过程中的异常"""
        try:
            return task(*args, **kwargs)
        except Exception as e:
            global_logger.error(f"任务执行异常: {str(e)}")
            # 更新统计信息
            with self._stats_lock:
                self._stats["tasks_failed"] += 1
            # 重新抛出异常，让调用方能够处理
            raise
    
    def _task_completed(self, task_id: str, future: Future):
        """任务完成回调函数"""
        # 更新统计信息
        with self._stats_lock:
            self._stats["tasks_completed"] += 1
        
        # 从任务字典中移除已完成的任务
        with self._lock:
            if task_id in self.tasks:
                del self.tasks[task_id]
    
    def submit_task(self, task: Callable, *args, priority: Union[TaskPriority, int] = TaskPriority.MEDIUM, **kwargs) -> str:
        """
        提交任务到线程管理器
        
        :param task: 要执行的任务函数
        :param args: 任务函数的位置参数
        :param priority: 任务优先级，默认为MEDIUM
        :param kwargs: 任务函数的关键字参数
        :return: 任务ID，可用于后续跟踪任务状态
        """
        if not self._running:
            raise RuntimeError("线程管理器已停止，无法提交新任务")
        
        try:
            # 创建优先级队列项
            priority_item = PriorityQueueItem(priority, task, args, kwargs)
            
            # 将任务添加到优先级队列
            self.priority_queue.put(priority_item, block=False)
            
            # 更新统计信息
            with self._stats_lock:
                self._stats["tasks_submitted"] += 1
                self._stats["queue_length"] = self.priority_queue.qsize()
            
            global_logger.debug(f"任务提交成功: {task.__name__ if hasattr(task, '__name__') else 'anonymous'}，优先级: {priority}")
            
            # 由于任务ID是在调度器中生成的，这里返回一个临时ID，实际使用中可以通过get_stats()查看任务状态
            return f"submitted_{int(time.time() * 1000)}"
            
        except queue.Full:
            error_msg = "任务队列已满，无法提交新任务"
            global_logger.error(error_msg)
            raise RuntimeError(error_msg)
        except Exception as e:
            global_logger.error(f"提交任务失败: {str(e)}")
            raise
    
    def submit_high_priority_task(self, task: Callable, *args, **kwargs) -> str:
        """提交高优先级任务"""
        return self.submit_task(task, *args, priority=TaskPriority.HIGH, **kwargs)
    
    def submit_critical_task(self, task: Callable, *args, **kwargs) -> str:
        """提交关键优先级任务"""
        return self.submit_task(task, *args, priority=TaskPriority.CRITICAL, **kwargs)
    
    def submit_low_priority_task(self, task: Callable, *args, **kwargs) -> str:
        """提交低优先级任务"""
        return self.submit_task(task, *args, priority=TaskPriority.LOW, **kwargs)
    
    def get_stats(self) -> Dict[str, int]:
        """获取线程管理器统计信息"""
        with self._stats_lock:
            # 返回统计信息的副本，避免并发修改问题
            return self._stats.copy()
    
    def get_queue_size(self) -> int:
        """获取当前队列中的任务数量"""
        return self.priority_queue.qsize()
    
    def shutdown(self, wait: bool = True):
        """
        关闭线程管理器
        
        :param wait: 是否等待所有任务完成，默认为True
        """
        with self._lock:
            if not self._running:
                return
            
            self._running = False
            
            # 如果设置了等待，等待队列中的任务都被处理
            if wait:
                # 等待任务队列中的所有任务都被处理
                self.priority_queue.join()
            
            # 关闭线程池
            self.executor.shutdown(wait=wait)
            
            global_logger.info(f"线程管理器已关闭，等待任务完成: {wait}")

# 创建全局线程管理器实例
# 默认最大线程数为CPU核心数*2，队列大小为1000
global_thread_manager = ThreadManager()

def get_thread_manager() -> ThreadManager:
    """获取全局线程管理器实例"""
    return global_thread_manager
