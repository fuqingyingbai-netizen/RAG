# 加载.env环境变量
from dotenv import load_dotenv
import os
# 处理JSON数据（流式返回时用）
import json
# 异步编程模块（流式对话核心）
import asyncio
# 初始化LangChain聊天模型
from langchain.chat_models import init_chat_model
# 创建LangChain Agent
from langchain.agents import create_agent
# 消息类型：用户消息、AI消息、AI消息片段、系统消息
from langchain_core.messages import HumanMessage, AIMessage, AIMessageChunk, SystemMessage
# 导入自定义工具和工具状态管理函数
from tools import get_current_weather, search_knowledge_base, get_last_rag_context, reset_tool_call_guards, \
    set_rag_step_queue
# 处理时间（存储对话时记录时间戳）
from datetime import datetime
# 导入缓存模块（Redis）
from cache import cache
# 导入数据库会话
from database import SessionLocal
# 导入数据库模型（用户、会话、消息）
from models import User, ChatSession, ChatMessage

# 加载.env文件
load_dotenv()

# 从环境变量读取API密钥（OpenAI/兼容API）
API_KEY = os.getenv("ARK_API_KEY")
# 从环境变量读取模型名称（比如gpt-3.5-turbo）
MODEL = os.getenv("MODEL")
# 从环境变量读取API基础地址（比如自定义的OpenAI代理地址）
BASE_URL = os.getenv("BASE_URL")


