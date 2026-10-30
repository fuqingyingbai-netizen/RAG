
# Milvus 客户端 - 支持密集向量+稀疏向量混合检索
# 功能：
#   1) 连接 Milvus 向量数据库
#   2) 创建集合（表）：同时存 密集向量 + 稀疏向量 + 文本 + 元数据
#   3) 插入数据、查询数据、删除数据
#   4) 核心：混合检索（语义+关键词）= RRF 融合结果
#   5) 支持仅密集向量检索（降级方案）
# 用途：RAG 系统的向量存储与检索核心模块


from __future__ import annotations

# 操作系统交互：读取环境变量
import os
from typing import TYPE_CHECKING
# 读取 .env 文件里的配置（地址、端口、集合名、向量维度等）
from dotenv import load_dotenv
if TYPE_CHECKING:
    from pymilvus import MilvusClient

# 加载 .env 环境变量
load_dotenv()

# ==================== 全局常量 ====================
# Milvus 单次查询最大返回条数（超过会报错）
QUERY_MAX_LIMIT = 16384
MILVUS_VARCHAR_LIMITS = {
    "text": 2000,
    "filename": 255,
    "file_type": 50,
    "file_path": 1024,
    "chunk_id": 512,
    "parent_chunk_id": 512,
    "root_chunk_id": 512,
}


def _clip_varchar_fields(row: dict) -> dict:
    """Milvus rejects oversized VARCHAR values, so keep rows within schema limits."""
    clipped = dict(row)
    for field, limit in MILVUS_VARCHAR_LIMITS.items():
        if field in clipped and clipped[field] is not None:
            value = str(clipped[field])
            clipped[field] = value if len(value) <= limit else value[:limit]
    return clipped


