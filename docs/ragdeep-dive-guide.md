# SuperMew RAG 项目深度学习指南

## 面试的时候改怎么描述这个项目？一句话怎么概括？

![image-20260603094848730](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260603094848730.png)

# 这个项目的流程是怎么样的，比如我作为一个用户，是先上传数据，然后再提问是吗？这中间是怎么运转的的？链路。

![image-20260603105440442](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260603105440442.png)

## JWT 会话管理在这个项目里的作用

**这个项目里，JWT 不是“保存会话数据”的数据库会话，而是“用户身份认证令牌”，用来确认请求是谁发起的，并决定权限。**

![image-20260603095137258](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260603095137258.png)

## 项目整体链路概览

这个项目本质上是一个基于 FastAPI + LangChain + Milvus 的 RAG 问答系统，链路可以拆成四大部分：

配置与启动
文档入库与检索数据构建
用户请求与 RAG 生成
数据持久化与缓存
1. 配置与启动
入口文件
app.py
创建 FastAPI 应用
加载数据库 init_db()
配置 CORS 允许跨域
挂载前端静态目录 frontend
启动方式支持 uvicorn backend.app:app
配置文件
.env
模型服务：ARK_API_KEY、MODEL、BASE_URL
向量模型：EMBEDDING_MODEL、EMBEDDING_DEVICE、DENSE_EMBEDDING_DIM
Milvus：MILVUS_HOST、MILVUS_PORT、MILVUS_COLLECTION
数据库缓存：DATABASE_URL、REDIS_URL
权限与安全：JWT_SECRET_KEY、ADMIN_INVITE_CODE
依赖与部署
README.md
说明 Python 环境、Docker Compose 启动依赖、前端访问地址
说明 Milvus、Postgres、Redis、MinIO 等依赖
2. 文档入库与知识库构建链路
文档加载与分块
document_loader.py
支持 PDF、Word、Excel
采用 RecursiveCharacterTextSplitter
设计了“三级切分”：
L1：大块
L2：中块
L3：小叶子块
每个 chunk 都带有：
chunk_id
parent_chunk_id
root_chunk_id
chunk_level
chunk_idx
亮点：
三级结构保留层级关系，方便后续 Auto-merging
中文分割优先语义标点，避免乱切
向量化服务
embedding.py
EmbeddingService
本地稠密向量：HuggingFaceEmbeddings（默认 BAAI/bge-m3）
稀疏向量：自研 BM25
BM25 特点：
持久化到 data/bm25_state.json
支持增量 increment_add_documents 和删除 increment_remove_documents
词表 + doc_freq + total_docs 持久保存
本地中英文分词：中文单字、英文单词
亮点：
同时支持稠密语义和稀疏关键词
BM25 状态持久化，文档增删可同步维护统计
Milvus 存储与检索
milvus_client.py
管理 Milvus 连接与集合
创建集合时同时建：
dense_embedding（FLOAT_VECTOR）
sparse_embedding（SPARSE_FLOAT_VECTOR）
text、filename、page_number、chunk_level 等字段
检索能力：
hybrid_retrieve：稠密 + 稀疏混合检索
dense_retrieve：纯稠密降级检索
query_all：分页拉取全部数据
亮点：
使用 RRF 融合混合检索结果
支持降级逻辑：混合失败时自动转纯密集检索
支持 filter_expr 精细过滤叶子级别 chunk
入库写入
milvus_writer.py
批量写入到 Milvus
对每个 chunk 同时生成：
密集向量
稀疏向量
写入前先调用 increment_add_documents 更新 BM25 统计
亮点：
密集+稀疏一起写，一次入库完成混合检索准备
批次写入设计，避免一次性写入过大导致卡顿
父级块存储
parent_chunk_store.py
父级分块写入 PostgreSQL
同时缓存到 Redis
支持：
upsert_documents
get_documents_by_ids
delete_by_filename
亮点：
只把父块存数据库，叶子块只存向量库，减少冗余
用 Redis 缓存热点父块，加速 Auto-merging
3. 召回 + RAG 生成链路
API 接口
api.py
认证：/auth/register、/auth/login、/auth/me
会话管理：/sessions、/sessions/{id}、/sessions/{id} 删除
聊天接口：
POST /chat：普通响应
POST /chat/stream：SSE 流式响应
文档管理接口（管理员权限）
文档列表、上传、删除
对话代理与流式回答
agent.py
核心负责：
创建 LangChain agent
加载会话历史
对话总结
工具调用限制
包含流式 chat_with_agent_stream
设计：
使用 agent.astream(stream_mode="messages")
通过 asyncio.Queue 将内容片段与 RAG 步骤统一推送
生成结果时逐 token 发送
亮点：
SSE 实现实时打字机效果
及时返回 rag_step 事件，让前端看到思考过程
支持用户断开连接后取消后台任务
对话存储
ConversationStorage
存储到 PostgreSQL
表：User、ChatSession、ChatMessage
同时缓存到 Redis
支持：
查会话消息
查会话列表
删除会话
亮点：
会话缓存+数据库双写，查询性能和持久化兼顾
保存每条 AI 消息的 rag_trace
Agent 工具与系统提示
工具：
get_current_weather
search_knowledge_base
search_knowledge_base 是核心 RAG 入口
Agent 系统提示明确：
只有一个知识库工具调用
用知识库后必须生成最终答案
如果上下文不足要诚实“不知道”
亮点：
强制工具调用策略避免循环调用
结合工具和生成模型的业务约束
4. RAG 检索与扩展逻辑
检索主流程
rag_utils.py
retrieve_documents(query, top_k=5)
核心流程：
生成 query 的稠密向量
生成 query 的稀疏向量
Milvus hybrid 检索
可选 Jina rerank
自动合并 Auto-merge
失败时降级到纯密集检索
亮点：
hybrid_retrieve + RRFRanker
自动降级策略设计
重排序与合并共同提高上下文质量
自动合并设计
_auto_merge_documents
L3→L2、L2→L1 两级合并
当同一个父块下子块数量超过阈值（默认 2）时，用父块替换子块
父块分数取子块最高分
去重后返回 top_k
亮点：
解决“碎片化检索结果太多，难以拼接”问题
保留更完整上下文，同时避免过长
重排序与降级
_rerank_documents
可接入 RERANK_MODEL / RERANK_BINDING_HOST
先按原检索结果 candidate 生成 relevance_score
失败时降级不影响主流程
亮点：
可插入精排服务，支持业务级排序优化
错误安全，不会因为 rerank 异常导致整个检索崩溃
扩展查询策略
step_back_expand
退步问题生成
扩展原始查询用于第二轮检索
generate_hypothetical_document
生成“假设文档”辅助检索
亮点：
一种“查询增强”机制，提升复杂问题的召回能力
能把用户问题转换为更通用、更容易检索的查询
5. 前端与交互链路
前端静态页面
index.html
script.js
style.css
前端流程
用户输入对话
发送 POST /chat/stream
浏览器通过 EventSource / ReadableStream 解析 SSE
实时展示：
content 片段
rag_step 过程
trace 最终 RAG 跟踪
还支持历史会话列表和文档管理
亮点
实时可视化 RAG 过程，不再只是“黑盒大模型”
兼容纯前端单页面，无需复杂前端框架
6. 逐步链路总结
端到端链路
用户发起请求 POST /chat/stream
api.py 调用 agent.py 的 chat_with_agent_stream
agent.py
读取历史消息
需要时摘要旧消息
调用 Agent
Agent 判断是否调用工具
若是知识库问题，调用 search_knowledge_base
rag_utils.py
向量化 query
Milvus hybrid 检索
rerank
auto-merge
检索结果返回给 Agent
Agent 生成最终答案并逐步流式输出
agent.py 保存会话到数据库/Redis
前端实时展示结果与过程
7. 每一步的亮点总结
配置与启动：.env + docker-compose 让模型、数据库、Milvus、缓存可独立配置
文档切分：三级分块+父子关系，为后续 Auto-merging 做基础
向量服务：稠密+稀疏双路嵌入，BM25 状态持久化支持增删
Milvus 存储：混合检索 + RRF + 降级策略，兼顾精度与稳定性
父块存储：PostgreSQL + Redis 缓存，保证父块结构查询快速可靠
RAG 检索：完整混合检索链路、可选 rerank、自动合并
Agent 设计：工具调用约束明确、流式 SSE、历史总结
会话存储：消息持久化 + 缓存加速 + RAG trace
前端展示：可视化 RAG 过程和断点流输出
如果你愿意，我可以继续帮你把这个梳理转成一份“项目文档架构图”或“每个文件职责清单”。

