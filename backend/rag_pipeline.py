# 1. 类型注解相关导入：Literal(字面量类型)、TypedDict(类型化字典)、List(列表类型)、Optional(可选类型)
#    知识点：Python 3.8+ 类型注解，提升代码可读性和静态类型检查能力
from typing import Literal, TypedDict, List, Optional
# 2. 操作系统交互模块：用于读取环境变量、文件路径等
import os
# 3. 加载 .env 文件中的环境变量：第三方库 python-dotenv 核心函数
from dotenv import load_dotenv
# 4. 初始化大语言模型：langchain 封装的统一模型初始化接口
from langchain.chat_models import init_chat_model
# 5. 状态图构建：langgraph 核心，用于构建有状态的多节点工作流
from langgraph.graph import StateGraph, END
# 6. 数据验证与模型定义：pydantic 核心，BaseModel(基础模型)、Field(字段描述)
from pydantic import BaseModel, Field

# 7. 自定义工具函数导入：检索文档、分步扩展查询、生成假设文档
from rag_utils import retrieve_documents, step_back_expand, generate_hypothetical_document
# 8. 自定义工具：发送 RAG 流程步骤日志
from tools import emit_rag_step

# 9. 加载 .env 文件到环境变量：优先加载项目根目录的 .env 文件
load_dotenv()

# 10. 从环境变量读取配置：API 密钥、基础模型、接口地址、评分模型
#     知识点：环境变量解耦配置，避免硬编码敏感信息
API_KEY = os.getenv("ARK_API_KEY")
MODEL = os.getenv("MODEL")
BASE_URL = os.getenv("BASE_URL")
GRADE_MODEL = os.getenv("GRADE_MODEL", "gpt-4.1")  # 带默认值的环境变量读取

# 11. 全局模型实例：懒加载（首次调用时初始化），避免启动时不必要的资源消耗
#     知识点：全局变量 + 懒加载模式，优化模型初始化性能
_grader_model = None
_router_model = None


# 12. 评分模型单例初始化函数
def _get_grader_model():
    # 13. 声明使用全局变量：修改全局变量需显式声明
    global _grader_model
    # 14. 配置校验：无密钥/模型名则返回 None
    if not API_KEY or not GRADE_MODEL:
        return None
    # 15. 懒加载：仅当全局实例为 None 时初始化
    if _grader_model is None:
        _grader_model = init_chat_model(
            model=GRADE_MODEL,          # 模型名称
            model_provider="openai",    # 模型提供商
            api_key=API_KEY,            # API 密钥
            base_url=BASE_URL,          # 自定义接口地址（如代理/私有部署）
            temperature=0,              # 温度：0 表示确定性输出（无随机性）
            stream_usage=True,          # 启用流式调用（节省内存）
        )
    return _grader_model


# 16. 路由模型（查询重写策略选择）单例初始化函数：逻辑同评分模型
def _get_router_model():
    global _router_model
    if not API_KEY or not MODEL:
        return None
    if _router_model is None:
        _router_model = init_chat_model(
            model=MODEL,
            model_provider="openai",
            api_key=API_KEY,
            base_url=BASE_URL,
            temperature=0,
            stream_usage=True,
        )
    return _router_model


# 17. 文档相关性评分提示词：Prompt Engineering 核心
#     知识点：提示词设计原则——明确任务、输入输出格式、判断标准
GRADE_PROMPT = (
    "You are a grader assessing relevance of a retrieved document to a user question. \n "
    "Here is the retrieved document: \n\n {context} \n\n"
    "Here is the user question: {question} \n"
    "If the document contains keyword(s) or semantic meaning related to the user question, grade it as relevant. \n"
    "Give a binary score 'yes' or 'no' score to indicate whether the document is relevant to the question."
)


# 18. 文档评分数据模型：继承 pydantic.BaseModel 实现结构化输出
#     知识点：Pydantic 数据验证 + 结构化输出，确保模型返回格式可控
class GradeDocuments(BaseModel):
    """Grade documents using a binary score for relevance check."""
    # 这个模板用来给文档打分，只有 “是 / 否” 两种结果
    # 19. 字段定义：描述 + 强制字符串类型
    binary_score: str = Field(
        description="Relevance score: 'yes' if relevant, or 'no' if not relevant"
    )