class ConversationStorage:
    """
    对话存储类：负责对话的保存、加载、删除（PostgreSQL数据库 + Redis缓存）
    核心功能：
    1. 保存用户对话到数据库+缓存
    2. 加载用户对话（优先缓存）
    3. 列出用户所有会话
    4. 删除指定会话
    """

    @staticmethod
    def _messages_cache_key(user_id: str, session_id: str) -> str:
        """
        静态方法：生成对话消息的缓存Key（Redis）
        :param user_id: 用户ID
        :param session_id: 会话ID
        :return: 缓存Key字符串（格式：chat_messages:用户ID:会话ID）
        """
        return f"chat_messages:{user_id}:{session_id}"

    @staticmethod
    def _sessions_cache_key(user_id: str) -> str:
        """
        静态方法：生成会话列表的缓存Key
        :param user_id: 用户ID
        :return: 缓存Key字符串（格式：chat_sessions:用户ID）
        """
        return f"chat_sessions:{user_id}"

    @staticmethod
    def _to_langchain_messages(records: list[dict]) -> list:
        """
        静态方法：将数据库/缓存中的消息记录转换为LangChain的Message对象
        :param records: 消息记录列表（字典格式）
        :return: LangChain Message对象列表
        """
        messages = []
        for msg_data in records:
            # 获取消息类型（human/ai/system）
            msg_type = msg_data.get("type")
            # 获取消息内容
            content = msg_data.get("content", "")
            # 根据类型创建对应的Message对象
            if msg_type == "human":
                messages.append(HumanMessage(content=content))
            elif msg_type == "ai":
                messages.append(AIMessage(content=content))
            elif msg_type == "system":
                messages.append(SystemMessage(content=content))
        return messages

    def save(self, user_id: str, session_id: str, messages: list, metadata: dict = None,
             extra_message_data: list = None):
        """
        保存对话到数据库+缓存
        :param user_id: 用户ID
        :param session_id: 会话ID
        :param messages: LangChain Message对象列表
        :param metadata: 会话元数据（可选）
        :param extra_message_data: 额外的消息数据（比如rag_trace，可选）
        """
        # 创建数据库会话
        db = SessionLocal()
        try:
            # 根据用户名查询用户（User表）
            user = db.query(User).filter(User.username == user_id).first()
            if not user:
                # 用户不存在则直接返回
                return

            # 查询当前会话是否存在（ChatSession表）
            session = (
                db.query(ChatSession)
                .filter(ChatSession.user_id == user.id, ChatSession.session_id == session_id)
                .first()
            )
            if not session:
                # 会话不存在则创建新会话
                session = ChatSession(user_id=user.id, session_id=session_id, metadata_json=metadata or {})
                db.add(session)
                # 刷新数据库（获取会话ID）
                db.flush()
            else:
                # 会话存在则更新元数据
                session.metadata_json = metadata or {}

            # 删除当前会话的所有旧消息（避免重复）
            db.query(ChatMessage).filter(ChatMessage.session_ref_id == session.id).delete(synchronize_session=False)

            # 序列化消息并保存到数据库
            serialized = []
            # 获取当前UTC时间（时间戳）
            now = datetime.utcnow()
            for idx, msg in enumerate(messages):
                rag_trace = None
                # 如果有额外消息数据，且当前索引有效
                if extra_message_data and idx < len(extra_message_data):
                    extra = extra_message_data[idx] or {}
                    # 获取RAG追踪信息
                    rag_trace = extra.get("rag_trace")

                # 创建ChatMessage对象并添加到数据库
                db.add(
                    ChatMessage(
                        session_ref_id=session.id,  # 关联的会话ID
                        message_type=msg.type,  # 消息类型（human/ai/system）
                        content=str(msg.content),  # 消息内容
                        timestamp=now,  # 时间戳
                        rag_trace=rag_trace,  # RAG追踪信息（可选）
                    )
                )
                # 序列化消息（用于缓存）
                serialized.append(
                    {
                        "type": msg.type,
                        "content": str(msg.content),
                        "timestamp": now.isoformat(),
                        "rag_trace": rag_trace,
                    }
                )

            # 更新会话的最后更新时间
            session.updated_at = now
            # 提交数据库事务
            db.commit()

            # 将序列化的消息保存到Redis缓存
            cache.set_json(self._messages_cache_key(user_id, session_id), serialized)
            # 删除会话列表的缓存（因为会话更新了）
            cache.delete(self._sessions_cache_key(user_id))
        finally:
            # 无论是否出错，都关闭数据库会话
            db.close()

    def load(self, user_id: str, session_id: str) -> list:
        """
        加载用户的对话（优先从缓存加载）
        :param user_id: 用户ID
        :param session_id: 会话ID
        :return: LangChain Message对象列表
        """
        # 从缓存获取消息
        cached = cache.get_json(self._messages_cache_key(user_id, session_id))
        if cached is not None:
            # 缓存存在则转换为LangChain Message并返回
            return self._to_langchain_messages(cached)

        # 缓存不存在则从数据库加载
        records = self.get_session_messages(user_id, session_id)
        # 将数据库结果存入缓存
        cache.set_json(self._messages_cache_key(user_id, session_id), records)
        # 转换为LangChain Message并返回
        return self._to_langchain_messages(records)

    def list_sessions(self, user_id: str) -> list:
        """
        列出用户的所有会话ID
        :param user_id: 用户ID
        :return: 会话ID列表
        """
        return [item["session_id"] for item in self.list_session_infos(user_id)]

    def list_session_infos(self, user_id: str) -> list[dict]:
        """
        列出用户的所有会话详情（ID、最后更新时间、消息数）
        :param user_id: 用户ID
        :return: 会话详情列表
        """
        # 优先从缓存加载
        cached = cache.get_json(self._sessions_cache_key(user_id))
        if cached is not None:
            return cached

        # 缓存不存在则从数据库加载
        db = SessionLocal()
        try:
            # 查询用户
            user = db.query(User).filter(User.username == user_id).first()
            if not user:
                return []

            # 查询用户的所有会话（按最后更新时间降序）
            sessions = (
                db.query(ChatSession)
                .filter(ChatSession.user_id == user.id)
                .order_by(ChatSession.updated_at.desc())
                .all()
            )
            result = []
            for s in sessions:
                # 统计每个会话的消息数
                count = db.query(ChatMessage).filter(ChatMessage.session_ref_id == s.id).count()
                # 构造会话详情
                result.append(
                    {
                        "session_id": s.session_id,
                        "updated_at": s.updated_at.isoformat(),
                        "message_count": count,
                    }
                )
            # 存入缓存
            cache.set_json(self._sessions_cache_key(user_id), result)
            return result
        finally:
            db.close()

    def get_session_messages(self, user_id: str, session_id: str) -> list[dict]:
        """
        从数据库获取会话的所有消息（底层方法，供load调用）
        :param user_id: 用户ID
        :param session_id: 会话ID
        :return: 消息记录列表（字典格式）
        """
        # 优先从缓存加载
        cached = cache.get_json(self._messages_cache_key(user_id, session_id))
        if cached is not None:
            return cached

        # 缓存不存在则从数据库加载
        db = SessionLocal()
        try:
            # 查询用户
            user = db.query(User).filter(User.username == user_id).first()
            if not user:
                return []
            # 查询会话
            session = (
                db.query(ChatSession)
                .filter(ChatSession.user_id == user.id, ChatSession.session_id == session_id)
                .first()
            )
            if not session:
                return []

            # 查询会话的所有消息（按ID升序，即时间顺序）
            rows = (
                db.query(ChatMessage)
                .filter(ChatMessage.session_ref_id == session.id)
                .order_by(ChatMessage.id.asc())
                .all()
            )
            # 构造消息记录列表
            result = [
                {
                    "type": row.message_type,
                    "content": row.content,
                    "timestamp": row.timestamp.isoformat(),
                    "rag_trace": row.rag_trace,
                }
                for row in rows
            ]
            # 存入缓存
            cache.set_json(self._messages_cache_key(user_id, session_id), result)
            return result
        finally:
            db.close()

    def delete_session(self, user_id: str, session_id: str) -> bool:
        """
        删除指定用户的会话（数据库+缓存）
        :param user_id: 用户ID
        :param session_id: 会话ID
        :return: 是否删除成功
        """
        db = SessionLocal()
        try:
            # 查询用户
            user = db.query(User).filter(User.username == user_id).first()
            if not user:
                return False
            # 查询会话
            session = (
                db.query(ChatSession)
                .filter(ChatSession.user_id == user.id, ChatSession.session_id == session_id)
                .first()
            )
            if not session:
                return False

            # 删除会话（级联删除消息，取决于数据库模型配置）
            db.delete(session)
            db.commit()
            # 删除缓存
            cache.delete(self._messages_cache_key(user_id, session_id))
            cache.delete(self._sessions_cache_key(user_id))
            return True
        finally:
            db.close()


