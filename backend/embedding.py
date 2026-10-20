"""
文本向量化服务
功能：
  1) 生成密集向量：用本地 BGE-M3 模型（用于语义搜索）
  2) 生成稀疏向量：用 BM25 算法（用于关键词搜索）
  3) 自动保存词表、文档频率、平均长度（持久化到 json）
  4) 支持增量添加/删除文档，自动更新统计
用途：RAG 检索（混合检索 = 语义 + 关键词）
"""

from __future__ import annotations

import json       # 读写 JSON 文件（保存 BM25 数据）
import math       # 数学计算：log、除法等
import os         # 文件/路径操作
import re         # 正则表达式：分词用
import threading  # 线程锁：防止多线程同时写文件导致错乱
from collections import Counter  # 计数工具：统计词频
from pathlib import Path         # 路径工具：更安全的文件路径

from dotenv import load_dotenv   # 读取 .env 配置文件
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_huggingface import HuggingFaceEmbeddings

# 加载环境变量（.env 文件里的模型名、设备等）
load_dotenv()

# BM25 状态保存路径：保存词表、文档数、词频等
_DEFAULT_STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "bm25_state.json"


# ==================== 【工具函数】创建本地密集向量模型 ====================
def _create_dense_embedder() -> HuggingFaceEmbeddings:
    """
    创建本地密集向量生成器（语义向量）
    从环境变量读取：
      EMBEDDING_MODEL：模型名称，默认 BAAI/bge-m3
      EMBEDDING_DEVICE：运行设备，默认 cpu
    """
    # Importing this dependency also imports the tensor/model runtime. Keep both
    # the import and model construction out of login and account-only startup.
    from langchain_huggingface import HuggingFaceEmbeddings

    model_name = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
    device = os.getenv("EMBEDDING_DEVICE", "cpu")

    return HuggingFaceEmbeddings(
        model_name=model_name,
        model_kwargs={"device": device},          # 使用 CPU 或 GPU
        encode_kwargs={"normalize_embeddings": True},  # 向量归一化（提高搜索精度）
    )