# 20. 查询重写策略模型：Literal 限制可选值，避免非法策略
#     知识点：Literal 字面量类型，强制枚举值，提升类型安全性
class RewriteStrategy(BaseModel):
    """Choose a query expansion strategy."""
    strategy: Literal["step_back", "hyde", "complex"]


# 21. RAG 流程状态字典：TypedDict 实现类型化字典（Python 3.8+）
#     知识点：TypedDict 相比普通 dict，提供静态类型检查，明确每个键的类型
class RAGState(TypedDict):
    question: str                  # 用户原始问题
    query: str                     # 当前检索用的查询词
    context: str                   # 检索到的文档拼接后的上下文
    docs: List[dict]               # 检索到的原始文档列表
    route: Optional[str]           # 流程路由（generate_answer/rewrite_question）
    expansion_type: Optional[str]  # 查询扩展策略类型
    expanded_query: Optional[str]  # 扩展后的查询词
    step_back_question: Optional[str]  # 分步扩展的问题
    step_back_answer: Optional[str]    # 分步扩展的答案
    hypothetical_doc: Optional[str]    # HyDE 生成的假设文档
    rag_trace: Optional[dict]          # RAG 流程追踪日志


# 22. 文档格式化函数：将检索到的文档列表转为可读字符串
def _format_docs(docs: List[dict]) -> str:
    # 23. 空值处理：无文档返回空字符串
    if not docs:
        return ""
    chunks = []
    # 24. 枚举文档：带索引（从 1 开始）遍历
    for i, doc in enumerate(docs, 1):
        # 25. 字典安全取值：get 方法避免 KeyError，带默认值
        source = doc.get("filename", "Unknown")
        page = doc.get("page_number", "N/A")
        text = doc.get("text", "")
        # 26. 字符串拼接：按格式组装文档片段
        chunks.append(f"[{i}] {source} (Page {page}):\n{text}")
    # 27. 分隔符拼接：多个文档片段用分隔符分隔，提升可读性
    return "\n\n---\n\n".join(chunks)


