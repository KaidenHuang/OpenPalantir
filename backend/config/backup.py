import os
import shutil
from datetime import datetime

# 数据库备份功能
def backup_database(db_path="database.db"):
    """
    备份数据库文件
    :param db_path: 数据库文件路径
    :return: 备份文件路径
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"数据库文件不存在: {db_path}")
    
    # 创建备份目录
    backup_dir = os.path.join(os.path.dirname(db_path), "backups")
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)
    
    # 生成备份文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"database_{timestamp}.db"
    backup_path = os.path.join(backup_dir, backup_filename)
    
    # 复制数据库文件
    shutil.copy2(db_path, backup_path)
    
    return backup_path

# 清理旧备份
def cleanup_old_backups(backup_dir="backups", max_backups=10):
    """
    清理旧备份文件，只保留最近的max_backups个
    :param backup_dir: 备份目录
    :param max_backups: 最大备份数量
    """
    if not os.path.exists(backup_dir):
        return
    
    # 获取所有备份文件
    backup_files = [f for f in os.listdir(backup_dir) if f.startswith("database_") and f.endswith(".db")]
    
    # 按修改时间排序
    backup_files.sort(key=lambda f: os.path.getmtime(os.path.join(backup_dir, f)))
    
    # 删除多余的备份
    while len(backup_files) > max_backups:
        old_backup = backup_files.pop(0)
        os.remove(os.path.join(backup_dir, old_backup))
