import os
import logging
import inspect
from logging.handlers import TimedRotatingFileHandler
import datetime

class Logger:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Logger, cls).__new__(cls)
            cls._instance._init_logger()
        return cls._instance
    
    def _init_logger(self):
        # 获取日志存储目录，默认为项目根目录下的logs目录
        log_dir = os.environ.get('LOG_DIR', os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '..', 'logs'))
        
        # 确保日志目录存在
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        # 获取日志级别，默认为INFO
        log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
        level_map = {
            'DEBUG': logging.DEBUG,
            'INFO': logging.INFO,
            'WARNING': logging.WARNING,
            'ERROR': logging.ERROR,
            'CRITICAL': logging.CRITICAL
        }
        level = level_map.get(log_level, logging.INFO)
        
        # 创建logger
        self.logger = logging.getLogger('OpenPalantir')
        self.logger.setLevel(level)
        
        # 避免重复添加handler
        if not self.logger.handlers:
            # 创建按日期轮转的文件handler
            log_file = os.path.join(log_dir, 'backend.log')
            file_handler = TimedRotatingFileHandler(
                log_file, 
                when='midnight', 
                interval=1, 
                backupCount=30,  # 保留30天的日志
                encoding='utf-8'
            )
            file_handler.suffix = '%Y-%m-%d.log'
            
            # 创建控制台handler
            console_handler = logging.StreamHandler()
            
            # 设置日志格式
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)
            
            # 添加handler到logger
            self.logger.addHandler(file_handler)
            # 移除控制台处理器，只输出到文件
            # self.logger.addHandler(console_handler)
    
    def debug(self, message, *args, **kwargs):
        try:
            caller_frame = inspect.currentframe().f_back
            filename = os.path.basename(caller_frame.f_code.co_filename)
            lineno = caller_frame.f_lineno
            self.logger.debug(f"{filename}:{lineno} - {message}", *args, **kwargs)
        except Exception:
            self.logger.debug(message, *args, **kwargs)
    
    def info(self, message, *args, **kwargs):
        try:
            caller_frame = inspect.currentframe().f_back
            filename = os.path.basename(caller_frame.f_code.co_filename)
            lineno = caller_frame.f_lineno
            self.logger.info(f"{filename}:{lineno} - {message}", *args, **kwargs)
        except Exception:
            self.logger.info(message, *args, **kwargs)
    
    def warning(self, message, *args, **kwargs):
        try:
            caller_frame = inspect.currentframe().f_back
            filename = os.path.basename(caller_frame.f_code.co_filename)
            lineno = caller_frame.f_lineno
            self.logger.warning(f"{filename}:{lineno} - {message}", *args, **kwargs)
        except Exception:
            self.logger.warning(message, *args, **kwargs)
    
    def error(self, message, *args, **kwargs):
        try:
            caller_frame = inspect.currentframe().f_back
            filename = os.path.basename(caller_frame.f_code.co_filename)
            lineno = caller_frame.f_lineno
            self.logger.error(f"{filename}:{lineno} - {message}", *args, **kwargs)
        except Exception:
            self.logger.error(message, *args, **kwargs)
    
    def critical(self, message, *args, **kwargs):
        try:
            caller_frame = inspect.currentframe().f_back
            filename = os.path.basename(caller_frame.f_code.co_filename)
            lineno = caller_frame.f_lineno
            self.logger.critical(f"{filename}:{lineno} - {message}", *args, **kwargs)
        except Exception:
            self.logger.critical(message, *args, **kwargs)
    
    def exception(self, message, *args, **kwargs):
        try:
            caller_frame = inspect.currentframe().f_back
            filename = os.path.basename(caller_frame.f_code.co_filename)
            lineno = caller_frame.f_lineno
            self.logger.exception(f"{filename}:{lineno} - {message}", *args, **kwargs)
        except Exception:
            self.logger.exception(message, *args, **kwargs)

# 创建全局日志实例
logger = Logger()