def create_agent_instance():
    """
    创建LangChain Agent实例（项目核心：AI对话机器人）
    :return: agent实例 + 模型实例
    """
    # 初始化聊天模型（兼容OpenAI API的模型）
    model = init_chat_model(
        model=MODEL,  # 模型名称（比如gpt-3.5-turbo）
        model_provider="openai",  # 模型提供商（openai）
        api_key=API_KEY,  # API密钥
        base_url=BASE_URL,  # API基础地址
        temperature=0.3,  # 随机性（0-1，越小越稳定）
        stream_usage=True,  # 支持流式输出
    )

    # 创建Agent（绑定模型和工具）
    agent = create_agent(
        model=model,
        # 绑定的工具列表：天气查询 + 知识库检索
        tools=[get_current_weather, search_knowledge_base],
        # 系统提示词（Agent的行为准则）
        system_prompt=(
            "You are a cute cat bot that loves to help users. "  # 人设：可爱的猫咪机器人
            "When responding, you may use tools to assist. "  # 可以使用工具辅助回答
            "Use search_knowledge_base when users ask document/knowledge questions. "  # 文档/知识问题用知识库工具
            "Do not call the same tool repeatedly in one turn. At most one knowledge tool call per turn. "  # 本轮不重复调用工具，知识库工具最多1次
            "Once you call search_knowledge_base and receive its result, you MUST immediately produce the Final Answer based on that result. "  # 调用知识库后必须立即生成最终答案
            "After receiving search_knowledge_base result, you MUST NOT call any tool again (including get_current_weather or search_knowledge_base). "  # 调用知识库后不能再调用任何工具
            "If the retrieved context is insufficient, answer honestly that you don't know instead of making up facts. "  # 上下文不足时诚实说不知道，不编造
            "If tool results include a Step-back Question/Answer, use that general principle to reason and answer, "  # 如果有回溯问题/答案，用其推理
            "but do not reveal chain-of-thought. "  # 不暴露思考过程
            "If you don't know the answer, admit it honestly."  # 不知道就承认
        ),
    )
    return agent, model


