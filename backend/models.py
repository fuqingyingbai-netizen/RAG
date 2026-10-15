from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

# 导入数据库基类（来自database.py，所有模型继承此类）
try:
    from .database import Base
except ImportError:
    from database import Base


class User(Base):
    """用户表：存储系统用户核心信息"""
    __tablename__ = "users"  # 数据库实际表名

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)  # 主键，索引加速查询
    # 定义一个类属性叫 id
    # 它的类型是整数，由 SQLAlchemy 映射管理
    # 对应数据库的一列：
    #    类型是整数
    #    是主键
    #    建立索引加速查询
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    # index = True
    # 意思：创建索引
    # 加速查询速度！
    # 大白话：
    # 以后按用户名查用户时，速度会飞快！
    # 用户名（唯一、非空）
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)  # 密码哈希（非明文存储）
    role: Mapped[str] = mapped_column(String(20), default="user", nullable=False)  # 用户角色（默认普通用户）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)  # 创建时间（UTC时区）

    # 关联ChatSession：一对多（一个用户对应多个会话），级联删除（删除用户时删除其所有会话）
    sessions = relationship("ChatSession", back_populates="user", cascade="all, delete-orphan")
# "ChatSession",        # 我和 ChatSession 表有关系
# back_populates="user",# 互相能找到对方
# cascade="all, delete-orphan"  # 删除我，就自动删除我的所有会话

class ChatSession(Base):
    """聊天会话表：存储用户的单次聊天会话元信息"""
    __tablename__ = "chat_sessions"
    # 唯一约束：同一个用户的session_id不能重复
    __table_args__ = (UniqueConstraint("user_id", "session_id", name="uq_user_session"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)  # 主键
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)  # 关联用户表（级联删除）
    session_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)  # 会话唯一标识
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # 会话元数据（如标题、类型）
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)  # 最后更新时间
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)  # 创建时间

    # 反向关联User：多对一（多个会话属于一个用户）
    user = relationship("User", back_populates="sessions")
    # 关联ChatMessage：一对多（一个会话对应多条消息），级联删除（删除会话时删除其所有消息）
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    """聊天消息表：存储会话内的单条消息"""
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)  # 主键
    session_ref_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)  # 关联会话表（级联删除）
    message_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 消息类型（如user/assistant/system）
    content: Mapped[str] = mapped_column(Text, nullable=False)  # 消息内容（长文本）
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)  # 消息发送时间
    rag_trace: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # RAG检索溯源信息（可选，如检索的chunk ID、相似度）

    # 反向关联ChatSession：多对一（多条消息属于一个会话）
    session = relationship("ChatSession", back_populates="messages")


class ParentChunk(Base):
    """文档分块表：存储RAG场景下的文档切分后chunk信息"""
    __tablename__ = "parent_chunks"

    chunk_id: Mapped[str] = mapped_column(String(512), primary_key=True)  # 分块唯一标识（主键）
    text: Mapped[str] = mapped_column(Text, nullable=False)  # 分块文本内容
    filename: Mapped[str] = mapped_column(String(255), nullable=False, index=True)  # 源文件名（索引加速查询）
    file_type: Mapped[str] = mapped_column(String(50), default="", nullable=False)  # 文件类型（如pdf/txt/docx）
    file_path: Mapped[str] = mapped_column(String(1024), default="", nullable=False)  # 源文件路径
    page_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 源文件页码（PDF等）
    parent_chunk_id: Mapped[str] = mapped_column(String(512), default="", nullable=False)  # 父分块ID（用于分块层级关联）
    root_chunk_id: Mapped[str] = mapped_column(String(512), default="", nullable=False)  # 根分块ID（顶级分块标识）
    chunk_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 分块层级（0=顶级，数字越大层级越深）
    chunk_idx: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 同层级分块的序号
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)  # 分块更新时间
class ResearchProject(Base):
    """Consulting research project."""
    __tablename__ = "research_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    target_name: Mapped[str] = mapped_column(String(255), default="", nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(50), default="industry", nullable=False)
    industry: Mapped[str] = mapped_column(String(255), default="", nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="draft", nullable=False, index=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    created_by = relationship("User")
    sources = relationship("ResearchSource", back_populates="project", cascade="all, delete-orphan")
    artifacts = relationship("ResearchArtifact", back_populates="project", cascade="all, delete-orphan")


class ResearchSource(Base):
    """Raw or cleaned source material for a research project."""
    __tablename__ = "research_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    url: Mapped[str] = mapped_column(String(2048), default="", nullable=False)
    object_key: Mapped[str] = mapped_column(String(1024), default="", nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    credibility_score: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    project = relationship("ResearchProject", back_populates="sources")

    @validates("title", "url", "object_key", "content", "summary")
    def _postgres_text(self, _key: str, value: str) -> str:
        # PDF extractors can emit NUL bytes, which PostgreSQL text rejects.
        # Guard every source entry point, including uploads and web collection.
        return value.replace("\x00", "") if isinstance(value, str) else value


class ResearchArtifact(Base):
    """Generated project output such as cleaned facts, risk score, report, or proposal."""
    __tablename__ = "research_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    artifact_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    object_key: Mapped[str] = mapped_column(String(1024), default="", nullable=False)
    artifact_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[str] = mapped_column(String(50), default="agent", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    project = relationship("ResearchProject", back_populates="artifacts")
