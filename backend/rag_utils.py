# -*- coding: utf-8 -*-
"""
RAG（Retrieval-Augmented Generation）工具类模块
核心功能：
1. 文档检索（混合检索/稠密检索降级）
2. 文档重排序（Rerank）
3. 文档自动合并（按父级Chunk层级合并）
4. 问题退步扩展（Step Back）：将具体问题抽象为通用问题并回答，扩展检索上下文
5. 假设性文档生成：基于用户问题生成虚拟文档辅助检索

依赖组件：
- MilvusManager：Milvus向量数据库操作客户端
- embedding_service：向量嵌入服务（稠密/稀疏向量生成）
- ParentChunkStore：父级Chunk存储管理
- init_chat_model：LangChain聊天模型初始化工具
- 环境变量：通过dotenv加载，配置各类开关、阈值、API密钥等
"""
from collections import defaultdict
from typing import List, Tuple, Dict, Any
import os
import json
import requests
from dotenv import load_dotenv

# 第三方/内部模块导入
from milvus_client import MilvusManager  # Milvus向量库管理客户端
from embedding import embedding_service as _embedding_service  # 嵌入服务（稠密/稀疏向量）
from parent_chunk_store import ParentChunkStore  # 父级Chunk存储（用于Chunk层级合并）
from langchain.chat_models import init_chat_model  # LangChain聊天模型初始化工具

# 加载.env环境变量文件
load_dotenv()

# ======================== 全局环境变量配置 ========================
# ARK API密钥（用于Step Back/假设性文档生成的大模型调用）
ARK_API_KEY = os.getenv("ARK_API_KEY")
# 大模型名称（用于Step Back/假设性文档生成）
MODEL = os.getenv("MODEL")
# 大模型基础URL（用于Step Back/假设性文档生成）
BASE_URL = os.getenv("BASE_URL")
# 重排序模型名称
RERANK_MODEL = os.getenv("RERANK_MODEL")
# 重排序服务绑定地址
RERANK_BINDING_HOST = os.getenv("RERANK_BINDING_HOST")
# 重排序API密钥
RERANK_API_KEY = os.getenv("RERANK_API_KEY")
# 是否启用文档自动合并（默认启用）os.getenv("AUTO_MERGE_ENABLED", "true")
# 从系统环境变量读取 AUTO_MERGE_ENABLED
# 如果环境变量没设置 → 默认值是 "true"
AUTO_MERGE_ENABLED = os.getenv("AUTO_MERGE_ENABLED", "true").lower() != "false"
# 文档自动合并阈值：子Chunk数量达到该值则合并为父Chunk
AUTO_MERGE_THRESHOLD = int(os.getenv("AUTO_MERGE_THRESHOLD", "2"))
# 叶子节点检索层级（仅检索该层级的Chunk）
LEAF_RETRIEVE_LEVEL = int(os.getenv("LEAF_RETRIEVE_LEVEL", "3"))

# ======================== 全局实例初始化 ========================
# Milvus向量库管理实例（全局单例，复用连接）
_milvus_manager = MilvusManager()
# 父级Chunk存储实例（全局单例，用于获取父Chunk内容）
_parent_chunk_store = ParentChunkStore()
# 单例 = 整个程序里，只创建 1 个对象，永远重复用这 1 个！
# 绝不创建第二个！
#为什么要做成「单例」？
# 1. 省资源
# 数据库连接、Redis 连接、Milvus 连接
# 创建一次很贵，反复创建会卡死、变慢
# 2. 避免冲突
# 多个连接同时操作数据库会出错、数据错乱
# 3. 速度快
# 不用反复断开、重连

# Step Back大模型实例（懒加载，首次使用时初始化）
_stepback_model = None


# ======================== 工具函数：重排序服务相关 ========================
def _get_rerank_endpoint() -> str:
    """
    构造重排序服务的完整端点URL
    返回：
        str: 标准化的rerank接口地址，若未配置RERANK_BINDING_HOST则返回空字符串
    逻辑：
        1. 去除地址首尾空格和末尾的/
        2. 检查是否以/v1/rerank结尾，否则拼接该路径
    """
    if not RERANK_BINDING_HOST:
        return ""
    host = RERANK_BINDING_HOST.strip().rstrip("/")
    return host if host.endswith("/v1/rerank") else f"{host}/v1/rerank"