# 初始化Agent和模型（全局单例）
agent, model = create_agent_instance()

# 初始化对话存储实例（全局单例）
storage = ConversationStorage()


def summarize_old_messages(model, messages: list) -> str:
    """
    总结旧消息（当对话数超过50条时，总结前40条，避免上下文过长）
    :param model: 聊天模型实例
    :param messages: 旧消息列表
    :return: 消息摘要字符串
    """
    # 提取旧对话并格式化
    old_conversation = "\n".join([
        f"{'用户' if msg.type == 'human' else 'AI'}: {msg.content}"
        for msg in messages
    ])

    # 生成摘要的提示词
    summary_prompt = f"""请总结以下对话的关键信息：

{old_conversation}
总结（包含用户信息、重要事实、待办事项）："""

    # 调用模型生成摘要
    summary = model.invoke(summary_prompt).content
    return summary


def chat_with_agent(user_text: str, user_id: str = "default_user", session_id: str = "default_session"):
    """
    非流式对话接口：处理用户消息，返回完整响应
    :param user_text: 用户输入的文本
    :param user_id: 用户ID（默认default_user）
    :param session_id: 会话ID（默认default_session）
    :return: 包含响应内容和rag_trace的字典
    """
    # 加载用户的历史对话
    messages = storage.load(user_id, session_id)

    # 清理残留的RAG上下文（避免跨请求污染）
    get_last_rag_context(clear=True)
    # 重置工具调用计数（本轮对话开始）
    reset_tool_call_guards()

    # 如果历史消息超过50条，总结前40条，减少上下文长度
    if len(messages) > 50:
        summary = summarize_old_messages(model, messages[:40])

        # 保留总结 + 最后10条消息
        messages = [
                       SystemMessage(content=f"之前的对话摘要：\n{summary}")
                   ] + messages[40:]

    # 添加用户的新消息到对话列表
    messages.append(HumanMessage(content=user_text))
    # 调用Agent处理对话
    result = agent.invoke(
        {"messages": messages},
        config={"recursion_limit": 8},  # 递归限制：最多调用8次工具
    )

    # 解析Agent的响应内容
    response_content = ""
    if isinstance(result, dict):
        # 如果是字典，优先取output字段
        if "output" in result:
            response_content = result["output"]
        # 其次取messages的最后一条
        elif "messages" in result and result["messages"]:
            msg = result["messages"][-1]
            response_content = getattr(msg, "content", str(msg))
        # 否则转字符串
        else:
            response_content = str(result)
    # 如果是Message对象，取content字段
    elif hasattr(result, "content"):
        response_content = result.content
    # 其他情况转字符串
    else:
        response_content = str(result)

    # 将AI的响应添加到对话列表
    messages.append(AIMessage(content=response_content))

    # 获取RAG追踪信息（并清空）
    rag_context = get_last_rag_context(clear=True)
    rag_trace = rag_context.get("rag_trace") if rag_context else None

    # 构造额外的消息数据（只给最后一条AI消息加rag_trace）
    extra_message_data = [None] * (len(messages) - 1) + [{"rag_trace": rag_trace}]
    # 保存对话到数据库+缓存
    storage.save(user_id, session_id, messages, extra_message_data=extra_message_data)

    # 返回响应和RAG追踪信息
    return {
        "response": response_content,
        "rag_trace": rag_trace,
    }