> 目标：像自己从 0 到 1 搭建的一样掌握这个项目。不是看代码长什么样，而是理解**为什么这样设计**。

---

## 学习路线图：从底层数据到上层智能

```
┌─────────────────────────────────────────────────────┐
│  第 5 层：应用层    FastAPI + Auth + 前端             │
│  第 4 层：智能层    Agent + 查询扩展 + 相关性评分       │
│  第 3 层：检索层    混合检索 + Rerank + Auto-merge     │
│  第 2 层：存储层    Milvus + PostgreSQL + Redis       │
│  第 1 层：数据层    文档解析 + 三层分块 + 双路向量化     │
└─────────────────────────────────────────────────────┘
```

**建议按 1→2→3→4→5 的顺序学**，因为每一层都是下一层的基础。就像盖房子，先理解"数据怎么存"，再理解"怎么搜"，最后理解"怎么用 AI 包装"。

---

## 第 1 层：数据层（文档 → 结构化分块 → 向量）

# 向量化emdeddng.py向量化的逻辑（分别讲一下：中英文分词逻辑
◦ 词表 vocab
◦ 文档频率 doc_freq
◦ 文档总数 / 总词数 / 平均文档长度
◦ BM25 的 IDF/TF 公式）

![image-20260603110837474](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260603110837474.png)

### 1.1 文档解析 — [document_loader.py](../backend/document_loader.py)

![image-20260601093519333](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601093519333.png)

**核心问题**：用户上传 PDF/Word/Excel，怎么变成程序能处理的文本？

**实现方式**：`DocumentLoader.load_document()`（第 120 行）

```python
# 根据文件扩展名选择不同的加载器
if file_lower.endswith(".pdf"):
    loader = PyPDFLoader(file_path)        # 用 pypdf 提取 PDF 文本
elif file_lower.endswith(".docx"):
    loader = Docx2txtLoader(file_path)     # 用 python-docx 提取 Word 文本
elif file_lower.endswith(".xlsx"):
    loader = UnstructuredExcelLoader(file_path)  # 用 unstructured 提取 Excel
```

**知识点**：LangChain 的 Document Loader 抽象了不同文件格式的差异，统一输出 `Document(page_content=..., metadata={...})` 结构。

---

### 1.2 三层分级分块 — [document_loader.py](../backend/document_loader.py) 第 43-118 行

**这是整个项目最核心的设计决策之一**。不是简单把文档切成等大小块，而是建立了**树形层级结构**。

**为什么需要三层？**

```
Level 1（父块 ~1200字）:  "深度学习是机器学习的一个分支..."
    ├── Level 2（子块 ~600字）: "深度神经网络由多层神经元组成..."
    │       ├── Level 3（叶子块 ~300字）: "卷积神经网络(CNN)使用卷积层..."
    │       └── Level 3（叶子块 ~300字）: "循环神经网络(RNN)擅长序列..."
    └── Level 2（子块 ~600字）: "训练深度网络需要大量数据..."
            ├── Level 3（叶子块 ~300字）: "GPU加速训练..."
            └── Level 3（叶子块 ~300字）: "数据增强技术..."
```

三层各自的作用：

| 层级 | 大小 | 作用 | 检索时如何使用 |
|------|------|------|---------------|
| Level 3（叶子） | ~300字 | 精确匹配，语义集中 | **存入 Milvus**，用于向量检索 |
| Level 2（子块） | ~600字 | 中等粒度上下文 | **存入 PostgreSQL**，Auto-merge 用它替换叶子 |
| Level 1（根块） | ~1200字 | 大范围上下文 | **存入 PostgreSQL**，两段合并时最终用这个 |

**代码实现逻辑**（`_split_page_to_three_levels`）：

```python
# 第 56-116 行：嵌套分块算法
level_1_docs = splitter_level_1.create_documents([text])   # 先切成 Level 1
for level_1_doc in level_1_docs:
    保存 level_1_chunk（parent_chunk_id=""，自己是根）
    
    level_2_docs = splitter_level_2.create_documents([level_1_text])  # Level 1 再切
    for level_2_doc in level_2_docs:
        保存 level_2_chunk（parent_chunk_id=level_1_id）
        
        level_3_docs = splitter_level_3.create_documents([level_2_text])  # Level 2 再切
        for level_3_doc in level_3_docs:
            保存 level_3_chunk（parent_chunk_id=level_2_id, root_chunk_id=level_1_id）
```

通过 `parent_chunk_id` 和 `root_chunk_id` 建立了父子引用链。

---

### 1.3 双路向量化（Dense + Sparse）— [embedding.py](../backend/embedding.py)

![image-20260601085306457](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601085306457.png)

![image-20260601085539245](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601085539245.png)

![image-20260601085600543](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601085600543.png)![image-20260601090210963](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601090210963.png)

![image-20260601090231374](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601090231374.png)

![image-20260601090636884](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601090636884.png)

![image-20260601093300518](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601093300518.png)





**核心问题**：一段文本既要语义搜索（"深度学习"能匹配"神经网络"），也要关键词搜索（精确匹配"CNN"）。

**为什么叫"混合检索"？**