# ==================== 【核心类】向量化服务 ====================
class EmbeddingService:
    """
    文本向量化服务：
      - 密集向量（语义）：本地 BGE 模型
      - 稀疏向量（关键词）：BM25 算法
      - 持久化：词表、文档总数、文档频率、平均长度
    """

    def __init__(self, state_path: Path | str | None = None):
        """
        初始化：
          1) 准备密集向量模型的按需初始化锁
          2) 设置 BM25 保存路径
          3) 初始化线程锁
          4) 加载历史 BM25 统计数据
        """
        # Sparse statistics do not require the dense model. Initialize that
        # model once, on the first non-empty dense embedding request.
        self._embedder = None
        self._embedder_lock = threading.Lock()

        # 2. BM25 状态保存文件路径（词表、文档数、df等）
        self._state_path = Path(state_path or os.getenv("BM25_STATE_PATH", _DEFAULT_STATE_PATH))

        # 3. 线程锁：多线程同时修改数据时防止错乱
        self._lock = threading.Lock()

        # ==================== BM25 核心参数 ====================
        # 标准 BM25 参数，不用改
        self.k1 = 1.5
        self.b = 0.75

        # ==================== 持久化变量 ====================
        # 词表：{词: 编号}
        self._vocab: dict[str, int] = {}
        # 下一个新词的编号
        self._vocab_counter = 0
        # 文档频率：{词: 多少篇文档包含这个词}
        self._doc_freq: Counter[str] = Counter()
        # 总文档数
        self._total_docs = 0
        # 所有文档的总词数之和
        self._sum_token_len = 0
        # 平均文档长度（BM25 必须）
        self._avg_doc_len = 1.0

        # 从文件加载历史数据
        self._load_state()

    def _get_embedder(self) -> HuggingFaceEmbeddings:
        if self._embedder is None:
            with self._embedder_lock:
                if self._embedder is None:
                    # A failed initialization leaves None so a later request
                    # can retry after the model/configuration is repaired.
                    self._embedder = _create_dense_embedder()
        return self._embedder

    def _recompute_avg_len(self) -> None:
        """重新计算平均文档长度：总词数 / 总文档数"""
        if self._total_docs > 0:
            self._avg_doc_len = self._sum_token_len / self._total_docs
        else:
            self._avg_doc_len = 1.0

    def _load_state(self) -> None:
        """
        从 bm25_state.json 加载：
          词表、文档数、总长度、文档频率
        如果文件不存在/损坏，就跳过
        """
        path = self._state_path
        if not path.is_file():
            return  # 没有文件，直接用空的初始化

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except:
            return  # 文件损坏，放弃加载

        # 版本必须是 1，避免不兼容
        if raw.get("version") != 1:
            return

        # 恢复所有统计数据
        self._vocab = {str(k): int(v) for k, v in raw.get("vocab", {}).items()}
        self._doc_freq = Counter({str(k): int(v) for k, v in raw.get("doc_freq", {}).items()})
        self._total_docs = int(raw.get("total_docs", 0))
        self._sum_token_len = int(raw.get("sum_token_len", 0))

        # 恢复词表计数器
        if self._vocab:
            self._vocab_counter = max(self._vocab.values()) + 1
        else:
            self._vocab_counter = 0

        # 重新计算平均长度
        self._recompute_avg_len()

    def _persist_unlocked(self) -> None:
        """
        不加锁地保存数据到文件（内部用）
        先写临时文件，再替换，防止损坏
        """
        # 自动创建文件夹
        self._state_path.parent.mkdir(parents=True, exist_ok=True)

        # 要保存的数据
        payload = {
            "version": 1,
            "total_docs": self._total_docs,
            "sum_token_len": self._sum_token_len,
            "vocab": self._vocab,
            "doc_freq": dict(self._doc_freq),
        }

        # 写入临时文件 → 再替换（安全写入）
        tmp = self._state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._state_path)

    def _persist(self) -> None:
        """带锁的安全保存（外部不要调用）"""
        with self._lock:
            self._persist_unlocked()

    # ==================== 【增量更新】添加文档 ====================
    def increment_add_documents(self, texts: list[str]) -> None:
        """
        增量添加一批文档，更新 BM25 统计：
          - 总文档数 +1
          - 总词数累加
          - 文档频率（df）累加
          - 新词加入词表
        """
        if not texts:
            return

        with self._lock:
            for text in texts:
                # 1. 分词
                tokens = self.tokenize(text)
                doc_len = len(tokens)

                # 2. 更新统计
                self._sum_token_len += doc_len
                self._total_docs += 1

                # 3. 每篇文档里的词只算一次（df = 文档频率）
                for token in set(tokens):
                    if token not in self._vocab:
                        self._vocab[token] = self._vocab_counter
                        self._vocab_counter += 1
                    self._doc_freq[token] += 1

            # 4. 重新计算平均长度
            self._recompute_avg_len()
            # 5. 保存到文件
            self._persist_unlocked()

    # ==================== 【增量更新】删除文档 ====================
    def increment_remove_documents(self, texts: list[str]) -> None:
        """
        增量删除文档，对称减少统计：
          总文档数、总长度、df 都减少
          不删除词表，防止向量维度错乱
        """
        if not texts:
            return

        with self._lock:
            for text in texts:
                tokens = self.tokenize(text)
                doc_len = len(tokens)

                self._sum_token_len = max(0, self._sum_token_len - doc_len)
                self._total_docs = max(0, self._total_docs - 1)

                for token in set(tokens):
                    if token not in self._doc_freq:
                        continue
                    self._doc_freq[token] -= 1
                    if self._doc_freq[token] <= 0:
                        del self._doc_freq[token]

            self._recompute_avg_len()
            self._persist_unlocked()

    # ==================== 【密集向量\语义向量的生成方法】 ====================
    def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """批量生成语义向量（密集）"""
        if not texts:
            return []
        try:
            return self._get_embedder().embed_documents(texts)
        except Exception as e:
            raise Exception(f"向量模型调用失败: {str(e)}") from e

    # ==================== 【核心分词】中英文 ====================
    def tokenize(self, text: str) -> list[str]:
        """
        分词规则：
          中文：一个字一个token
          英文：一个单词一个token
          符号、数字、空格全部丢弃
        """
        text = text.lower()  # 英文统一小写
        tokens = []

        # 正则：匹配中文
        chinese_pattern = re.compile(r"[\u4e00-\u9fff]")
        # 正则：匹配英文单词
        english_pattern = re.compile(r"[a-zA-Z]+")

        i = 0
        while i < len(text):
            char = text[i]

            # 中文：单字成词
            if chinese_pattern.match(char):
                tokens.append(char)
                i += 1

            # 英文：整个单词成词
            elif english_pattern.match(char):
                match = english_pattern.match(text[i:])
                if match:
                    word = match.group()
                    tokens.append(word)
                    i += len(word)

            # 其他字符（数字、符号、空格）直接跳过
            else:
                i += 1

        return tokens

    # ==================== 【BM25 核心】生成稀疏向量 ====================
    def _sparse_vector_for_text_unlocked(self, text: str) -> tuple[dict, bool]:
        """
        内部方法：生成 BM25 稀疏向量
        返回：(向量字典, 是否有新词)
        """
        # 1. 分词
        tokens = self.tokenize(text)
        doc_len = len(tokens)

        # 2. 词频 TF
        tf = Counter(tokens)

        sparse_vector: dict[int, float] = {}
        vocab_changed = False

        n = self._total_docs
        avg = self._avg_doc_len

        # 3. 逐个词计算 BM25 分数
        for token, freq in tf.items():
            # 新词自动加入词表
            if token not in self._vocab:
                self._vocab[token] = self._vocab_counter
                self._vocab_counter += 1
                vocab_changed = True

            idx = self._vocab[token]
            df = self._doc_freq.get(token, 0)

            # ==================== BM25 IDF 公式 ====================
            if df == 0:
                idf = math.log((n + 1) / 1)
            else:
                idf = math.log((n - df + 0.5) / (df + 0.5) + 1)

            # ==================== BM25 TF 公式 ====================
            numerator = freq * (self.k1 + 1)
            denominator = freq + self.k1 * (1 - self.b + self.b * doc_len / avg)
            score = idf * numerator / denominator

            if score > 0:
                sparse_vector[idx] = score

        return sparse_vector, vocab_changed

    # ==================== 对外接口：生成稀疏向量 ====================
    def get_sparse_embedding(self, text: str) -> dict:
        """单句稀疏向量（带锁安全调用）"""
        # # 加锁：同一时间只有一个线程能进来
        with self._lock:
            # 调用内部函数，生成向量 + 是否有新词
            vec, changed = self._sparse_vector_for_text_unlocked(text)
            if changed:
                # 如果有新词 → 立刻保存词表
                self._persist_unlocked()
        return vec

    def get_sparse_embeddings(self, texts: list[str]) -> list[dict]:
        """批量稀疏向量"""
        if not texts:
            return []
        with self._lock:
            out = []
            any_new = False
            for t in texts:
                vec, changed = self._sparse_vector_for_text_unlocked(t)
                out.append(vec)
                any_new = any_new or changed
            if any_new:
                self._persist_unlocked()
        return out

    # ==================== 对外接口：同时获取密集+稀疏向量 ====================
    def get_all_embeddings(self, texts: list[str]) -> tuple[list[list[float]], list[dict]]:
        dense = self.get_embeddings(texts)
        sparse = self.get_sparse_embeddings(texts)
        return dense, sparse


# ==================== 全局唯一实例（整个项目共用一个） ====================
embedding_service = EmbeddingService()