# ==================== Milvus 管理类 ====================
class MilvusManager:
    """
    Milvus 连接和集合（表）管理
    核心能力：建表、插入、查询、混合检索、删除
    """

    def __init__(self):
        """
        构造函数：初始化连接信息
        知识点：
          1. __init__ 是类初始化方法，创建实例时自动执行
          2. os.getenv(键, 默认值) → 读取环境变量
        """
        # Milvus 服务地址
        self.host = os.getenv("MILVUS_HOST", "localhost")
        # Milvus 端口
        self.port = os.getenv("MILVUS_PORT", "19530")
        # 集合名（相当于数据库表名）
        self.collection_name = os.getenv("MILVUS_COLLECTION", "embeddings_collection")
        # 拼接连接地址
        self.uri = f"http://{self.host}:{self.port}"
        # 客户端连接对象（先设为 None，用到时再创建 → 懒加载）
        self.client = None

    def _get_client(self) -> MilvusClient:
        """
        【内部工具方法】
        懒加载创建客户端：
          只有真正需要连接时才创建，避免启动时阻塞
          多次调用只会创建一次
        """
        # 如果还没创建客户端
        if self.client is None:
            # The SDK imports native gRPC modules. Login/account-only startup
            # must not load that runtime before a vector operation is requested.
            from pymilvus import MilvusClient
            # 创建连接
            self.client = MilvusClient(uri=self.uri)
        # 返回客户端对象
        return self.client

    # ==================== 核心：创建集合（表） ====================
    def init_collection(self, dense_dim: int | None = None):
        """
        初始化 Milvus 集合（表）
        同时支持：密集向量 + 稀疏向量 + 所有元数据
        :param dense_dim: 密集向量维度（bge-m3=1024）
        """
        # 如果没传维度，从环境变量读取，默认 1024
        if dense_dim is None:
            dense_dim = int(os.getenv("DENSE_EMBEDDING_DIM", "1024"))

        # 获取客户端连接
        client = self._get_client()

        # 如果集合不存在，才创建
        if not client.has_collection(self.collection_name):
            from pymilvus import DataType
            # 创建表结构：自动ID + 允许动态新增字段
            schema = client.create_schema(auto_id=True, enable_dynamic_field=True)

            # -------------------- 字段定义 --------------------
            # 知识点：schema.add_field(字段名, 类型, 其他参数)

            # 主键 ID（自动生成）
            schema.add_field("id", DataType.INT64, is_primary=True, auto_id=True)

            # 密集向量（来自 EmbeddingService 模型）
            schema.add_field("dense_embedding", DataType.FLOAT_VECTOR, dim=dense_dim)

            # 稀疏向量（来自 EmbeddingService BM25）
            schema.add_field("sparse_embedding", DataType.SPARSE_FLOAT_VECTOR)

            # 文本内容（来自 DocumentLoader chunk）
            schema.add_field("text", DataType.VARCHAR, max_length=2000)

            # 文件元数据
            schema.add_field("filename", DataType.VARCHAR, max_length=255)
            schema.add_field("file_type", DataType.VARCHAR, max_length=50)
            schema.add_field("file_path", DataType.VARCHAR, max_length=1024)
            schema.add_field("page_number", DataType.INT64)
            schema.add_field("chunk_idx", DataType.INT64)

            # 三级分片所需层级字段（来自 DocumentLoader）
            schema.add_field("chunk_id", DataType.VARCHAR, max_length=512)
            schema.add_field("parent_chunk_id", DataType.VARCHAR, max_length=512)
            schema.add_field("root_chunk_id", DataType.VARCHAR, max_length=512)
            schema.add_field("chunk_level", DataType.INT64)

            # -------------------- 创建索引（加速检索） --------------------
            index_params = client.prepare_index_params()

            # 密集向量索引：HNSW（高精度检索）
            index_params.add_index(
                field_name="dense_embedding",
                # 给密集向量字段建索引（就是模型生成的语义向量）
                index_type="HNSW",
                # 索引类型用 HNSW
                # 这是语义检索最强索引，速度快、精度高
                metric_type="IP",         # 内积相似度（语义检索）
                # 相似度计算方式用 IP（内积）
                # 专门用来算语义相似度
                params={"M": 16, "efConstruction": 256}
            #     索引内部参数（行业标准值，不用改）
                # 控制精度与速度，值越大越准，但建库越慢
            )

            # 稀疏向量索引：倒排索引（关键词检索）
            index_params.add_index(
                field_name="sparse_embedding",
                # 给 ** 稀疏向量（BM25）** 建索引
                index_type="SPARSE_INVERTED_INDEX",
                # 稀疏向量专用倒排索引
                # 专门加速关键词搜索
                metric_type="IP",
                # 稀疏向量也用内积计算相似度
                params={"drop_ratio_build": 0.2}
            #     建索引时丢弃 20% 不重要的关键词
                # 节省空间、加速检索（标准值）
            )

            # 最终创建集合
            client.create_collection(
                collection_name=self.collection_name,
                schema=schema,
                index_params=index_params
            )

    # ==================== 插入数据 ====================
    def insert(self, data: list[dict]):
        """插入数据到 Milvus"""
        safe_data = [_clip_varchar_fields(row) for row in data]
        return self._get_client().insert(self.collection_name, safe_data)

    # ==================== 普通精确查询 ====================
    def query(
        self,
        filter_expr: str = "",            # 过滤条件（查什么）
        output_fields: list[str] = None,  # 要返回哪些字段
        limit: int = 10000,               # 最多返回几条
        offset: int = 0,                 # 从第几条开始
    ):
        """
        普通查询（非向量检索）
        例：filename="test.pdf"
        """
        return self._get_client().query(
            collection_name=self.collection_name,
            filter=filter_expr,
            output_fields=output_fields or ["filename", "file_type"],
            limit=min(limit, QUERY_MAX_LIMIT),
            offset=offset,
        )

    # ==================== 分页查询全部 ====================
    # ==================== 分页查询全部 ====================
    def query_all(self, filter_expr: str = "", output_fields: list[str] | None = None) -> list:
        """
        自动分页拉取所有符合条件的数据
        解决 Milvus 单次查询最多只能返回 16384 条的限制
        无论数据量多大，都能完整返回
        """
        # 如果用户没有指定要返回的字段，默认只返回 filename 和 file_type
        fields = output_fields or ["filename", "file_type"]

        # 创建一个空列表，用于存储最终所有查询到的数据
        out = []

        # 分页起始位置，初始从第0条数据开始查询
        offset = 0

        # 无限循环，直到查询完所有数据才退出
        while True:
            # 执行单次普通查询，每次最多查 QUERY_MAX_LIMIT = 16384 条
            batch = self._get_client().query(
                collection_name=self.collection_name,  # 指定要查询的集合（表名）
                filter=filter_expr,  # 查询过滤条件，类似SQL的WHERE
                output_fields=fields,  # 指定需要返回哪些字段
                limit=QUERY_MAX_LIMIT,  # 每次查询最大数量，受Milvus限制
                offset=offset,  # 本次查询从第几条开始
            )

            # 如果本次查询没有获取到任何数据，说明已经全部查完，退出循环
            if not batch:
                break

            # 把本次查询到的一批数据，添加到总结果列表中
            out.extend(batch)

            # 如果本次返回的数据量不足最大值，说明是最后一页，查询结束
            if len(batch) < QUERY_MAX_LIMIT:
                break

            # 更新offset，下次查询从下一批数据开始
            offset += len(batch)

        # 返回所有查询到的完整数据
        return out

    # ==================== 根据ID查询分块（父块拉取） ====================
    # ==================== 根据 chunk_id 批量查询分块 ====================
    def get_chunks_by_ids(self, chunk_ids: list[str]) -> list[dict]:
        """
        根据传入的 chunk_id 列表，批量查询对应的分块数据
        主要用于 Auto-merging 检索：根据子块ID，拉取对应的父块/根块信息
        :param chunk_ids: 要查询的 chunk_id 字符串列表
        :return: 匹配到的分块数据列表
        """
        # 过滤掉列表中的空字符串、无效值，只保留有效的 chunk_id
        ids = [item for item in chunk_ids if item]

        # 如果过滤后没有有效ID，直接返回空列表，不执行后续查询
        if not ids:
            return []

        # 把ID列表处理成 Milvus WHERE IN 语法需要的格式："id1","id2","id3"
        quoted_ids = ", ".join([f'"{item}"' for item in ids])

        # 构造过滤条件：查询 chunk_id 在指定列表中的数据（等价于 SQL 的 IN 查询）
        filter_expr = f"chunk_id in [{quoted_ids}]"

        # 调用本类的普通 query 方法，执行精确查询并返回结果
        return self.query(
            filter_expr=filter_expr,  # 使用拼接好的 ID 过滤条件
            output_fields=[  # 指定需要返回的所有分块相关字段
                "text", "filename", "file_type", "page_number",
                "chunk_id", "parent_chunk_id", "root_chunk_id",
                "chunk_level", "chunk_idx"
            ],
            limit=len(ids),  # 限制返回数量 = 传入的ID数量，避免多余数据
        )

    # ==================== 【核心】混合检索 ====================
    def hybrid_retrieve(
        self,
        dense_embedding: list[float],
        sparse_embedding: dict,
        top_k: int = 5,
        rrf_k: int = 60,
        filter_expr: str = "",
    ) -> list[dict]:
        """
        混合检索 = 密集向量（语义） + 稀疏向量（关键词）
        使用 RRF 算法融合两个检索结果 → 最强检索效果
        """
        from pymilvus import AnnSearchRequest, RRFRanker
        # 要返回的字段
        output_fields = [
            "text", "filename", "file_type", "page_number",
            "chunk_id", "parent_chunk_id", "root_chunk_id",
            "chunk_level", "chunk_idx"
        ]

        # 1. 构造密集向量检索请求
        dense_search = AnnSearchRequest(
            data=[dense_embedding],
            anns_field="dense_embedding",
            param={"metric_type": "IP", "params": {"ef": 64}},
            # HNSW 索引的检索参数 "ef": 64 搜索时多查一些候选结果，保证精度更高
            limit=top_k * 2,
            expr=filter_expr,
        )

        # 2. 构造稀疏向量检索请求
        sparse_search = AnnSearchRequest(
            data=[sparse_embedding],
            anns_field="sparse_embedding",
            param={"metric_type": "IP", "params": {"drop_ratio_search": 0.2}},
            limit=top_k * 2,
            expr=filter_expr,
        )

        # 3. RRF 结果融合（两个检索结果重新排序）
        reranker = RRFRanker(k=rrf_k)

        # 4. 执行混合检索
        results = self._get_client().hybrid_search(
            collection_name=self.collection_name,
            reqs=[dense_search, sparse_search],
            ranker=reranker,
            limit=top_k,
            output_fields=output_fields
        )

        # 5. 格式化结果
        formatted_results = []
        for hits in results:
            for hit in hits:
                formatted_results.append({
                    "id": hit.get("id"),
                    "text": hit.get("text", ""),
                    "filename": hit.get("filename", ""),
                    "file_type": hit.get("file_type", ""),
                    "page_number": hit.get("page_number", 0),
                    "chunk_id": hit.get("chunk_id", ""),
                    "parent_chunk_id": hit.get("parent_chunk_id", ""),
                    "root_chunk_id": hit.get("root_chunk_id", ""),
                    "chunk_level": hit.get("chunk_level", 0),
                    "chunk_idx": hit.get("chunk_idx", 0),
                    "score": hit.get("distance", 0.0)
                })

        return formatted_results

    # ==================== 仅密集向量检索（降级） ====================
    def dense_retrieve(self, dense_embedding: list[float], top_k: int = 5, filter_expr: str = "") -> list[dict]:
        """只使用密集向量检索（备用方案）"""
        results = self._get_client().search(
            collection_name=self.collection_name,
            data=[dense_embedding],
            anns_field="dense_embedding",
            search_params={"metric_type": "IP", "params": {"ef": 64}},
            limit=top_k,
            output_fields=[
                "text", "filename", "file_type", "page_number",
                "chunk_id", "parent_chunk_id", "root_chunk_id",
                "chunk_level", "chunk_idx"
            ],
            filter=filter_expr,
        )

        formatted_results = []
        for hits in results:
            for hit in hits:
                formatted_results.append({
                    "id": hit.get("id"),
                    "text": hit.get("entity", {}).get("text", ""),
                    "filename": hit.get("entity", {}).get("filename", ""),
                    "file_type": hit.get("entity", {}).get("file_type", ""),
                    "page_number": hit.get("entity", {}).get("page_number", 0),
                    "chunk_id": hit.get("entity", {}).get("chunk_id", ""),
                    "parent_chunk_id": hit.get("entity", {}).get("parent_chunk_id", ""),
                    "root_chunk_id": hit.get("entity", {}).get("root_chunk_id", ""),
                    "chunk_level": hit.get("entity", {}).get("chunk_level", 0),
                    "chunk_idx": hit.get("entity", {}).get("chunk_idx", 0),
                    "score": hit.get("distance", 0.0)
                })
        return formatted_results

    # ==================== 删除数据 ====================
    def delete(self, filter_expr: str):
        return self._get_client().delete(
            collection_name=self.collection_name,
            filter=filter_expr
        )

    # ==================== 判断表是否存在 ====================
    def has_collection(self) -> bool:
        return self._get_client().has_collection(self.collection_name)

    # ==================== 删除整张表 ====================
    def drop_collection(self):
        client = self._get_client()
        if client.has_collection(self.collection_name):
            client.drop_collection(self.collection_name)