# ======================== 工具函数：文档合并相关 ========================
def _merge_to_parent_level(docs: List[dict], threshold: int = 2) -> Tuple[List[dict], int]:
    """
    将满足阈值的子Chunk合并为父Chunk（单层级合并，如L3→L2、L2→L1）
    参数：
        docs: 待合并的文档Chunk列表，每个Chunk需包含parent_chunk_id字段
        threshold: 合并阈值，子Chunk数量≥该值则合并为父Chunk
    返回：
        Tuple[List[dict], int]: 
            - 合并后的文档列表（去重后）
            - 被替换的子Chunk数量（即合并操作影响的Chunk数）
    核心逻辑：
        1. 按parent_chunk_id分组子Chunk
        2. 筛选出子Chunk数量≥阈值的父ID，从ParentChunkStore获取父Chunk内容
        3. 用父Chunk替换满足条件的子Chunk，父Chunk的score取子Chunk的最大值
        4. 对合并后的列表去重（避免重复的父Chunk）
    """
    # 步骤1：按父Chunk ID分组子Chunk
    groups: Dict[str, List[dict]] = defaultdict(list)
    for doc in docs:
        parent_id = (doc.get("parent_chunk_id") or "").strip()
        if parent_id:
            groups[parent_id].append(doc)

    # 步骤2：筛选出需要合并的父ID（子Chunk数量≥阈值）
    merge_parent_ids = [parent_id for parent_id, children in groups.items() if len(children) >= threshold]
    if not merge_parent_ids:
        return docs, 0  # 无满足条件的父ID，直接返回原文档

    # 步骤3：从存储中获取需要合并的父Chunk内容
    parent_docs = _parent_chunk_store.get_documents_by_ids(merge_parent_ids)
    parent_map = {item.get("chunk_id", ""): item for item in parent_docs if item.get("chunk_id")}

    # 步骤4：用父Chunk替换满足条件的子Chunk
    merged_docs: List[dict] = []
    merged_count = 0  # 记录被替换的子Chunk数量
    for doc in docs:
        parent_id = (doc.get("parent_chunk_id") or "").strip()
        # 无父ID或父Chunk不存在 → 保留原文档
        if not parent_id or parent_id not in parent_map:
            merged_docs.append(doc)
            continue
        # 存在父ID且满足合并条件 → 替换为父Chunk
        parent_doc = dict(parent_map[parent_id])  # 深拷贝避免修改原数据
        score = doc.get("score")
        if score is not None:
            # 父Chunk的score取自身score和子Chunk score的最大值
            parent_doc["score"] = max(float(parent_doc.get("score", score)), float(score))
        # 标记该父Chunk是合并而来，记录合并的子Chunk数量
        parent_doc["merged_from_children"] = True
        parent_doc["merged_child_count"] = len(groups[parent_id])
        merged_docs.append(parent_doc)
        merged_count += 1

    # 步骤5：去重（避免同一父Chunk被多次添加）
    deduped: List[dict] = []
    seen = set()
    for item in merged_docs:
        # 生成去重key：优先用chunk_id，无则用(filename+page_number+text)组合
        key = item.get("chunk_id") or (item.get("filename"), item.get("page_number"), item.get("text"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    return deduped, merged_count


def _auto_merge_documents(docs: List[dict], top_k: int) -> Tuple[List[dict], Dict[str, Any]]:
    """
    执行自动文档合并（两级合并：L3→L2 → L2→L1）
    参数：
        docs: 重排序后的文档列表（已按score排序）
        top_k: 最终需要返回的文档数量
    返回：
        Tuple[List[dict], Dict[str, Any]]:
            - 合并并截断后的文档列表（按score降序）
            - 合并元数据（记录合并是否生效、替换数量等）
    核心逻辑：
        1. 检查自动合并开关是否开启，未开启则直接返回前top_k条
        2. 第一级合并：L3→L2（叶子节点→上一级）
        3. 第二级合并：L2→L1（上一级→更顶层）
        4. 对合并后的文档按score降序排序，截断到top_k
        5. 生成合并元数据（用于监控/调试）
    """
    # 开关未开启或无文档 → 直接返回前top_k条
    if not AUTO_MERGE_ENABLED or not docs:
        return docs[:top_k], {
            "auto_merge_enabled": AUTO_MERGE_ENABLED,
            "auto_merge_applied": False,  # 是否实际执行了合并
            "auto_merge_threshold": AUTO_MERGE_THRESHOLD,
            "auto_merge_replaced_chunks": 0,  # 被替换的Chunk总数
            "auto_merge_steps": 0,  # 执行的合并步骤数（0/1/2）
        }

    # 两级合并：先L3→L2，再L2→L1
    merged_docs, merged_count_l3_l2 = _merge_to_parent_level(docs, threshold=AUTO_MERGE_THRESHOLD)
    merged_docs, merged_count_l2_l1 = _merge_to_parent_level(merged_docs, threshold=AUTO_MERGE_THRESHOLD)

    # 按score降序排序，截断到top_k
    merged_docs.sort(key=lambda item: item.get("score", 0.0), reverse=True)
    merged_docs = merged_docs[:top_k]

    # 计算总替换数和合并步骤数
    replaced_count = merged_count_l3_l2 + merged_count_l2_l1
    return merged_docs, {
        "auto_merge_enabled": AUTO_MERGE_ENABLED,
        "auto_merge_applied": replaced_count > 0,
        "auto_merge_threshold": AUTO_MERGE_THRESHOLD,
        "auto_merge_replaced_chunks": replaced_count,
        "auto_merge_steps": int(merged_count_l3_l2 > 0) + int(merged_count_l2_l1 > 0),
    }


# ======================== 工具函数：重排序相关 ========================
def _rerank_documents(query: str, docs: List[dict], top_k: int) -> Tuple[List[dict], Dict[str, Any]]:
    """
    调用重排序服务对检索到的文档进行精排
    参数：
        query: 用户查询语句
        docs: 检索到的原始文档列表（未重排序）
        top_k: 重排序后需要返回的文档数量
    返回：
        Tuple[List[dict], Dict[str, Any]]:
            - 重排序后的文档列表（前top_k条）
            - 重排序元数据（开关状态、错误信息、候选数等）
    核心逻辑：
        1. 初始化元数据，检查重排序服务是否可用（模型/密钥/地址是否配置）
        2. 构造重排序请求参数（模型、查询、文档列表、top_n）
        3. 调用重排序API，处理响应（提取相关性分数，更新文档）
        4. 异常处理：API调用失败时返回原始文档前top_k条，并记录错误
    """
    # 为原始文档添加RRF排名（用于降级场景）
    docs_with_rank = [{**doc, "rrf_rank": i} for i, doc in enumerate(docs, 1)]
    # 初始化重排序元数据
    meta: Dict[str, Any] = {
        "rerank_enabled": bool(RERANK_MODEL and RERANK_API_KEY and RERANK_BINDING_HOST),
        "rerank_applied": False,  # 是否实际执行了重排序
        "rerank_model": RERANK_MODEL,
        "rerank_endpoint": _get_rerank_endpoint(),
        "rerank_error": None,  # 重排序错误信息（如有）
        "candidate_count": len(docs_with_rank),  # 重排序候选文档数
    }

    # 无候选文档或重排序服务不可用 → 返回原始文档前top_k条
    if not docs_with_rank or not meta["rerank_enabled"]:
        return docs_with_rank[:top_k], meta

    # 构造重排序请求体
    payload = {
        "model": RERANK_MODEL,
        "query": query,
        "documents": [doc.get("text", "") for doc in docs_with_rank],  # 仅传文本内容给重排序服务
        "top_n": min(top_k, len(docs_with_rank)),  # 重排序返回的数量（不超过候选数）
        "return_documents": False,  # 不返回完整文档，仅返回索引和分数
    }

    # 请求头（包含API密钥）
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {RERANK_API_KEY}",
    }

    try:
        meta["rerank_applied"] = True  # 标记已执行重排序
        # 调用重排序API（超时15秒）
        response = requests.post(
            meta["rerank_endpoint"],
            headers=headers,
            json=payload,
            timeout=15,
        )

        # HTTP状态码≥400 → 记录错误，返回原始文档
        if response.status_code >= 400:
            meta["rerank_error"] = f"HTTP {response.status_code}: {response.text}"
            return docs_with_rank[:top_k], meta

        # 解析响应结果
        items = response.json().get("results", [])
        reranked = []
        for item in items:
            idx = item.get("index")
            # 索引有效 → 提取对应文档，添加重排序分数
            if isinstance(idx, int) and 0 <= idx < len(docs_with_rank):
                doc = dict(docs_with_rank[idx])
                score = item.get("relevance_score")
                if score is not None:
                    doc["rerank_score"] = score  # 添加重排序相关性分数
                reranked.append(doc)

        # 重排序结果非空 → 返回重排序后的文档
        if reranked:
            return reranked[:top_k], meta

        # 重排序结果为空 → 记录错误，返回原始文档
        meta["rerank_error"] = "empty_rerank_results"
        return docs_with_rank[:top_k], meta

    # 捕获所有可能的异常（网络错误、JSON解析错误、键缺失、类型错误等）
    except (requests.RequestException, json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
        meta["rerank_error"] = str(e)
        return docs_with_rank[:top_k], meta


# ======================== 工具函数：Step Back相关 ========================
def _get_stepback_model():
    """
    懒加载Step Back大模型实例（全局单例）
    返回：
        初始化后的聊天模型实例，若缺少ARK_API_KEY/MODEL则返回None
    逻辑：
        1. 检查必要配置（API密钥、模型名称）
        2. 全局实例未初始化 → 调用init_chat_model初始化
        3. 返回全局实例
    """
    global _stepback_model
    if not ARK_API_KEY or not MODEL:
        return None
    if _stepback_model is None:
        _stepback_model = init_chat_model(
            model=MODEL,
            model_provider="openai",  # 模型提供商为OpenAI兼容接口
            api_key=ARK_API_KEY,
            base_url=BASE_URL,
            temperature=0.2,  # 低温度保证输出稳定
        )
    return _stepback_model


def _generate_step_back_question(query: str) -> str:
    """
    生成Step Back问题：将具体问题抽象为更高层次的通用问题
    参数：
        query: 用户原始查询语句
    返回：
        str: 抽象后的退步问题，生成失败则返回空字符串
    提示词逻辑：
        要求模型仅输出一句话的退步问题，不包含解释，聚焦通用原理/核心概念
    """
    model = _get_stepback_model()
    if not model:
        return ""
    prompt = (
        "请将用户的具体问题抽象成更高层次、更概括的‘退步问题’，"
        "用于探寻背后的通用原理或核心概念。只输出退步问题一句话，不要解释。\n"
        f"用户问题：{query}"
    )
    try:
        # 调用模型并提取内容，去除首尾空格
        return (model.invoke(prompt).content or "").strip()
    except Exception:
        return ""


def _answer_step_back_question(step_back_question: str) -> str:
    """
    回答Step Back问题：基于通用问题生成背景知识/原理回答
    参数：
        step_back_question: 抽象后的退步问题
    返回：
        str: 简洁的回答（≤120字），生成失败则返回空字符串
    提示词逻辑：
        要求模型仅输出答案（≤120字），不包含推理过程，聚焦通用原理/背景知识
    """
    model = _get_stepback_model()
    if not model or not step_back_question:
        return ""
    prompt = (
        "请简要回答以下退步问题，提供通用原理/背景知识，"
        "控制在120字以内。只输出答案，不要列出推理过程。\n"
        f"退步问题：{step_back_question}"
    )
    try:
        return (model.invoke(prompt).content or "").strip()
    except Exception:
        return ""


# ======================== 核心函数：假设性文档生成 ========================
def generate_hypothetical_document(query: str) -> str:
    """
    生成假设性文档：基于用户问题生成模拟的真实资料片段，辅助检索
    参数：
        query: 用户原始查询语句
    返回：
        str: 假设性文档内容，生成失败则返回空字符串
    提示词逻辑：
        要求模型生成与问题语义相关的、类似真实资料的文本片段，仅输出正文，无标题/解释
    """
    model = _get_stepback_model()
    if not model:
        return ""
    prompt = (
        "请基于用户问题生成一段‘假设性文档’，内容应像真实资料片段，"
        "用于帮助检索相关信息。文档可以包含合理推测，但需与问题语义相关。"
        "只输出文档正文，不要标题或解释。\n"
        f"用户问题：{query}"
    )
    try:
        return (model.invoke(prompt).content or "").strip()
    except Exception:
        return ""


# ======================== 核心函数：Step Back扩展 ========================
def step_back_expand(query: str) -> dict:
    """
    执行Step Back扩展：生成退步问题+回答，扩展原始查询
    参数：
        query: 用户原始查询语句
    返回：
        dict: 包含以下字段的扩展结果
            - step_back_question: 抽象后的退步问题
            - step_back_answer: 退步问题的回答
            - expanded_query: 扩展后的查询（原始问题+退步问题+回答）
    逻辑：
        1. 生成退步问题和回答
        2. 若生成成功 → 拼接扩展查询；否则 → 返回原始查询
    """
    step_back_question = _generate_step_back_question(query)
    step_back_answer = _answer_step_back_question(step_back_question)
    # 有退步问题/回答 → 扩展查询
    if step_back_question or step_back_answer:
        expanded_query = (
            f"{query}\n\n"
            f"退步问题：{step_back_question}\n"
            f"退步问题答案：{step_back_answer}"
        )
    else:
        expanded_query = query
    return {
        "step_back_question": step_back_question,
        "step_back_answer": step_back_answer,
        "expanded_query": expanded_query,
    }


# ======================== 核心函数：文档检索主流程 ========================
def retrieve_documents(query: str, top_k: int = 5) -> Dict[str, Any]:
    """
    文档检索主函数：混合检索（稠密+稀疏）→ 重排序 → 自动合并
    参数：
        query: 用户查询语句
        top_k: 最终返回的文档数量（默认5）
    返回：
        dict: 检索结果，包含以下字段
            - docs: 最终筛选后的文档列表
            - meta: 检索元数据（重排序、合并、检索模式等信息）
    核心流程：
        1. 计算候选数（candidate_k = max(top_k*3, top_k)，为重排序预留更多候选）
        2. 尝试混合检索（稠密+稀疏向量）→ 重排序 → 自动合并
        3. 混合检索失败 → 降级为稠密检索 → 重排序 → 自动合并
        4. 所有检索失败 → 返回空文档列表+失败元数据
    """
    # 候选文档数：取top_k*3和top_k的最大值，为重排序提供更多候选
    candidate_k = max(top_k * 3, top_k)
    # 检索过滤条件：仅检索指定层级的叶子节点Chunk
    filter_expr = f"chunk_level == {LEAF_RETRIEVE_LEVEL}"

    try:
        # ======================== 第一步：混合检索（稠密+稀疏） ========================
        # 生成查询的稠密向量
        dense_embeddings = _embedding_service.get_embeddings([query])
        dense_embedding = dense_embeddings[0]
        # 生成查询的稀疏向量
        sparse_embedding = _embedding_service.get_sparse_embedding(query)

        # 调用Milvus混合检索（稠密+稀疏）
        retrieved = _milvus_manager.hybrid_retrieve(
            dense_embedding=dense_embedding,
            sparse_embedding=sparse_embedding,
            top_k=candidate_k,
            filter_expr=filter_expr,
        )

        # ======================== 第二步：重排序 ========================
        reranked, rerank_meta = _rerank_documents(query=query, docs=retrieved, top_k=top_k)

        # ======================== 第三步：自动合并 ========================
        merged_docs, merge_meta = _auto_merge_documents(docs=reranked, top_k=top_k)

        # ======================== 第四步：组装元数据 ========================
        rerank_meta["retrieval_mode"] = "hybrid"  # 标记检索模式为混合检索
        rerank_meta["candidate_k"] = candidate_k
        rerank_meta["leaf_retrieve_level"] = LEAF_RETRIEVE_LEVEL
        rerank_meta.update(merge_meta)  # 合并自动合并的元数据

        return {"docs": merged_docs, "meta": rerank_meta}

    except Exception:
        # 混合检索失败 → 降级为稠密检索
        try:
            # ======================== 降级：稠密检索 ========================
            # 生成查询的稠密向量
            dense_embeddings = _embedding_service.get_embeddings([query])
            dense_embedding = dense_embeddings[0]

            # 调用Milvus稠密检索
            retrieved = _milvus_manager.dense_retrieve(
                dense_embedding=dense_embedding,
                top_k=candidate_k,
                filter_expr=filter_expr,
            )

            # 重排序 + 自动合并
            reranked, rerank_meta = _rerank_documents(query=query, docs=retrieved, top_k=top_k)
            merged_docs, merge_meta = _auto_merge_documents(docs=reranked, top_k=top_k)

            # 组装元数据（标记为稠密检索降级）
            rerank_meta["retrieval_mode"] = "dense_fallback"
            rerank_meta["candidate_k"] = candidate_k
            rerank_meta["leaf_retrieve_level"] = LEAF_RETRIEVE_LEVEL
            rerank_meta.update(merge_meta)

            return {"docs": merged_docs, "meta": rerank_meta}

        except Exception:
            # 所有检索方式均失败 → 返回空文档+失败元数据
            return {
                "docs": [],
                "meta": {
                    "rerank_enabled": bool(RERANK_MODEL and RERANK_API_KEY and RERANK_BINDING_HOST),
                    "rerank_applied": False,
                    "rerank_model": RERANK_MODEL,
                    "rerank_endpoint": _get_rerank_endpoint(),
                    "rerank_error": "retrieve_failed",  # 标记检索失败
                    "retrieval_mode": "failed",  # 检索模式标记为失败
                    "candidate_k": candidate_k,
                    "leaf_retrieve_level": LEAF_RETRIEVE_LEVEL,
                    "auto_merge_enabled": AUTO_MERGE_ENABLED,
                    "auto_merge_applied": False,
                    "auto_merge_threshold": AUTO_MERGE_THRESHOLD,
                    "auto_merge_replaced_chunks": 0,
                    "auto_merge_steps": 0,
                    "candidate_count": 0,
                },
            }