# 28. 初始检索节点：接收 RAGState，返回更新后的 RAGState
#     知识点：LangGraph 节点函数规范——输入/输出均为状态字典
def retrieve_initial(state: RAGState) -> RAGState:
    # 29. 从状态中提取用户问题
    query = state["question"]
    # 30. 发送流程日志：类型、标题、详情（截断查询词避免过长）
    emit_rag_step("🔍", "正在检索知识库...", f"查询: {query[:50]}")
    # 31. 调用检索函数：top_k=5 表示返回Top5相关文档
    retrieved = retrieve_documents(query, top_k=5)
    # 32. 提取检索结果：文档列表 + 元数据
    results = retrieved.get("docs", [])
    retrieve_meta = retrieved.get("meta", {})
    # 33. 格式化文档为上下文字符串
    context = _format_docs(results)
    # 34-36. 发送检索元数据日志：三级分块、Auto-merging 合并、检索完成
    emit_rag_step(
        "🧱",
        "三级分块检索",
        (
            f"叶子层 L{retrieve_meta.get('leaf_retrieve_level', 3)} 召回，"
            f"候选 {retrieve_meta.get('candidate_k', 0)}"
        ),
    )
    emit_rag_step(
        "🧩",
        "Auto-merging 合并",
        (
            f"启用: {bool(retrieve_meta.get('auto_merge_enabled'))}，"
            f"应用: {bool(retrieve_meta.get('auto_merge_applied'))}，"
            f"替换片段: {retrieve_meta.get('auto_merge_replaced_chunks', 0)}"
        ),
    )
    emit_rag_step("✅", f"检索完成，找到 {len(results)} 个片段", f"模式: {retrieve_meta.get('retrieval_mode', 'hybrid')}")
    # 37. 构建流程追踪日志：记录检索全量元数据，用于问题排查/分析
    # 这段代码 = 给 RAG 运行过程做【完整黑匣子记录】
    # 把每一步做了什么、用了什么功能、结果如何
    # 全部记下来，方便：调试、排查问题、看效果、日志审计 **
    rag_trace = {
        # ------------ 基础信息 ------------
        "tool_used": True,  # 我用了检索工具
        "tool_name": "search_knowledge_base",  # 工具名字：搜索知识库
        "query": query,  # 用户原始问题
        "expanded_query": query,  # 扩展后的问题（第一次就是原问题）

        # ------------ 检索结果 ------------
        "retrieved_chunks": results,  # 最终搜到的文档块
        "initial_retrieved_chunks": results,  # 第一次搜到的文档块
        "retrieval_stage": "initial",  # 阶段：第一次检索（不是重搜）

        # ------------ 重排序 Rerank 信息 ------------
        "rerank_enabled": retrieve_meta.get("rerank_enabled"),  # 重排序开没开
        "rerank_applied": retrieve_meta.get("rerank_applied"),  # 这次真的用了吗
        "rerank_model": retrieve_meta.get("rerank_model"),  # 用的哪个模型
        "rerank_endpoint": retrieve_meta.get("rerank_endpoint"),  # 模型地址
        "rerank_error": retrieve_meta.get("rerank_error"),  # 有没有报错

        # ------------ 检索模式信息 ------------
        "retrieval_mode": retrieve_meta.get("retrieval_mode"),  # 混合/语义/关键词
        "candidate_k": retrieve_meta.get("candidate_k"),  # 召回多少候选
        "leaf_retrieve_level": retrieve_meta.get("leaf_retrieve_level"),  # 搜的L3层

        # ------------ 自动合并 AutoMerge 信息 ------------
        "auto_merge_enabled": retrieve_meta.get("auto_merge_enabled"),  # 功能开没开
        "auto_merge_applied": retrieve_meta.get("auto_merge_applied"),  # 这次用没
        "auto_merge_threshold": retrieve_meta.get("auto_merge_threshold"),  # 阈值多少
        "auto_merge_replaced_chunks": retrieve_meta.get("auto_merge_replaced_chunks"),  # 替换几个
        "auto_merge_steps": retrieve_meta.get("auto_merge_steps"),  # 合并步数
    }
    # 38. 返回更新后的状态：核心字段 + 追踪日志
    return {
        "query": query,
        "docs": results,
        "context": context,
        "rag_trace": rag_trace,
    }


# 39. 文档评分节点：评估检索文档与问题的相关性
def grade_documents_node(state: RAGState) -> RAGState:
    # 40. 获取评分模型实例（懒加载）
    grader = _get_grader_model()
    emit_rag_step("📊", "正在评估文档相关性...")
    # 41. 模型未初始化：默认路由到重写查询
    if not grader:
        grade_update = {
            "grade_score": "unknown",
            "grade_route": "rewrite_question",
            "rewrite_needed": True,
        }
        # 42. 安全获取追踪日志：避免 None 导致的更新失败
        rag_trace = state.get("rag_trace", {}) or {}
        rag_trace.update(grade_update)
        return {"route": "rewrite_question", "rag_trace": rag_trace}
    # 43. 提取问题和上下文
    question = state["question"]
    context = state.get("context", "")
    # 44. 格式化评分提示词：填充问题和上下文
    prompt = GRADE_PROMPT.format(question=question, context=context)
    # 45. 结构化输出调用：with_structured_output 强制模型返回 GradeDocuments 格式
    #     知识点：LangChain 结构化输出——避免解析自然语言的繁琐和错误
    response = grader.with_structured_output(GradeDocuments).invoke(
        [{"role": "user", "content": prompt}]  # 标准 OpenAI 消息格式
    )
    # 46. 标准化评分结果：小写 + 去空格，避免大小写/空格导致的判断错误
    score = (response.binary_score or "").strip().lower()
    # 47. 路由判断：yes→生成答案，no→重写查询
    route = "generate_answer" if score == "yes" else "rewrite_question"
    # 48-50. 发送评分结果日志
    if route == "generate_answer":
        emit_rag_step("✅", "文档相关性评估通过", f"评分: {score}")
    else:
        emit_rag_step("⚠️", "文档相关性不足，将重写查询", f"评分: {score}")
    # 51. 构建评分更新日志
    grade_update = {
        "grade_score": score,
        "grade_route": route,
        "rewrite_needed": route == "rewrite_question",
    }
    # 52. 更新追踪日志
    rag_trace = state.get("rag_trace", {}) or {}
    rag_trace.update(grade_update)
    # 53. 返回路由和更新后的追踪日志
    return {"route": route, "rag_trace": rag_trace}


