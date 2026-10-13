"""
文档加载和分片服务
功能：支持PDF/Word/Excel文档加载，自动进行三层级文本分片，生成带层级关系的chunk数据
适用于RAG知识库预处理、向量库入库前的文档处理
"""

# os：Python自带的文件/文件夹操作工具
import os

# 类型注解语法：告诉编辑器变量是什么类型（List=列表，Dict=字典）
# 小白知识点：这不是运行必须的，只是让代码更清晰、不容易报错
from typing import Dict, List

# LangChain 文本分片工具：按段落、句子、空格把长文本切成小段
from langchain_text_splitters import RecursiveCharacterTextSplitter

# 文档加载器：分别用来读 PDF、Word、Excel 文件的工具
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, UnstructuredExcelLoader


# 【类】class = 把一堆功能打包成一个工具箱
# 这个类专门做：读文件 + 切文本
class DocumentLoader:
    """
    文档加载与三层级文本分片工具类
    核心能力：
        1. 自动识别并加载 PDF / Word / Excel 文档
        2. 对文档内容进行三层递归分片（大→中→小）
        3. 生成带父子关系、层级、页码、文件名的结构化chunk
    """

    # 【构造方法】创建这个工具箱时，自动运行的初始化方法
    # self 必须写在第一个参数：代表自己这个工具箱
    # chunk_size / chunk_overlap：外部传入的分片大小、重叠大小
    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        """
        初始化分片器（三层滑动窗口分块策略）
        :param chunk_size: 基础分块大小（外部兼容参数，内部会自动放大为三层）
        :param chunk_overlap: 基础重叠大小（外部兼容参数）
        """

        # -------------------------- 知识点：max() 语法 --------------------------
        # max(a, b) → 取两个数里更大的那个
        # 作用：保证分片大小不会太小，更稳定
        # -----------------------------------------------------------------------

        # 第一层：大段落块（保证上下文完整）
        level_1_size = max(1200, chunk_size * 2)
        level_1_overlap = max(240, chunk_overlap * 2)

        # 第二层：中等块
        level_2_size = max(600, chunk_size)
        level_2_overlap = max(120, chunk_overlap)

        # 第三层：小精块（检索更精准）
        level_3_size = max(300, chunk_size // 2)
        level_3_overlap = max(60, chunk_overlap // 2)

        # -------------------------- 知识点：创建3个分片工具 --------------------------
        # RecursiveCharacterTextSplitter：LangChain 最常用的文本切块工具
        # separators：按优先级切割 → 段落 → 换行 → 中文句子 → 逗号 → 空格 → 单字
        # 中文必须这样写，才能保证语义不被乱切
        # ---------------------------------------------------------------------------
        self._splitter_level_1 = RecursiveCharacterTextSplitter(
            chunk_size=level_1_size,
            chunk_overlap=level_1_overlap,
            add_start_index=True,  # 记录切块开始位置
            separators=["\n\n", "\n", "。", "！", "？", "，", "、", " ", ""],
        )
        self._splitter_level_2 = RecursiveCharacterTextSplitter(
            chunk_size=level_2_size,
            chunk_overlap=level_2_overlap,
            add_start_index=True,
            separators=["\n\n", "\n", "。", "！", "？", "，", "、", " ", ""],
        )
        self._splitter_level_3 = RecursiveCharacterTextSplitter(
            chunk_size=level_3_size,
            chunk_overlap=level_3_overlap,
            add_start_index=True,
            separators=["\n\n", "\n", "。", "！", "？", "，", "、", " ", ""],
        )

    # -------------------------- 知识点：@staticmethod --------------------------
    # 静态方法：不需要实例就能用，纯工具函数，不访问类里的变量
    # 作用：生成唯一ID，避免重复
    # ---------------------------------------------------------------------------
    @staticmethod
    def _build_chunk_id(filename: str, page_number: int, level: int, index: int) -> str:
        """
        静态工具方法：生成唯一的chunk ID
        格式：文件名::p页码::l层级::索引
        示例：报告.pdf::p2::l1::0
        """
        # f-string 语法：把变量拼进字符串里
        return f"{filename}::p{page_number}::l{level}::{index}"

    # -------------------------- 核心方法 --------------------------
    # 把一页文本切成 1→2→3 三级结构
    # 每一级都记录：父块ID、层级、序号
    # ----------------------------------------------------------------
    def _split_page_to_three_levels(
        self,
        text: str,            # 要切的文本
        base_doc: Dict,       # 基础信息（文件名、页码...）
        page_global_chunk_idx: int,  # 全局唯一序号
    ) -> List[Dict]:
        """
        【核心方法】对单页文本进行三层级分片
        分片逻辑：
            1 → 2 → 3 逐级拆分
            每一层都记录父子关系、层级、唯一ID、全局索引
        :param text: 当前页文本内容
        :param base_doc: 基础元数据（文件名、路径、页码等）
        :param page_global_chunk_idx: 全局chunk自增ID
        :return: 包含三层所有chunk的列表
        """
        # 如果是空文本，直接返回空列表
        if not text:
            return []

        # 准备一个空列表，用来装所有切好的块
        root_chunks: List[Dict] = []

        # 从基础信息里拿出：页码、文件名
        page_number = int(base_doc.get("page_number", 0))
        filename = base_doc["filename"]

        # -------------------- 第一层分片（最大块）--------------------
        level_1_docs = self._splitter_level_1.create_documents([text], [base_doc])

        # 计数器：每一层内部编号
        level_1_counter = 0
        level_2_counter = 0
        level_3_counter = 0

        # 遍历第一层切好的块
        for level_1_doc in level_1_docs:
            # 去掉文本前后空白字符
            level_1_text = (level_1_doc.page_content or "").strip()

            # 如果文本为空，跳过
            if not level_1_text:
                continue

            # 生成唯一ID
            level_1_id = self._build_chunk_id(filename, page_number, 1, level_1_counter)
            level_1_counter += 1

            # -------------------- 知识点：**base_doc --------------------
            # 字典解包：把 base_doc 里的所有键值对直接放进新字典
            # 小白理解：快速复制基础信息，不用一个个手写
            # -----------------------------------------------------------
            level_1_chunk = {
                **base_doc,
                "text": level_1_text,           # 切块内容
                "chunk_id": level_1_id,         # 唯一ID
                "parent_chunk_id": "",          # 第一层没有爸爸
                "root_chunk_id": level_1_id,    # 根ID = 自己
                "chunk_level": 1,               # 层级
                "chunk_idx": page_global_chunk_idx,  # 全局序号
            }
            page_global_chunk_idx += 1  # 全局序号+1
            root_chunks.append(level_1_chunk)  # 放进结果列表

            # -------------------- 第二层分片（从第一层里切） --------------------
            level_2_docs = self._splitter_level_2.create_documents([level_1_text], [base_doc])
            for level_2_doc in level_2_docs:
                level_2_text = (level_2_doc.page_content or "").strip()
                if not level_2_text:
                    continue

                level_2_id = self._build_chunk_id(filename, page_number, 2, level_2_counter)
                level_2_counter += 1

                level_2_chunk = {
                    **base_doc,
                    "text": level_2_text,
                    "chunk_id": level_2_id,
                    "parent_chunk_id": level_1_id,    # 爸爸是第一层
                    "root_chunk_id": level_1_id,      # 根还是第一层
                    "chunk_level": 2,
                    "chunk_idx": page_global_chunk_idx,
                }
                page_global_chunk_idx += 1
                root_chunks.append(level_2_chunk)

                # -------------------- 第三层分片（从第二层里切） --------------------
                level_3_docs = self._splitter_level_3.create_documents([level_2_text], [base_doc])
                for level_3_doc in level_3_docs:
                    level_3_text = (level_3_doc.page_content or "").strip()
                    if not level_3_text:
                        continue

                    level_3_id = self._build_chunk_id(filename, page_number, 3, level_3_counter)
                    level_3_counter += 1

                    root_chunks.append({
                        **base_doc,
                        "text": level_3_text,
                        "chunk_id": level_3_id,
                        "parent_chunk_id": level_2_id,   # 爸爸是第二层
                        "root_chunk_id": level_1_id,     # 根永远是第一层
                        "chunk_level": 3,
                        "chunk_idx": page_global_chunk_idx,
                    })
                    page_global_chunk_idx += 1

        # 返回这一页切好的所有三层块
        return root_chunks

    # -------------------- 加载单个文件（PDF/Word/Excel） --------------------
    def load_document(self, file_path: str, filename: str) -> list[dict]:
        """
        加载单个文档并完成三层分片
        支持：PDF / Word(docx) / Excel(xlsx)
        :param file_path: 文件完整路径
        :param filename: 文件名（用于元数据）
        :return: 所有分片后的结构化chunk列表
        """
        # 转小写，避免 .PDF 和 .pdf 识别失败
        file_lower = filename.lower()

        # 根据后缀名选择不同的读取工具
        if file_lower.endswith(".pdf"):
            doc_type = "PDF"
            loader = PyPDFLoader(file_path)
        elif file_lower.endswith((".docx", ".doc")):
            doc_type = "Word"
            loader = Docx2txtLoader(file_path)
        elif file_lower.endswith((".xlsx", ".xls")):
            doc_type = "Excel"
            loader = UnstructuredExcelLoader(file_path)
        else:
            # 主动抛出错误，告诉用户不支持这种文件
            raise ValueError(f"不支持的文件类型: {filename}")

        try:
            # 加载文件内容
            raw_docs = loader.load()
            documents = []
            page_global_chunk_idx = 0

            # 遍历文件每一页
            for doc in raw_docs:
                # 基础信息字典
                base_doc = {
                    "filename": filename,
                    "file_path": file_path,
                    "file_type": doc_type,
                    "page_number": doc.metadata.get("page", 0),
                }

                # 调用上面的核心方法，切成三级块
                page_chunks = self._split_page_to_three_levels(
                    text=(doc.page_content or "").strip(),
                    base_doc=base_doc,
                    page_global_chunk_idx=page_global_chunk_idx,
                )

                # 全局序号累加
                page_global_chunk_idx += len(page_chunks)
                # 把这一页的块加入总列表
                documents.extend(page_chunks)

            # 返回整个文件切好的所有块
            return documents

        except Exception as e:
            # 出错时抛出异常，方便排查问题
            raise Exception(f"处理文档失败: {str(e)}")

    # -------------------- 批量加载整个文件夹 --------------------
    def load_documents_from_folder(self, folder_path: str) -> list[dict]:
        """
        批量加载文件夹下所有支持的文档
        自动跳过不支持格式与加载失败的文件
        :param folder_path: 文件夹路径
        :return: 所有文档的三层分片结果
        """
        all_documents = []

        # 遍历文件夹里所有文件
        for filename in os.listdir(folder_path):
            file_lower = filename.lower()

            # 只支持这三类文件，其他跳过
            if not (file_lower.endswith(".pdf") or
                    file_lower.endswith((".docx", ".doc")) or
                    file_lower.endswith((".xlsx", ".xls"))):
                continue

            # 拼接路径：文件夹 + 文件名
            file_path = os.path.join(folder_path, filename)

            try:
                # 调用单个文件加载方法
                documents = self.load_document(file_path, filename)
                all_documents.extend(documents)
            except Exception:
                # 失败了就跳过，不影响其他文件
                continue

        # 返回文件夹里所有文件切好的块
        return all_documents