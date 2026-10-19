from sqlalchemy import Column, Integer, String, Boolean, DateTime, JSON
from sqlalchemy.sql import func
from config.database import Base, SessionLocal
from system.logger import logger

class ModelInfo(Base):
    __tablename__ = "model_info"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String, index=True)
    type = Column(String, default="cloud")
    status = Column(String, default="unknown")
    models = Column(JSON, default=list)  # 以JSON格式存储模型列表数据
    enabled = Column(Boolean, default=False)
    api_url = Column(String, default="")
    api_key = Column(String, default="")
    create_time = Column(DateTime(timezone=True), server_default=func.now())
    update_time = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    def to_dict(self) -> dict:
        """
        将模型配置转换为字典格式（api_key 单向掩码：前端展示/回填用掩码值，
        掩码原样提交时 Service 层保留既有密钥；内部真实密钥消费方一律读 ORM 属性）
        """
        return {
            'id': self.id,
            'name': self.name,
            'model_type': self.type,
            'status': self.status,
            'models': self.models or [],
            'enabled': self.enabled,
            'api_url': self.api_url,
            'api_key': mask_api_key(self.api_key),
            'model_name': self.models[0] if self.models else None
        }

API_KEY_MASK = "****"


def mask_api_key(key: str) -> str:
    """api_key 展示掩码：保留首 4 尾 4，短密钥整串遮盖"""
    if not key:
        return ""
    if API_KEY_MASK in key:
        return key  # 已经是掩码值
    if len(key) <= 8:
        return API_KEY_MASK
    return f"{key[:4]}{API_KEY_MASK}{key[-4:]}"

# 初始化模型和配置
def init_models():
    """初始化默认模型和配置"""
    db = SessionLocal()
    try:
        # 数据库迁移：添加 enabled 列，删除 priority 列
        from sqlalchemy import inspect, text
        inspector = inspect(db.bind)
        columns = [col['name'] for col in inspector.get_columns('model_info')]
        if 'enabled' not in columns:
            db.execute(text("ALTER TABLE model_info ADD COLUMN enabled BOOLEAN DEFAULT 0"))
            logger.info("迁移: 添加 enabled 列到 model_info 表")
        if 'priority' in columns:
            try:
                db.execute(text("ALTER TABLE model_info DROP COLUMN priority"))
                logger.info("迁移: 从 model_info 表删除 priority 列")
            except Exception as e:
                logger.warning(f"迁移: 删除 priority 列失败（可能 SQLite 版本过低）: {e}")
        db.commit()

        # 检查是否已有模型记录
        existing_models = db.query(ModelInfo).count()
        if existing_models == 0:
            # 直接创建默认模型记录
            default_models = [
                ModelInfo(
                    name="OpenAI",
                    type="cloud",
                    status="unknown",
                    models=["gpt-4", "gpt-3.5-turbo", "gpt-4o"],
                    enabled=False,
                    api_url="https://api.openai.com/v1",
                    api_key=""
                ),
                ModelInfo(
                    name="Ollama",
                    type="local",
                    status="unknown",
                    models=["llama3", "qwen2.5:7b", "mistral:7b"],
                    enabled=False,
                    api_url="http://localhost:11434",
                    api_key=""
                ),
                ModelInfo(
                    name="DeepSeek V4",
                    type="cloud",
                    status="unknown",
                    models=["deepseek-v4-flash", "deepseek-v4-pro"],
                    enabled=False,
                    api_url="https://api.deepseek.com",
                    api_key=""
                ),
                ModelInfo(
                    name="硅基流动",
                    type="cloud",
                    status="unknown",
                    models=["deepseek-ai/DeepSeek-V3", "deepseek-ai/DeepSeek-R1"],
                    enabled=False,
                    api_url="https://api.siliconflow.cn/v1",
                    api_key=""
                ),
                ModelInfo(
                    name="OpenCode CLI",
                    type="opencode",
                    status="unknown",
                    models=["opencode/glm-5.3-flash-free"],
                    enabled=False,
                    api_url="",
                    api_key=""
                ),
            ]
            db.add_all(default_models)
            db.commit()
            logger.info("默认模型记录初始化完成")
        else:
            logger.info("模型记录已存在，跳过初始化")
    except Exception as e:
        logger.error(f"初始化默认模型记录失败: {e}")
        db.rollback()
    finally:
        db.close()