# 54. 查询重写节点：选择扩展策略并生成扩展查询
def rewrite_question_node(state: RAGState) -> RAGState:
    question = state["question"]
    emit_rag_step("✏️", "正在重写查询...")
    # 55. 获取路由模型实例（策略选择）
    router = _get_router_model()
    # 56. 默认策略：step_back
    strategy = "step_back"
    # 57. 模型已初始化：执行策略选择
    if router:
        prompt = (
            "请根据用户问题选择最合适的查询扩展策略，仅输出策略名。\n"
            "- step_back：包含具体名称、日期、代码等细节，需要先理解通用概念的问题。\n"
            "- hyde：模糊、概念性、需要解释或定义的问题。\n"
            "- complex：多步骤、需要分解或综合多种信息的复杂问题。\n"
            f"用户问题：{question}"
        )
        try:
            # 58. 结构化输出调用：强制返回 RewriteStrategy 格式
            decision = router.with_structured_output(RewriteStrategy).invoke(
                [{"role": "user", "content": prompt}]
            )
            strategy = decision.strategy
        # 59. 异常处理：调用失败时回退到默认策略
        except Exception:
            strategy = "step_back"

    # 60. 初始化扩展查询相关变量
    expanded_query = question
    step_back_question = ""
    step_back_answer = ""
    hypothetical_doc = ""

    # 61. step_back/complex 策略：生成分步扩展查询
    if strategy in ("step_back", "complex"):
        emit_rag_step("🧠", f"使用策略: {strategy}", "生成退步问题")
        step_back = step_back_expand(question)
        step_back_question = step_back.get("step_back_question", "")
        step_back_answer = step_back.get("step_back_answer", "")
        expanded_query = step_back.get("expanded_query", question)

    # 62. hyde/complex 策略：生成假设文档
    if strategy in ("hyde", "complex"):
        emit_rag_step("📝", "HyDE 假设性文档生成中...")
        hypothetical_doc = generate_hypothetical_document(question)

    # 63. 更新追踪日志：记录重写策略和扩展后的查询
    rag_trace = state.get("rag_trace", {}) or {}
    rag_trace.update({
        "rewrite_strategy": strategy,
        "rewrite_query": expanded_query,
    })

    # 64. 返回重写后的所有状态
    return {
        "expansion_type": strategy,
        "expanded_query": expanded_query,
        "step_back_question": step_back_question,
        "step_back_answer": step_back_answer,
        "hypothetical_doc": hypothetical_doc,
        "rag_trace": rag_trace,
    }


