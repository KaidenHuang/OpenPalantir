from sqlalchemy.orm import Session
from models.task import Task
from datetime import datetime

class TaskService:
    @staticmethod
    def create_task(db: Session, type: str, document_id: str = None, status: str = "pending", task_id: str = None):
        """
        创建新任务
        """
        import uuid
        # 如果没有提供task_id，生成一个新的UUID
        if not task_id:
            task_id = str(uuid.uuid4())
        db_task = Task(
            id=task_id,
            type=type,
            status=status,
            file_id=document_id
        )
        db.add(db_task)
        db.commit()
        db.refresh(db_task)
        return db_task
    
    @staticmethod
    def get_task(db: Session, task_id: str):
        """
        获取任务
        """
        return db.query(Task).filter(Task.id == task_id).first()
    
    @staticmethod
    def get_tasks(db: Session, skip: int = 0, limit: int = 100):
        """
        获取任务列表
        """
        return db.query(Task).offset(skip).limit(limit).all()
    
    @staticmethod
    def update_task(db: Session, task_id: int, **kwargs):
        """
        更新任务信息
        """
        db_task = db.query(Task).filter(Task.id == task_id).first()
        if db_task:
            # 如果状态变为completed，更新完成时间
            if kwargs.get("status") == "completed" and db_task.complete_time is None:
                kwargs["complete_time"] = datetime.now()
            for key, value in kwargs.items():
                setattr(db_task, key, value)
            db.commit()
            db.refresh(db_task)
        return db_task
    
    @staticmethod
    def delete_task(db: Session, task_id: int):
        """
        删除任务
        """
        db_task = db.query(Task).filter(Task.id == task_id).first()
        if db_task:
            db.delete(db_task)
            db.commit()
        return db_task