| 向量类型 | 原理 | 擅长 | 局限性 |
|----------|------|------|--------|
| **Dense（稠密）** | 用 bge 模型把文本编码成 512 维向量 | 语义相似（"猫"≈"小动物"） | 专有名词、精确匹配弱 |
| **Sparse（稀疏/BM25）** | 统计 TF-IDF，输出 `{词ID: 分数}` | 关键词精确匹配 | 同义词、语义理解弱 |

**BM25 持久化设计**（第 28-86 行）：

BM25 的算法依赖全局统计量：
- `_doc_freq`：每个词在多少篇文档里出现过（文档频率）
- `_total_docs`：总文档数
- `_avg_doc_len`：平均文档长度

这些统计量被序列化到 `data/bm25_state.json`，每次增删文档时**增量更新**而非重新计算：

```python
# increment_add_documents（第 91-109 行）
def increment_add_documents(self, texts: list[str]):
    for text in texts:
        tokens = self.tokenize(text)
        self._sum_token_len += len(tokens)
        self._total_docs += 1                    # 总文档数 +1
        for token in set(tokens):
            if token not in self._vocab:
                self._vocab[token] = self._vocab_counter
                self._vocab_counter += 1         # 新词加入词表
            self._doc_freq[token] += 1           # 该词的文档频率 +1
    self._persist_unlocked()                     # 存盘
```

**分词策略**（第 141-159 行）：中文逐字切分（"你好" → "你" "好"），英文按词切分（"hello" → "hello"），简单但有效。

---

## 第 2 层：存储层（三个数据库各司其职）

### 2.1 Milvus（向量库）— [milvus_client.py](../backend/milvus_client.py)

![image-20260601101931071](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601101931071.png)

![image-20260601094054196](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601094054196.png)

![image-20260601094122369](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601094122369.png)

![image-20260601094157951](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601094157951.png)

![image-20260601105145013](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601105145013.png)