async def chat_with_agent_stream(user_text: str, user_id: str = "default_user", session_id: str = "default_session"):
    """
    流式对话接口：异步处理用户消息，流式返回响应（支持实时展示RAG步骤）
    :param user_text: 用户输入的文本
    :param user_id: 用户ID
    :param session_id: 会话ID
    :yield: SSE格式的数据流（content/rag_step/trace/error）
    """
    # 加载历史对话
    messages = storage.load(user_id, session_id)

    # 清理残留的RAG上下文
    get_last_rag_context(clear=True)
    # 重置工具调用计数
    reset_tool_call_guards()

    # 创建统一的输出队列：所有事件（内容片段/RAG步骤）都放入这个队列
    output_queue = asyncio.Queue()

    class _RagStepProxy:
        """
        代理类：包装RAG步骤队列，将RAG步骤转换为统一的事件格式
        """

        def put_nowait(self, step):
            # 将RAG步骤放入输出队列，标记类型为rag_step
            output_queue.put_nowait({"type": "rag_step", "step": step})

    # 设置RAG步骤队列（替换全局变量）
    set_rag_step_queue(_RagStepProxy())

    # 消息数超过50条时总结旧消息
    if len(messages) > 50:
        summary = summarize_old_messages(model, messages[:40])
        messages = [
                       SystemMessage(content=f"之前的对话摘要：\n{summary}")
                   ] + messages[40:]

    # 添加用户新消息
    messages.append(HumanMessage(content=user_text))

    # 存储完整的AI响应（流式返回时逐步拼接）
    full_response = ""

    async def _agent_worker():
        """
        后台异步任务：运行Agent流式调用，将内容片段推入输出队列
        """
        nonlocal full_response  # 引用外部的full_response变量
        try:
            # 异步流式调用Agent
            async for msg, metadata in agent.astream(
                    {"messages": messages},
                    stream_mode="messages",  # 按消息流返回
                    config={"recursion_limit": 8},  # 递归限制
            ):
                # 只处理AI消息片段
                if not isinstance(msg, AIMessageChunk):
                    continue
                # 跳过工具调用的片段
                if getattr(msg, "tool_call_chunks", None):
                    continue

                # 解析消息内容（兼容字符串/列表格式）
                content = ""
                if isinstance(msg.content, str):
                    content = msg.content
                elif isinstance(msg.content, list):
                    for block in msg.content:
                        if isinstance(block, str):
                            content += block
                        elif isinstance(block, dict) and block.get("type") == "text":
                            content += block.get("text", "")

                # 如果有内容，拼接并推入队列
                if content:
                    full_response += content
                    await output_queue.put({"type": "content", "content": content})
        except Exception as e:
            # 捕获异常，推入错误事件
            await output_queue.put({"type": "error", "content": str(e)})
        finally:
            # 推入哨兵值（None），通知主循环Agent已完成
            await output_queue.put(None)

    # 启动后台任务
    agent_task = asyncio.create_task(_agent_worker())

    try:
        # 主循环：从输出队列取事件，流式返回给前端
        while True:
            # 等待队列中的事件
            event = await output_queue.get()
            # 哨兵值表示Agent处理完成
            if event is None:
                break
            # 将事件转换为SSE格式（Server-Sent Events）并yield
            yield f"data: {json.dumps(event)}\n\n"
    except GeneratorExit:
        # 客户端断开连接时（比如前端关闭页面），取消后台任务
        agent_task.cancel()
        try:
            await agent_task
        except asyncio.CancelledError:
            pass  # 忽略取消异常
        raise  # 重新抛出，让FastAPI正确处理
    finally:
        # 清理：重置RAG步骤队列
        set_rag_step_queue(None)
        # 确保后台任务被取消
        if not agent_task.done():
            agent_task.cancel()

    # 获取RAG追踪信息
    rag_context = get_last_rag_context(clear=True)
    rag_trace = rag_context.get("rag_trace") if rag_context else None

    # 发送RAG追踪信息事件
    if rag_trace:
        yield f"data: {json.dumps({'type': 'trace', 'rag_trace': rag_trace})}\n\n"

    # 发送结束信号
    yield "data: [DONE]\n\n"

    # 保存完整的对话到数据库+缓存
    messages.append(AIMessage(content=full_response))
    extra_message_data = [None] * (len(messages) - 1) + [{"rag_trace": rag_trace}]
    storage.save(user_id, session_id, messages, extra_message_data=extra_message_data)