# 65. 扩展检索节点：基于重写后的查询/假设文档重新检索
def retrieve_expanded(state: RAGState) -> RAGState:
    # 66. 提取扩展策略（默认 step_back）
    strategy = state.get("expansion_type") or "step_back"
    emit_rag_step("🔄", "使用扩展查询重新检索...", f"策略: {strategy}")
    # 67. 初始化检索结果和元数据变量
    results: List[dict] = []
    rerank_applied_any = False
    rerank_enabled_any = False
    rerank_model = None
    rerank_endpoint = None
    rerank_errors = []
    retrieval_mode = None
    candidate_k = None
    leaf_retrieve_level = None
    auto_merge_enabled = None
    auto_merge_applied = False
    auto_merge_threshold = None
    auto_merge_replaced_chunks = 0
    auto_merge_steps = 0

    # 68. hyde/complex 策略：基于假设文档检索
    if strategy in ("hyde", "complex"):
        # 69. 安全获取假设文档（无则生成）
        hypothetical_doc = state.get("hypothetical_doc") or generate_hypothetical_document(state["question"])
        retrieved_hyde = retrieve_documents(hypothetical_doc, top_k=5)
        results.extend(retrieved_hyde.get("docs", []))
        hyde_meta = retrieved_hyde.get("meta", {})
        # 70. 发送 HyDE 检索日志
        emit_rag_step(
            "🧱",
            "HyDE 三级检索",
            (
                f"L{hyde_meta.get('leaf_retrieve_level', 3)} 召回，"
                f"候选 {hyde_meta.get('candidate_k', 0)}，"
                f"合并替换 {hyde_meta.get('auto_merge_replaced_chunks', 0)}"
            ),
        )
        # 71-78. 合并 HyDE 检索元数据：重排、检索模式、Auto-merging 等
        rerank_applied_any = rerank_applied_any or bool(hyde_meta.get("rerank_applied"))
        rerank_enabled_any = rerank_enabled_any or bool(hyde_meta.get("rerank_enabled"))
        rerank_model = rerank_model or hyde_meta.get("rerank_model")
        rerank_endpoint = rerank_endpoint or hyde_meta.get("rerank_endpoint")
        if hyde_meta.get("rerank_error"):
            rerank_errors.append(f"hyde:{hyde_meta.get('rerank_error')}")
        retrieval_mode = retrieval_mode or hyde_meta.get("retrieval_mode")
        candidate_k = candidate_k or hyde_meta.get("candidate_k")
        leaf_retrieve_level = leaf_retrieve_level or hyde_meta.get("leaf_retrieve_level")
        auto_merge_enabled = auto_merge_enabled if auto_merge_enabled is not None else hyde_meta.get("auto_merge_enabled")
        auto_merge_applied = auto_merge_applied or bool(hyde_meta.get("auto_merge_applied"))
        auto_merge_threshold = auto_merge_threshold or hyde_meta.get("auto_merge_threshold")
        auto_merge_replaced_chunks += int(hyde_meta.get("auto_merge_replaced_chunks") or 0)
        auto_merge_steps += int(hyde_meta.get("auto_merge_steps") or 0)

    # 79. step_back/complex 策略：基于扩展查询检索
    if strategy in ("step_back", "complex"):
        expanded_query = state.get("expanded_query") or state["question"]
        retrieved_stepback = retrieve_documents(expanded_query, top_k=5)
        results.extend(retrieved_stepback.get("docs", []))
        step_meta = retrieved_stepback.get("meta", {})
        # 80. 发送 Step-back 检索日志
        emit_rag_step(
            "🧱",
            "Step-back 三级检索",
            (
                f"L{step_meta.get('leaf_retrieve_level', 3)} 召回，"
                f"候选 {step_meta.get('candidate_k', 0)}，"
                f"合并替换 {step_meta.get('auto_merge_replaced_chunks', 0)}"
            ),
        )
        # 81-88. 合并 Step-back 检索元数据（逻辑同 HyDE）
        rerank_applied_any = rerank_applied_any or bool(step_meta.get("rerank_applied"))
        rerank_enabled_any = rerank_enabled_any or bool(step_meta.get("rerank_enabled"))
        rerank_model = rerank_model or step_meta.get("rerank_model")
        rerank_endpoint = rerank_endpoint or step_meta.get("rerank_endpoint")
        if step_meta.get("rerank_error"):
            rerank_errors.append(f"step_back:{step_meta.get('rerank_error')}")
        retrieval_mode = retrieval_mode or step_meta.get("retrieval_mode")
        candidate_k = candidate_k or step_meta.get("candidate_k")
        leaf_retrieve_level = leaf_retrieve_level or step_meta.get("leaf_retrieve_level")
        auto_merge_enabled = auto_merge_enabled if auto_merge_enabled is not None else step_meta.get("auto_merge_enabled")
        auto_merge_applied = auto_merge_applied or bool(step_meta.get("auto_merge_applied"))
        auto_merge_threshold = auto_merge_threshold or step_meta.get("auto_merge_threshold")
        auto_merge_replaced_chunks += int(step_meta.get("auto_merge_replaced_chunks") or 0)
        auto_merge_steps += int(step_meta.get("auto_merge_steps") or 0)

    # 89. 文档去重：基于 (文件名、页码、文本) 唯一键去重
    #     知识点：集合去重——利用不可变元组作为集合的键
    deduped = []
    seen = set()
    for item in results:
        key = (item.get("filename"), item.get("page_number"), item.get("text"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    # 90. 重新排序：为去重后的文档分配连续排名，避免重复名次
    for idx, item in enumerate(deduped, 1):
        item["rrf_rank"] = idx

    # 91. 格式化去重后的文档为上下文
    context = _format_docs(deduped)
    emit_rag_step("✅", f"扩展检索完成，共 {len(deduped)} 个片段")
    # 92. 更新追踪日志：记录扩展检索全量元数据
    rag_trace = state.get("rag_trace", {}) or {}
    rag_trace.update({
        "expanded_query": state.get("expanded_query") or state["question"],
        "step_back_question": state.get("step_back_question", ""),
        "step_back_answer": state.get("step_back_answer", ""),
        "hypothetical_doc": state.get("hypothetical_doc", ""),
        "expansion_type": strategy,
        "retrieved_chunks": deduped,
        "expanded_retrieved_chunks": deduped,
        "retrieval_stage": "expanded",
        "rerank_enabled": rerank_enabled_any,
        "rerank_applied": rerank_applied_any,
        "rerank_model": rerank_model,
        "rerank_endpoint": rerank_endpoint,
        "rerank_error": "; ".join(rerank_errors) if rerank_errors else None,
        "retrieval_mode": retrieval_mode,
        "candidate_k": candidate_k,
        "leaf_retrieve_level": leaf_retrieve_level,
        "auto_merge_enabled": auto_merge_enabled,
        "auto_merge_applied": auto_merge_applied,
        "auto_merge_threshold": auto_merge_threshold,
        "auto_merge_replaced_chunks": auto_merge_replaced_chunks,
        "auto_merge_steps": auto_merge_steps,
    })
    # 93. 返回扩展检索后的状态
    return {"docs": deduped, "context": context, "rag_trace": rag_trace}


# 94. 构建 RAG 状态图：核心流程编排
def build_rag_graph():
    # 95. 初始化状态图：指定状态类型为 RAGState
    graph = StateGraph(RAGState)
    # 96. 添加节点：节点名 + 节点函数
    # 1. 添加第一个节点：第一次检索
    graph.add_node("retrieve_initial", retrieve_initial)

    # 2. 添加第二个节点：给文档打分（判断相关不相关）
    graph.add_node("grade_documents", grade_documents_node)

    # 3. 添加第三个节点：重写问题（不好就改写）
    graph.add_node("rewrite_question", rewrite_question_node)

    # 4. 添加第四个节点：用改写后的问题重新检索
    graph.add_node("retrieve_expanded", retrieve_expanded)

    # 97. 设置入口节点：流程从初始检索开始
    graph.set_entry_point("retrieve_initial")
    # 98. 添加固定边：初始检索 → 文档评分
    graph.add_edge("retrieve_initial", "grade_documents")
    # 99. 添加条件边：根据评分节点的 route 字段路由
    #     知识点：LangGraph 条件边——基于状态字段动态选择下一个节点
    graph.add_conditional_edges(
        "grade_documents",
        lambda state: state.get("route"),  # 路由判断函数
        {
            "generate_answer": END,        # 相关性通过 → 结束流程（外部生成答案）
            "rewrite_question": "rewrite_question",  # 相关性不足 → 重写查询
        },
    )
    # 100-101. 添加固定边：重写查询 → 扩展检索 → 结束流程
    graph.add_edge("rewrite_question", "retrieve_expanded")
    graph.add_edge("retrieve_expanded", END)
    # 102. 编译状态图：生成可执行的流程对象
    return graph.compile()


# 103. 编译 RAG 流程：全局实例，避免重复编译
rag_graph = build_rag_graph()


# 104. 运行 RAG 流程的入口函数：接收用户问题，返回最终状态
def run_rag_graph(question: str) -> dict:
    # 105. 调用流程：初始化状态字典，invoke 执行流程
    return rag_graph.invoke({
        "question": question,
        "query": question,
        "context": "",
        "docs": [],
        "route": None,
        "expansion_type": None,
        "expanded_query": None,
        "step_back_question": None,
        "step_back_answer": None,
        "hypothetical_doc": None,
        "rag_trace": None,
    })