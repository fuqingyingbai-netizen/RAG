"""
父级分块文档存储模块（用于 Auto-merging Retriever）
Auto-merging Retriever：一种检索增强生成（RAG）的检索器，核心是先检索小分块，再自动合并父级大分块提升上下文完整性
本模块作用：把文档分块后的「父级分块」数据存到 PostgreSQL 数据库 + Redis 缓存中，提供增/查/删操作
"""
# 导入datetime：处理时间（记录数据更新时间）
from datetime import datetime
# 导入List：指定列表类型（Python类型注解，让代码更易读）
from typing import List

# 导入自定义缓存模块（封装了Redis操作）
from cache import cache
# 导入自定义数据库模块（封装了PostgreSQL的数据库会话）
from database import SessionLocal
# 导入自定义模型（ParentChunk是数据库表对应的Python类，ORM映射）
from models import ParentChunk


class ParentChunkStore:
    """
    父级分块存储核心类
    基于 PostgreSQL（持久化存储） + Redis（缓存加速）实现：
    - PostgreSQL：长期保存所有父级分块数据，不怕重启丢失
    - Redis：缓存高频访问的分块数据，减少数据库查询，提升速度
    """

    @staticmethod
    def _to_dict(item: ParentChunk) -> dict:
        """
        私有静态方法：把数据库查询到的ParentChunk对象转成字典（方便后续返回/缓存）
        :param item: 数据库查询返回的ParentChunk实例（一行数据）
        :return: 结构化的字典，包含分块的所有核心字段
        """
        return {
            "text": item.text,          # 分块的文本内容
            "filename": item.filename,  # 所属文件名称（如：xxx.pdf）
            "file_type": item.file_type,  # 文件类型（如：pdf、txt）
            "file_path": item.file_path,  # 文件存储路径
            "page_number": item.page_number,  # 所属页码（PDF等分页文件）
            "chunk_id": item.chunk_id,  # 当前分块的唯一ID
            "parent_chunk_id": item.parent_chunk_id,  # 父分块ID（用于合并）
            "root_chunk_id": item.root_chunk_id,      # 根分块ID（最顶层父分块）
            "chunk_level": item.chunk_level,          # 分块层级（0=根，1=子，2=孙...）
            "chunk_idx": item.chunk_idx,              # 分块在同级中的序号（用于排序）
        }

    @staticmethod
    def _cache_key(chunk_id: str) -> str:
        """
        私有静态方法：生成Redis缓存的key（保证key唯一且有语义）
        :param chunk_id: 分块ID
        :return: 缓存key（格式：parent_chunk:分块ID）
        """
        return f"parent_chunk:{chunk_id}"

    def upsert_documents(self, docs: List[dict]) -> int:
        """
        核心方法：批量写入/更新父级分块（Upsert = Update + Insert）
        有则更新，无则插入，同时更新Redis缓存
        :param docs: 待写入的分块列表，每个元素是包含分块信息的字典
        :return: 成功写入/更新的条数
        """
        # 如果传入的列表为空，直接返回0（避免无效操作）
        if not docs:
            return 0

        # 获取数据库会话（连接PostgreSQL）
        db = SessionLocal()
        # 初始化成功写入的计数器
        upserted = 0
        try:
            # 遍历每个分块数据
            for doc in docs:
                # 提取并清洗分块ID（去空格、判空，避免无效ID）
                chunk_id = (doc.get("chunk_id") or "").strip()
                if not chunk_id:
                    continue  # 无有效ID则跳过当前分块

                # 第一步：查数据库是否已有该分块ID的记录
                record = db.query(ParentChunk).filter(ParentChunk.chunk_id == chunk_id).first()

                # 第二步：构造要写入数据库的字段（统一格式、类型）
                payload = {
                    "text": doc.get("text", ""),          # 文本默认空字符串
                    "filename": doc.get("filename", ""),  # 文件名默认空
                    "file_type": doc.get("file_type", ""),# 文件类型默认空
                    "file_path": doc.get("file_path", ""),# 文件路径默认空
                    "page_number": int(doc.get("page_number", 0) or 0),  # 页码转整数，默认0
                    "parent_chunk_id": doc.get("parent_chunk_id", ""),  # 父分块ID默认空
                    "root_chunk_id": doc.get("root_chunk_id", ""),      # 根分块ID默认空
                    "chunk_level": int(doc.get("chunk_level", 0) or 0),  # 层级转整数，默认0
                    "chunk_idx": int(doc.get("chunk_idx", 0) or 0),      # 序号转整数，默认0
                    "updated_at": datetime.utcnow(),      # 更新时间：当前UTC时间（统一时区）
                }

                # 第三步：构造要写入Redis缓存的字段（比数据库多chunk_id）
                cache_payload = {
                    "chunk_id": chunk_id,  # 缓存里显式存chunk_id，方便后续读取
                    **payload  # 解包上面的数据库字段（除了updated_at，缓存不需要更新时间）
                }
                # 移除缓存payload里的updated_at（Redis只存核心业务字段）
                cache_payload.pop("updated_at", None)

                # 第四步：更新/插入数据库
                if record:
                    # 已有记录：遍历字段，逐个更新
                    for key, value in payload.items():
                        setattr(record, key, value)
                else:
                    # 无记录：新建ParentChunk实例并添加到数据库会话
                    db.add(ParentChunk(chunk_id=chunk_id, **payload))

                # 第五步：更新Redis缓存（不管新增/更新，都刷新缓存）
                cache.set_json(self._cache_key(chunk_id), cache_payload)
                # 计数器+1
                upserted += 1

            # 提交数据库事务（把所有修改写入数据库）
            db.commit()
        finally:
            # 无论是否出错，最终都关闭数据库连接（避免连接泄露）
            db.close()

        # 返回成功写入/更新的条数
        return upserted

    def get_documents_by_ids(self, chunk_ids: List[str]) -> List[dict]:
        """
        核心方法：按分块ID列表批量查询父级分块
        优先查Redis缓存（快），缓存没有再查数据库，查完后更新缓存
        :param chunk_ids: 要查询的分块ID列表
        :return: 按传入ID顺序返回的分块字典列表（保证顺序一致）
        """
        # 空列表直接返回空
        if not chunk_ids:
            return []

        # 有序结果字典：保证最终返回顺序和传入的chunk_ids一致
        ordered_results = {}
        # 缓存未命中的ID：需要查数据库的ID列表
        missing_ids = []

        # 第一步：遍历ID，先查缓存
        for chunk_id in chunk_ids:
            # 清洗ID（去空格、判空）
            key = (chunk_id or "").strip()
            if not key:
                continue
            # 从Redis获取缓存（get_json：自动把Redis的字符串转字典）
            cached = cache.get_json(self._cache_key(key))
            if cached:
                # 缓存命中：存入有序结果
                ordered_results[key] = cached
            else:
                # 缓存未命中：加入缺失ID列表
                missing_ids.append(key)

        # 第二步：缓存未命中的ID，查数据库
        if missing_ids:
            db = SessionLocal()
            try:
                # 批量查询数据库（in操作：一次查多个ID，比循环查快）
                rows = db.query(ParentChunk).filter(ParentChunk.chunk_id.in_(missing_ids)).all()
                # 遍历查询结果
                for row in rows:
                    # 转成字典
                    payload = self._to_dict(row)
                    # 存入有序结果
                    ordered_results[row.chunk_id] = payload
                    # 更新缓存（下次查就不用走数据库了）
                    cache.set_json(self._cache_key(row.chunk_id), payload)
            finally:
                # 关闭数据库连接
                db.close()

        # 第三步：按传入的ID顺序，提取结果（保证顺序和输入一致）
        return [ordered_results[item] for item in chunk_ids if item in ordered_results]

    def delete_by_filename(self, filename: str) -> int:
        """
        核心方法：按文件名删除所有对应的父级分块
        同时删除数据库记录和Redis缓存
        :param filename: 要删除的文件名（如：xxx.pdf）
        :return: 成功删除的条数
        """
        # 文件名空直接返回0
        if not filename:
            return 0

        db = SessionLocal()
        try:
            # 第一步：先查该文件名对应的所有分块（获取chunk_id，用于删缓存）
            rows = db.query(ParentChunk).filter(ParentChunk.filename == filename).all()
            # 提取所有chunk_id
            chunk_ids = [row.chunk_id for row in rows]
            # 要删除的条数
            deleted = len(chunk_ids)

            # 第二步：如果有要删除的记录
            if deleted > 0:
                # 批量删除数据库记录（synchronize_session=False：提升删除性能）
                db.query(ParentChunk).filter(ParentChunk.filename == filename).delete(synchronize_session=False)
                # 提交事务
                db.commit()
                # 遍历chunk_id，删除对应的Redis缓存
                for chunk_id in chunk_ids:
                    cache.delete(self._cache_key(chunk_id))

            # 返回删除条数
            return deleted
        finally:
            # 关闭数据库连接
            db.close()