**启动 → 连接 Milvus → 建表（含双向量索引）→ 插入数据 →**
**可精确查询 / 可查全部 / 可按 ID 查 /**
**【核心】混合检索（语义 + 关键词）最强搜索 /**
**降级方案（纯语义）兜底 /**
**最后可删除表**

**主要用于 Auto-merging 检索：根据子块ID，拉取对应的父块/根块信息**

**职责**：存**所有 Level 3（叶子块）**的向量 + 元数据，执行向量相似度搜索。

**Schema 设计**（第 28-85 行 `init_collection`）：

```python
schema.add_field("dense_embedding",  FLOAT_VECTOR, dim=512)   # 稠密向量 512 维
schema.add_field("sparse_embedding", SPARSE_FLOAT_VECTOR)     # 稀疏向量（变长）
schema.add_field("text",             VARCHAR, max_length=2000) # 原文
schema.add_field("chunk_id",         VARCHAR, max_length=512)  # 分块 ID
schema.add_field("parent_chunk_id",  VARCHAR, max_length=512)  # 父块 ID（Auto-merge 用）
schema.add_field("chunk_level",      INT64)                    # 层级 1/2/3
```

**为什么 Level 1 和 Level 2 不存 Milvus？** 因为它们不需要被向量检索——叶子块检索到后，通过 `parent_chunk_id` 去 PostgreSQL 拉父块替换，这叫 **Auto-merging**。

---

### 2.2 PostgreSQL（关系库）— [database.py](../backend/database.py) + [models.py](../backend/models.py)

![image-20260601110441424](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601110441424.png)



**职责**：存四类数据，每类一张表：

| 表 | 对应的 ORM 类 | 用途 |
|----|-------------|------|
| `users` | `User` | 用户认证 |
| `chat_sessions` | `ChatSession` | 会话管理 |
| `chat_messages` | `ChatMessage` | 对话历史 |
| `parent_chunks` | `ParentChunk` | **Level 1+2 父块**（Auto-merge 的关键） |

**为什么 parent_chunks 放 PostgreSQL 而不是 Milvus？** 因为它们不需要向量搜索，只需要"根据 chunk_id 精确查找"。PostgreSQL 做这事更擅长，且避免了 Milvus 的存储膨胀。

---

### 2.3 Redis（缓存库）— [cache.py](../backend/cache.py)

![image-20260601130938058](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601130938058.png)

![image-20260601130952365](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601130952365.png)

**职责**：缓存两类热数据：

```python
# agent.py 第 24-26 行：缓存 key 设计
f"chat_messages:{user_id}:{session_id}"   # 对话消息缓存
f"chat_sessions:{user_id}"                # 会话列表缓存

# parent_chunk_store.py 第 30 行
f"parent_chunk:{chunk_id}"               # 父块缓存
```

**为什么需要 Redis？** 每次 Agent 对话都要加载历史消息（`ConversationStorage.load()`），每次都查 PostgreSQL 太慢。Redis 做一级缓存，命中率高且延迟低（<1ms vs ~10ms）。

**缓存策略**：cache-aside（旁路缓存）模式：

- 读：先查 Redis → 未命中再查 PostgreSQL → 回写 Redis
- 写：更新 PostgreSQL → 更新 Redis → 删除相关缓存 key

---

## 第 3 层：检索层（怎么从海量文档中精准找到答案）

这是 RAG 系统的心脏。整个检索流程在 [rag_utils.py](../backend/rag_utils.py) 的 `retrieve_documents()` 函数（第 245-301 行）里：

```
用户查询
    │
    ▼
┌─────────────────────────────┐
│ Step 1: 混合检索 (Hybrid)    │  ← 稠密向量 + 稀疏向量，各搜 top_k*2
│ 对候选结果做 RRF 融合排序     │
├─────────────────────────────┤
│ Step 2: Rerank（可选）       │  ← 调用外部 Rerank API 重新排序
├─────────────────────────────┤
│ Step 3: Auto-merge          │  ← 如果同一父块的叶子够多，用父块替换
├─────────────────────────────┤
│ Step 4: 返回 top_k 结果      │
└─────────────────────────────┘
```

### 3.1 混合检索（Hybrid Search）— [milvus_client.py](../backend/milvus_client.py) 第 151-227 行

```python
def hybrid_retrieve(self, dense_embedding, sparse_embedding, top_k=5):
    # 稠密搜索（语义相似）
    dense_search = AnnSearchRequest(
        data=[dense_embedding],
        anns_field="dense_embedding",   # 在稠密向量字段搜
        limit=top_k * 2,                # 多取一倍，给 RRF 融合用
    )
    
    # 稀疏搜索（关键词匹配）
    sparse_search = AnnSearchRequest(
        data=[sparse_embedding],
        anns_field="sparse_embedding",  # 在稀疏向量字段搜
        limit=top_k * 2,
    )
    
    # RRF（Reciprocal Rank Fusion）融合两路结果
    ranker = RRFRanker(k=60)  # k=60 是经典值
    results = client.hybrid_search(
        reqs=[dense_search, sparse_search],
        ranker=ranker,
        limit=top_k,
    )
```

**RRF 算法原理**：不依赖原始分数绝对值，而是用排名倒数做融合：

```
RRF_score(doc) = Σ 1/(k + rank_i(doc))

k=60 意味着：排第 1 名得 1/61 分，排第 10 名得 1/70 分
```

两路结果各自排名，然后按 RRF 分数合并排序。这样即使稠密和稀疏的原始分数量级不同，也能公平融合。

---

### 3.2 Rerank（重排序）— [rag_utils.py](../backend/rag_utils.py) 第 108-163 行

![image-20260601141026061](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601141026061.png)



## 为什么要做step back

![image-20260601141756624](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601141756624.png)

**为什么需要 Rerank？** 向量检索用余弦相似度做初筛很快但不精准。Rerank 用更强大的模型（如 Jina Reranker）做**精细化的相关性判断**。

```python
def _rerank_documents(query, docs, top_k):
    # 把 query + 每个候选文档发给 Rerank API
    payload = {
        "model": RERANK_MODEL,
        "query": query,
        "documents": [doc["text"] for doc in docs],
        "top_n": top_k,
    }
    response = requests.post(rerank_endpoint, json=payload)
    # 按 relevance_score 排序，只保留 top_n
```

**这里用的是 Cross-encoder 思路**：把 (query, document) 对一起输入模型打分，比向量检索的 Bi-encoder（query 和 document 分开编码）精度高很多，但速度慢 10-100 倍，所以只在候选集上重排。

---

### 3.3 Auto-merging（自动合并）— [rag_utils.py](../backend/rag_utils.py) 第 39-105 行

"""
**RAG（Retrieval-Augmented Generation）工具类模块**
**核心功能：**

1. **文档检索（混合检索/稠密检索降级）**
2. **文档重排序（Rerank）**
3. **文档自动合并（按父级Chunk层级合并）**
4. **问题退步扩展（Step Back）：将具体问题抽象为通用问题并回答，扩展检索上下文**
5. **假设性文档生成：基于用户问题生成虚拟文档辅助检索**

**依赖组件：**
- **MilvusManager：Milvus向量数据库操作客户端**
- **embedding_service：向量嵌入服务（稠密/稀疏向量生成）**
- **ParentChunkStore：父级Chunk存储管理**
- **init_chat_model：LangChain聊天模型初始化工具**
- **环境变量：通过dotenv加载，配置各类开关、阈值、API密钥等**
**"""**

**这是三层分块的"回收"机制**：

```python
def _merge_to_parent_level(docs, threshold=2):
    # 按 parent_chunk_id 分组
    groups = defaultdict(list)
    for doc in docs:
        groups[doc["parent_chunk_id"]].append(doc)
    
    # 如果某个父块下有 ≥ threshold 个叶子块被召回
    for parent_id, children in groups.items():
        if len(children) >= threshold:  # 默认 2 个
            parent_doc = 从 PostgreSQL 拉父块
            merged_docs.append(parent_doc)  # 用父块替换这些叶子块
```

**直觉理解**：**如果检索回了同一个父块下的 2 个以上叶子块，说明用户关心的可能是父块这个更大的主题。用父块替换叶子块，给 LLM 更完整的上下文。**

```
检索回的叶子块:
  - "CNN 使用卷积层提取特征"    ──┐ parent=L2-1
  - "最大池化减少维度"          ──┘ 
  - "Transformer 用自注意力"    ─── parent=L2-2（只有 1 个，不触发合并）

合并后发给 LLM:
  - "深度神经网络由多层神经元组成，包括卷积层、池化层..."  ← 整个 L2-1 父块
  - "Transformer 用自注意力"                          ← 保留叶子
```

---

## parent_chunk_store这个文件在干嘛

![image-20260601145522432](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601145522432.png)



## 第 4 层：智能层（AI 如何理解并改写你的问题）重点

### 4.1 RAG 流程编排 — [rag_pipeline.py](../backend/rag_pipeline.py)

**使用了 LangGraph 的 StateGraph**（不是 LangChain 老式的 Chain），这是一个状态机：

```
         ┌──────────────────┐
         │  retrieve_initial │  ← 初始检索（混合检索）
         └────────┬─────────┘
                  │
         ┌────────▼─────────┐
         │  grade_documents  │  ← 相关性评分
         └────┬─────────┬───┘
              │         │
      相关 ✅  │         │ 不相关 ❌
              │         │
         ┌────▼──┐  ┌───▼──────────────┐
         │  END  │  │ rewrite_question  │  ← 查询重写
         └───────┘  └────────┬─────────┘
                             │
                    ┌────────▼──────────┐
                    │ retrieve_expanded │  ← 用扩展查询重新检索
                    └────────┬──────────┘
                             │
                             ▼
                            END
```

### 4.2 查询扩展的三种策略 — [rag_utils.py](../backend/rag_utils.py)

当第一次检索结果不够相关时，不是直接放弃，而是**改写问题再搜一次**：

**策略 1：Step-back（退步问题）**— `_generate_step_back_question()` 第 181-193 行

```
用户问："CNN 为什么在 ImageNet 2012 上表现这么好？"
      ↓
退步问题："深度卷积神经网络在图像识别中的核心优势是什么？"
      ↓
用退步答案扩充原始查询，重新检索
```

**策略 2：HyDE（假设性文档）**— `generate_hypothetical_document()` 第 211-224 行

```
用户问："什么是 zero-shot learning？"
      ↓
AI 生成一篇假设性文档："Zero-shot learning 是一种机器学习范式，
它允许模型对训练中未见过的类别进行分类..."
      ↓
用这篇假文档去检索（假文档和真知识库文档在语义上更接近）
```

**策略 3：Complex（组合）**— Step-back + HyDE 一起上

**策略选择**（[rag_pipeline.py](../backend/rag_pipeline.py) 第 197-211 行）：用一个轻量 LLM 判断该用哪种策略。

---

### 4.3 Agent 工具系统 — [agent.py](../backend/agent.py) + [tools.py](../backend/tools.py)

```python
# agent.py 第 210-236 行
agent = create_agent(
    model=model,
    tools=[get_current_weather, search_knowledge_base],  # 两个工具
    system_prompt="You are a cute cat bot..."
)
```

**Agent 的调用流程**：

```
用户: "知识库里关于 CNN 的资料有哪些？"
    │
    ▼
LLM 判断：需要调用 search_knowledge_base 工具
    │
    ▼
search_knowledge_base("CNN")  → 触发 RAG 流程 → 返回检索结果
    │
    ▼
LLM 基于检索结果生成回答 → 返回给用户
```

**流式输出架构**（[agent.py](../backend/agent.py) 第 310-415 行 `chat_with_agent_stream`）：

这是项目的精妙设计之一：使用 `asyncio.Queue` 做统一消息队列，Agent worker 在后台线程运行，RAG 检索步骤通过 `call_soon_threadsafe` 实时推入队列，主循环不断从队列取事件 yield SSE。这样用户能**实时看到检索进度**（"正在检索...", "找到 5 个片段"），而不是干等。

## SSE 格式和yield

SSE = 服务器给前端 “实时推消息” 的专用格式
就像直播弹幕、实时打字、实时通知必须用这种格式！

yield = 不要一次返回全部，而是 “有一点就吐一点”
→ 这就是打字机效果的来源！

---

# rag_pipeline.py

![image-20260601154746323](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601154746323.png)

![image-20260601191106048](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601191106048.png)

![image-20260601191647413](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601191647413.png)

## rag_pipeline.py和其它文件的联系

![image-20260601160339171](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601160339171.png)

## Literal 核心知识点总结

![image-20260601151948284](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601151948284.png)

## TypedDict这个点

![image-20260601152204049](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601152204049.png)

## 对上面总结一下

![image-20260601165810566](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601165810566.png)

## 第 5 层：应用层（FastAPI + 认证 + 前端）

### 5.1 API 路由 — [api.py](../backend/api.py)

```
POST /auth/register          ← 注册
POST /auth/login             ← 登录
GET  /auth/me                ← 获取当前用户信息

POST /chat                   ← 对话（非流式）
POST /chat/stream            ← 对话（SSE 流式）

GET  /sessions               ← 会话列表
GET  /sessions/{id}          ← 会话消息
DELETE /sessions/{id}        ← 删除会话

GET  /documents              ← 文档列表（管理员）
POST /documents/upload       ← 上传文档（管理员）
DELETE /documents/{filename}  ← 删除文档（管理员）
```



### 5.2 API 路由详解 — [api.py](../backend/api.py) 逐行拆解

这个文件是所有 HTTP 请求的入口，每个函数对应一个 URL。代码不长但包含了 RAG 系统最核心的上传→检索→对话闭环。

#### 5.2.1 文件顶部的"全局初始化"（第 1-43 行）

```python
# api.py 第 38 行：数据存储在项目根目录下的 data/ 文件夹
DATA_DIR = BASE_DIR.parent / "data"
UPLOAD_DIR = DATA_DIR / "documents"

# 第 40-43 行：创建三个全局单例，整个应用共享
loader = DocumentLoader()             # 文档解析器
parent_chunk_store = ParentChunkStore()  # 父块存储（PostgreSQL + Redis）
milvus_manager = MilvusManager()      # Milvus 连接管理
milvus_writer = MilvusWriter(...)      # 向量写入器
```

**关键理解**：**这些是模块级变量，Python 在 `import api` 时只创建一次，全进程共享。这就是单例模式。为什么用单例？因为 Milvus 连接、Embedding 模型加载都很昂贵，不能每个请求都重新创建。**

#### 5.2.2 注册接口（第 58-75 行）

```python
@router.post("/auth/register", response_model=AuthResponse)
async def register(request: RegisterRequest, db: Session = Depends(get_db)):
    # 1. 检查用户名密码不为空
    # 2. 检查用户名是否已存在 → 409
    # 3. resolve_role() 判断角色：
    #    - 如果请求 admin 角色 → 必须提供正确的邀请码
    #    - 否则默认 user 角色
    # 4. 密码哈希后存入数据库
    # 5. 返回 JWT token
```

**面试亮点**：`resolve_role()` 在 [auth.py:126-132](../backend/auth.py#L126-L132)，管理员邀请码机制防止任何人随意注册为 admin。

#### 5.2.3 登录接口（第 78-84 行）

```python
@router.post("/auth/login", response_model=AuthResponse)
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    user = authenticate_user(db, request.username, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_access_token(username=user.username, role=user.role)
    return AuthResponse(access_token=token, username=user.username, role=user.role)
```

**面试亮点**：不区分"用户名不存在"和"密码错误"，统一返回 401。这是安全最佳实践，防止攻击者枚举用户名。

#### 5.2.4 聊天接口（第 135-183 行）— 核心

```python
@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest, current_user: User = Depends(get_current_user)):
    # 1. 从请求中拿 message 和 session_id（没传就用 "default_session"）
    # 2. 调用 chat_with_agent() → 走 Agent + RAG 流程
    # 3. 错误处理：429（限流）、401/403（认证）单独处理，其余 500
```

```python
@router.post("/chat/stream")
async def chat_stream_endpoint(request: ChatRequest, current_user: User = Depends(get_current_user)):
    # 流式版本：返回 StreamingResponse
    # media_type="text/event-stream"  ← 这是 SSE 协议标识
    # event_generator() 是一个异步生成器，用 yield 逐条推送数据
```

**面试亮点**：
- `StreamingResponse` + `text/event-stream` = SSE（Server-Sent Events）
- 三个关键 Header：`Cache-Control: no-cache`（不缓存）、`Connection: keep-alive`（长连接）、`X-Accel-Buffering: no`（禁用 Nginx 缓冲）
- `Depends(get_current_user)` = FastAPI 的依赖注入，自动从请求头取 JWT、验签、查用户，代码里直接用 `current_user` 变量

#### 5.2.5 文档管理接口（第 186-299 行）— 管理员专属

```python
@router.get("/documents")      # 查文档列表
@router.post("/documents/upload")  # 上传文档
@router.delete("/documents/{filename}")  # 删除文档
# 都需要 Depends(require_admin) → 非管理员直接 403
```

**上传流程**（第 216-279 行，是整个 RAG 系统的"数据入口"）：
```python
# 1. 检查文件类型（只允许 PDF/Word/Excel）
# 2. 如果同名文件已存在 → 先删旧的（BM25 统计 + Milvus 向量 + 父块）
# 3. 保存到 data/documents/
# 4. loader.load_document() → 三层分块
# 5. parent_chunk_store.upsert_documents(parent_docs) → Level 1+2 存 PostgreSQL
# 6. milvus_writer.write_documents(leaf_docs) → Level 3 向量化后存 Milvus
```

**面试亮点**：上传同名文件时先清理旧数据，保证"覆盖上传"而不是"追加"。三个存储（Milvus + PostgreSQL + BM25 统计）同步清理，防止脏数据。

## BM25 统计是什么

![image-20260601184315623](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601184315623.png)

#### 5.2.6 BM25 统计同步删除（第 48-55 行）

```python
def _remove_bm25_stats_for_filename(filename: str):
    # 从 Milvus 查该文件所有 chunk 的 text
    rows = milvus_manager.query_all(filter_expr=f'filename == "{filename}"', ...)
    texts = [r.get("text") or "" for r in rows]
    # 从 BM25 统计中扣减
    embedding_service.increment_remove_documents(texts)
```

**面试亮点**：删除文档不只是删向量，还要**逆更新 BM25 全局统计量**（DF、总文档数、总 token 长度），否则统计值会越来越偏，检索效果下降。

---

### 5.3 认证系统 — [auth.py](../backend/auth.py)

#### 5.3.1 密码哈希（第 32-78 行）

```python
def get_password_hash(password: str) -> str:
    salt = os.urandom(16)           # 16 字节随机盐
    digest = hashlib.pbkdf2_hmac(   # PBKDF2-SHA256，31 万轮迭代
        "sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS
    )
    # 格式：pbkdf2_sha256$轮数$salt_b64$hash_b64
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt_b64}${digest_b64}"
```

- PBKDF2 通过反复哈希 31 万次，暴力破解成本极高
- `os.urandom(16)` 生成真随机数做盐，两个相同密码的人哈希值也不同（防止彩虹表攻击）
- **16 字节随机盐 = 一串随机生成的、长度固定为 16 字节的字符串
  作用：给密码 “加调料”，让相同密码也能存成不一样的密文，防止被破解！**
- 还兼容了旧版 bcrypt 哈希（第 53-58 行），平滑迁移

#### 5.3.2 JWT 令牌（第 81-88 行）

```python
def create_access_token(username: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": username, "role": role, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
```

- Token 里存 username + role + 过期时间

- 用 HMAC-SHA256 签名，防止篡改

- `exp` 字段是 JWT 标准，FastAPI 自动校验过期

- ![image-20260601185047890](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601185047890.png)

  ## JWT 是什么？

  WT（JSON Web Token）就是用户登录成功后，服务器发给你的一张 “电子身份证”。
  以后每次请求接口，带着这张 “身份证”，服务器就知道 “你是谁、你是什么角色、有没有权限”，不用再每次输密码登录。
  你这段代码，就是生成这张 “身份证” 的函数。

#### 5.3.3 依赖注入链（第 100-132 行）

```
get_current_user  →  从请求头取 Bearer token → 验签 → 查数据库 → 返回 User
        │
        ▼
require_admin  →  调用 get_current_user → 检查 role == "admin" → 是则放行，否则 403
```

这两个函数都用 `Depends()` 装饰，FastAPI 会在调用 API 函数前自动执行。

#### 5.3.4 管理员邀请码机制（第 126-132 行）

```python
def resolve_role(requested_role, admin_code):
    if role != "admin":
        return "user"
    if ADMIN_INVITE_CODE and admin_code == ADMIN_INVITE_CODE:
        return "admin"
    raise HTTPException(status_code=403, detail="管理员邀请码错误")
```

- 普通人注册只能选 user
- 想注册 admin 必须输入正确的邀请码（`.env` 里的 `ADMIN_INVITE_CODE`）
- 邀请码不对直接报 403

---

### 5.4 Pydantic 数据模型 — [schemas.py](../backend/schemas.py)

这个文件定义了所有 API 请求/响应的"形状"，FastAPI 用它自动做**参数校验**和**文档生成**。

#### 5.4.1 请求模型（前端 → 后端）

```python
class RegisterRequest(BaseModel):
    username: str
    password: str
    role: Optional[str] = "user"      # 默认 user，传 "admin" 要邀请码
    admin_code: Optional[str] = None   # 注册管理员时填

class LoginRequest(BaseModel):
    username: str
    password: str

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default_session"
```

#### 5.4.2 响应模型（后端 → 前端）

```python
class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str

class ChatResponse(BaseModel):
    response: str
    rag_trace: Optional[RagTrace] = None  # 可选的 RAG 追溯信息
```

## bearer 是什么？

![image-20260601185801075](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601185801075.png)

#### 5.4.3 RAG Trace 模型（第 43-73 行）— 面试最爱问

```python
class RagTrace(BaseModel):
    # 检索阶段
    retrieval_mode: Optional[str] = None     # "hybrid" 或 "dense_fallback"
    candidate_k: Optional[int] = None        # 粗筛多少个候选
    leaf_retrieve_level: Optional[int] = None # L3 叶子层检索
    rerank_enabled: Optional[bool] = None     # 是否开启 Rerank
    rerank_applied: Optional[bool] = None     # Rerank 是否真正执行
    rerank_model: Optional[str] = None        # 用了哪个 Rerank 模型
    
    # 评分阶段
    grade_score: Optional[str] = None         # "yes" / "no"
    rewrite_needed: Optional[bool] = None     # 是否需要重写查询
    
    # 重写阶段
    rewrite_strategy: Optional[str] = None    # "step_back" / "hyde" / "complex"
    expansion_type: Optional[str] = None
    
    # Auto-merge
    auto_merge_enabled: Optional[bool] = None
    auto_merge_applied: Optional[bool] = None
    auto_merge_replaced_chunks: Optional[int] = None  # 多少个叶子被父块替换
```

**面试能聊**：我们把 RAG 每一步的内部状态都通过 `rag_trace` 返回前端，方便调试和监控。你能在前端看到"混合检索召回了 15 个候选，Rerank 后保留了 5 个，评分不通过触发了 Step-back 重写"，整个链路完全透明。

## RagTrace 是什么？

它是 RAG（检索增强生成）全链路的 “黑匣子日志”。
你可以把它理解成：
给你的 RAG 流程装了一个 “行车记录仪”，
把每一步的决策、参数、结果都记录下来，
最后返回给前端，方便调试、监控和排查问题。

---

### 5.5 数据库连接 — [database.py](../backend/database.py)

```python
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://...")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
# pool_pre_ping=True：每次从连接池取连接前先发 SELECT 1 检测
# 防止拿到已被数据库端关闭的连接（常见于长时间空闲后）

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
# autoflush=False：不自动同步内存对象到数据库，手动 commit
# autocommit=False：事务手动管理

Base = declarative_base()  # 所有 ORM 模型继承这个 Base

def init_db():
    import models  # 导入触发所有 ORM 类注册到 Base
    Base.metadata.create_all(bind=engine)  # 自动建表（如果表不存在）
```

**为什么 `init_db()` 里才 import models？** 如果放文件顶部，可能触发循环引用（models → database → models）。延迟导入解耦。

---

### 5.6 ORM 数据表 — [models.py](../backend/models.py)

四张表对应四个类，每张表用图解说明：

#### User 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT (PK) | 自增主键 |
| username | VARCHAR(100) UNIQUE | 用户名，有索引 |
| password_hash | VARCHAR(255) | PBKDF2 哈希后的密码 |
| role | VARCHAR(20) | "user" 或 "admin" |
| created_at | DATETIME | 注册时间 |

#### ChatSession 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT (PK) | 自增主键 |
| user_id | INT (FK → users.id) | 谁创建的会话 |
| session_id | VARCHAR(120) | 会话标识符（前端生成，如 UUID） |
| metadata_json | JSON | 扩展元数据 |
| updated_at | DATETIME | 最后活跃时间，用于排序 |

**为什么 `user_id + session_id` 有联合唯一约束？** 不同用户可以创建同名 session_id，但同一个用户不能有重复的。

#### ChatMessage 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT (PK) | 自增 |
| session_ref_id | INT (FK → chat_sessions.id) | 属于哪个会话 |
| message_type | VARCHAR(20) | "human"、"ai" 或 "system" |
| content | TEXT | 消息正文 |
| timestamp | DATETIME | 消息时间 |
| rag_trace | JSON (nullable) | 这条 AI 回复的 RAG 追溯信息 |

#### ParentChunk 表

| 字段 | 类型 | 说明 |
|------|------|------|
| chunk_id | VARCHAR(512) (PK) | 分块唯一标识 |
| text | TEXT | 块内容 |
| parent_chunk_id | VARCHAR(512) | 父块 ID（用于 Auto-merge） |
| root_chunk_id | VARCHAR(512) | 根块 ID |
| chunk_level | INT | 1/2/3 层级 |
| filename, file_type, page_number | — | 元数据 |

---

### 5.7 Redis 缓存 — [cache.py](../backend/cache.py)

```python
class RedisCache:
    def __init__(self):
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.key_prefix = os.getenv("REDIS_KEY_PREFIX", "supermew")
        self.default_ttl = int(os.getenv("REDIS_CACHE_TTL_SECONDS", "300"))
        # 关键参数：
        # decode_responses=True → 自动把 bytes 转成 str
```

#### 核心方法

```python
def get_json(self, key):
    value = self._get_client().get(self._key(key))
    if not value: return None
    return json.loads(value)     # Redis 存字符串，取出来反序列化

def set_json(self, key, value, ttl=None):
    payload = json.dumps(value, ensure_ascii=False)
    self._get_client().setex(   # SET + EXPIRE 原子操作
        self._key(key),
        ttl or self.default_ttl, # 默认 300 秒
        payload
    )

def delete(self, key):
    self._get_client().delete(self._key(key))

def delete_pattern(self, pattern):
    # 支持通配符删除：cache.delete_pattern("chat_sessions:*")
    full_pattern = self._key(pattern)
    keys = self._get_client().keys(full_pattern)
    if keys: self._get_client().delete(*keys)
```

**设计模式**：cache-aside（旁路缓存）

```
读请求 → 查 Redis
           ├─ 命中 → 直接返回（~1ms）
           └─ 未命中 → 查 PostgreSQL → 结果写入 Redis → 返回（~10ms）
```

**面试能聊**：
- TTL 为什么是 300 秒？对话消息更新频率低，5 分钟过期足够。太短缓存命中率低，太长数据不一致风险大。

- `setex` 而不是 `set` + `expire`？原子操作，防止 `set` 后 `expire` 前进程崩溃导致 key 永不过期。

- `delete_pattern` 用在什么时候？删除会话时清理该用户所有相关缓存，防止脏读。

  ## 什么是命中

- ![image-20260601192240142](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601192240142.png)

---

### 5.8 向量写入器 — [milvus_writer.py](../backend/milvus_writer.py)

```python
class MilvusWriter:
    def write_documents(self, documents, batch_size=50):
        # 1. 确保 Milvus collection 存在（不存在则创建）
        self.milvus_manager.init_collection()
        
        # 2. 更新 BM25 全局统计（这一步在 Milvus 写入之前）
        all_texts = [doc["text"] for doc in documents]
        self.embedding_service.increment_add_documents(all_texts)
        
        # 3. 分批写入（每批 50 个）
        for i in range(0, len(documents), batch_size):
            batch = documents[i:i + batch_size]
            texts = [doc["text"] for doc in batch]
            
            # 同时生成稠密向量和稀疏向量
            dense_embeddings, sparse_embeddings = \
                self.embedding_service.get_all_embeddings(texts)
            
            # 组装每条数据的 10 个字段
            insert_data = [{
                "dense_embedding": dense_emb,    # 512 维浮点数列表
                "sparse_embedding": sparse_emb,   # {词ID: 分数} 字典
                "text": doc["text"],
                "filename": doc["filename"],
                "chunk_level": doc.get("chunk_level", 0),
                # ... 其他 6 个字段
            } for doc, dense_emb, sparse_emb in zip(batch, dense_embeddings, sparse_embeddings)]
            
            self.milvus_manager.insert(insert_data)
```

**面试能聊**：
- 为什么 batch_size=50？Milvus 单次插入数据量有限制，太大会 OOM，太小会频繁网络 IO

  ## 什么是OOM  IO

  ![image-20260601192915795](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601192915795.png)

  ![image-20260601193253777](C:\Users\WINDOWS\AppData\Roaming\Typora\typora-user-images\image-20260601193253777.png)

- 为什么 BM25 更新在 Milvus 写入之前？如果写入失败不会污染统计；如果统计更新了但写入失败，BM25 会比实际多一点，比少一点影响小

- `get_all_embeddings()` 一次调用同时生成稠密和稀疏，避免重复分词

---

### 5.9 父块存储 — [parent_chunk_store.py](../backend/parent_chunk_store.py)

这是 Auto-merge 的"弹药库"——当叶子块检索到后，从这拿父块来替换。

```python
class ParentChunkStore:
    def upsert_documents(self, docs):
        # 对每个 Level 1/2 分块：
        #   如果 chunk_id 已存在 → UPDATE
        #   如果不存在 → INSERT
        #   同时写入 Redis 缓存
    
    def get_documents_by_ids(self, chunk_ids):
        # 1. 先查 Redis（有的直接返回）
        # 2. 未命中的查 PostgreSQL
        # 3. 查到的结果回写 Redis
        # 4. 按原始 chunk_ids 顺序返回（保持排序）
```

**面试能聊**：这是典型的 cache-aside + write-through 双写模式。而且用了 UPSERT（存在则更新，不存在则插入），支持同名文档覆盖上传而不会产生重复记录。

---

### 5.10 应用入口 — [app.py](../backend/app.py)

```python
def create_app() -> FastAPI:
    app = FastAPI(title="Cute Cat Bot API")

    # 启动事件：首次请求前自动建表
    @app.on_event("startup")
    async def _startup_init_db():
        init_db()  # 创建所有表（如果不存在）

    # CORS 中间件：允许任何来源的前端调用 API
    app.add_middleware(CORSMiddleware, allow_origins=["*"], ...)

    # 自定义中间件：禁用前端文件的浏览器缓存
    @app.middleware("http")
    async def _no_cache(request, call_next):
        response = await call_next(request)
        if path.endswith((".html", ".js", ".css")):
            response.headers["Cache-Control"] = "no-cache, ..."
        return response

    # 挂载 API 路由
    app.include_router(api_module.router)

    # 挂载前端静态文件（在 "/" 路径）
    if FRONTEND_DIR.exists():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="static")

    return app

app = create_app()  # 模块级单例，uvicorn 导入时执行

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

**关键设计决策**：

1. **`html=True`** 的作用：当访问 `/` 时自动返回 `index.html`；当访问 `/chat-page` 这种 SPA 路由时也 fallback 到 `index.html`，由前端 Vue Router 接管
2. **`_no_cache` 中间件**：开发阶段每次刷新都加载最新 JS/CSS，否则改了代码浏览器还用缓存的老文件
3. **`create_app()` 工厂函数**：不是直接 `app = FastAPI()`，而是包了一层函数。方便测试时创建多个独立实例

---

### 5.11 前端 — [frontend/](../frontend/)

三个文件，纯 HTML/CSS/JS，不依赖 Node.js / Webpack 等构建工具。

```
frontend/
├── index.html   ← Vue 3 模板（CDN 引入，不需要 npm install）
├── script.js    ← 所有交互逻辑
└── style.css    ← 猫咪主题样式
```

**面试能聊**：为什么不用 React/Vite 等现代工具链？这个项目的前端逻辑很简单（聊天界面 + 文档管理），Vue 3 CDN 引入+原生 JS 完全够用。省掉了整个 Node.js 构建流程，部署只需要把三个静态文件丢给 FastAPI 托管。这就是"够用就行"的工程判断。

---

## 全部文件面试问题速查表

| 面试问题 | 在哪找答案 | 关键词 |
|----------|-----------|--------|
| 上传的文档怎么变成能搜索的？ | document_loader.py 1.2 节 + api.py 5.2.5 节 | 三层分块、双路向量化 |
| 混合检索是什么意思？ | milvus_client.py 3.1 节 | Dense+Sparse+RRF |
| Auto-merge 怎么工作的？ | rag_utils.py 3.3 节 + parent_chunk_store.py 5.9 节 | 父块替换、叶子→父块 |
| 用户问题搜不到结果怎么办？ | rag_pipeline.py 4.2 节 | Step-back、HyDE、查询重写 |
| Rerank 和向量检索什么区别？ | rag_utils.py 3.2 节 | Bi-encoder vs Cross-encoder |
| 对话怎么实现流式输出？ | agent.py 4.3 节 + api.py 5.2.4 节 | SSE、yield、asyncio.Queue |
| 删除文档时 BM25 统计怎么处理？ | api.py 5.2.6 节 + embedding.py 1.3 节 | increment_remove、逆更新 |
| 密码怎么存的？安全性如何？ | auth.py 5.3.1 节 | PBKDF2、salt、31 万轮 |
| 怎么区分普通用户和管理员？ | auth.py 5.3.4 节 | 邀请码机制 |
| API 怎么知道是哪个用户在请求？ | auth.py 5.3.3 节 | JWT + Depends 依赖注入 |
| 缓存怎么设计的？ | cache.py 5.7 节 | cache-aside、TTL、setex |
| 为什么前端没有用 React/Vite？ | app.py 5.10 节 + frontend/ | CDN 引入、够用就行 |

---

## 数据流全景图

```
用户上传 PDF
    │
    ▼
document_loader.py    解析 + 三层分块
    │
    ├──→ Level 3 叶子块 → embedding.py 生成 Dense+Sparse 向量 → MilvusWriter → Milvus
    │                                                                              
    └──→ Level 1+2 父块 → ParentChunkStore → PostgreSQL (+ Redis 缓存)              
                                                                                    
用户提问                                                                              
    │                                                                               
    ▼                                                                               
agent.py 判断是否需要搜索 → tools.py search_knowledge_base                           
    │                                                                               
    ▼                                                                               
rag_pipeline.py 编排流程:                                                            
    ① retrieve_initial  →  rag_utils.retrieve_documents()                           
                              ├─ 稠密+稀疏 → Milvus.hybrid_retrieve()               
                              ├─ Rerank 重排                                         
                              └─ Auto-merge → 从 PostgreSQL 拉父块替换               
    ② grade_documents   →  LLM 评分相关性                                           
    ③ rewrite_question  →  Step-back / HyDE 扩展查询                                
    ④ retrieve_expanded →  重新检索 + 合并去重                                       
    │                                                                               
    ▼                                                                               
LLM 拿到检索结果 + 对话历史 → 生成回答 → SSE 流式返回前端
```

---

## 按学习顺序的阅读清单

| 顺序 | 文件 | 关注点 | 预计时间 |
|------|------|--------|----------|
| 1 | [document_loader.py](../backend/document_loader.py) | 三种文件解析 + 三层分块算法 | 30min |
| 2 | [embedding.py](../backend/embedding.py) | Dense/Sparse 向量原理 + BM25 增量更新 | 30min |
| 3 | [milvus_client.py](../backend/milvus_client.py) | Schema 设计 + 混合检索 RRF | 25min |
| 4 | [milvus_writer.py](../backend/milvus_writer.py) | 文档写入 Milvus 的流程 | 10min |
| 5 | [models.py](../backend/models.py) + [database.py](../backend/database.py) | ORM 表设计 | 10min |
| 6 | [parent_chunk_store.py](../backend/parent_chunk_store.py) | Auto-merge 的存储基础 | 15min |
| 7 | [rag_utils.py](../backend/rag_utils.py) | 检索流程 + Rerank + Auto-merge + Step-back + HyDE | **45min** |
| 8 | [rag_pipeline.py](../backend/rag_pipeline.py) | LangGraph 状态机编排 | 25min |
| 9 | [tools.py](../backend/tools.py) | Agent 工具 + RAG 步骤队列 | 20min |
| 10 | [agent.py](../backend/agent.py) | Agent 创建 + 流式输出架构 | 30min |
| 11 | [api.py](../backend/api.py) + [schemas.py](../backend/schemas.py) | RESTful API 设计 | 20min |
| 12 | [auth.py](../backend/auth.py) + [cache.py](../backend/cache.py) | JWT 认证 + Redis 缓存 | 15min |
| 13 | [app.py](../backend/app.py) + [frontend/](../frontend/) | FastAPI 入口 + Vue 前端 | 15min |

**总计约 5 小时**，一口气读完或分几天都可以。

---

## 如果自己从 0 搭建，核心设计决策回顾

1. **为什么选 Milvus 而不是 ChromaDB/Faiss？** Milvus 原生支持混合检索（Dense+Sparse + RRF），ChromaDB 只支持 Dense，Faiss 只支持向量搜索没有数据库能力

2. **为什么需要三层分块？** 单层小块检索精准但上下文不够；单层大块上下文完整但检索不精准。三层分块 + Auto-merge 做到了"检索用小块，回答用大块"

3. **为什么用 BM25 做稀疏向量而不是直接用 TF-IDF？** BM25 是 TF-IDF 的改进版，多了饱和度函数和长度归一化，效果更好

4. **为什么用 Query Expansion（Step-back + HyDE）？** 用户的问题往往和知识库文档在语义空间有差距（"CNN 为啥厉害" vs "卷积神经网络优势"），扩展查询能桥接这个 gap

5. **为什么用 Rerank？** 向量检索是预计算的（速度快），Rerank 是实时计算的（精度高）。两阶段检索（粗筛 + 精排）是业界的标准做法
