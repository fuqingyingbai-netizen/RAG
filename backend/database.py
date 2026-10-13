import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# 数据库连接URL，优先从环境变量读取，默认使用本地PostgreSQL（库名langchain_app）
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/langchain_app",
)

# 创建数据库引擎，pool_pre_ping=True：每次连接前检查可用性，避免失效连接
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)

# 创建数据库会话工厂：绑定引擎、关闭自动刷新/自动提交、提交后不立即过期对象
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False
)

# 声明式基类：所有ORM模型需继承此类，用于统一管理表元数据
Base = declarative_base()


def init_db() -> None:
    """
    初始化数据库（创建所有表）
    延迟导入models：避免循环依赖（models依赖Base，若提前导入会导致Base未初始化）
    """
    import models  # noqa: F401（抑制"导入未使用"的语法提示）
    # 根据Base的元数据（models中定义的表结构）创建所有表
    Base.metadata.create_all(bind=engine)