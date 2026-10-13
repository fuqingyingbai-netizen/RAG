# 常见手写题面试问答

这份文档按“面试官提问 + 候选人回答”的形式整理，重点放在 Python 实现、思路解释、复杂度和容易被追问的点。  
如果面试官让你现场手写，不需要一上来写得特别花，先把边界条件和核心数据结构说清楚，再写代码会更稳。

---

## 1. 手写一个 LRU Cache

### 面试官提问

请你手写一个 LRU Cache，要求 `get` 和 `put` 的时间复杂度都是 `O(1)`。

### 候选人回答

LRU 的全称是 `Least Recently Used`，也就是“最近最少使用”。它的核心规则是：当缓存容量满了之后，优先淘汰最久没有被访问过的元素。

要做到 `get` 和 `put` 都是 `O(1)`，只用一个字典不够，因为字典虽然能快速查找 key，但不能高效维护“最近使用顺序”。常见做法是：

- 用哈希表保存 `key -> node`，保证按 key 查找是 `O(1)`。
- 用双向链表维护访问顺序，最近访问的节点放到链表头部，最久未访问的节点放到链表尾部。
- 每次 `get` 命中后，把节点移动到头部。
- 每次 `put` 新增或更新后，也把节点移动到头部。
- 容量超限时，删除尾部节点。

Python 里可以直接用 `collections.OrderedDict`，但如果面试官要求手写，最好写哈希表 + 双向链表版本。

### 参考实现

```python
class Node:
    def __init__(self, key=0, value=0):
        self.key = key
        self.value = value
        self.prev = None
        self.next = None


class LRUCache:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.cache = {}

        # 使用虚拟头尾节点，避免处理空链表和边界节点时写很多 if。
        self.head = Node()
        self.tail = Node()
        self.head.next = self.tail
        self.tail.prev = self.head

    def _remove(self, node: Node) -> None:
        prev_node = node.prev
        next_node = node.next
        prev_node.next = next_node
        next_node.prev = prev_node

    def _add_to_head(self, node: Node) -> None:
        first = self.head.next
        node.prev = self.head
        node.next = first
        self.head.next = node
        first.prev = node

    def _move_to_head(self, node: Node) -> None:
        self._remove(node)
        self._add_to_head(node)

    def _remove_tail(self) -> Node:
        node = self.tail.prev
        self._remove(node)
        return node

    def get(self, key: int) -> int:
        if key not in self.cache:
            return -1

        node = self.cache[key]
        self._move_to_head(node)
        return node.value

    def put(self, key: int, value: int) -> None:
        if key in self.cache:
            node = self.cache[key]
            node.value = value
            self._move_to_head(node)
            return

        node = Node(key, value)
        self.cache[key] = node
        self._add_to_head(node)

        if len(self.cache) > self.capacity:
            removed = self._remove_tail()
            del self.cache[removed.key]
```

### 复杂度

- `get`: `O(1)`
- `put`: `O(1)`
- 空间复杂度: `O(capacity)`

### 面试追问

如果面试官问“为什么不能只用数组”，可以回答：数组删除和移动元素需要 `O(n)`，无法满足 `O(1)`。  
如果面试官问“为什么要用双向链表”，可以回答：删除某个已知节点时需要同时修改前驱和后继，双向链表可以 `O(1)` 完成。

---

## 2. 手写 top-k 高频词

### 面试官提问

给定一个字符串列表，请返回出现频率最高的前 `k` 个词。

### 候选人回答

这个题的核心是先统计词频，再选出频率最高的 `k` 个。最直接的做法是：

- 用哈希表统计每个词出现次数。
- 用堆维护 top-k。

如果数据量不大，也可以直接排序，代码更简单。面试时我会先写容易理解的排序版本，再说明如果数据量大可以用小顶堆优化。

### 排序版本

```python
from collections import Counter


def top_k_frequent(words: list[str], k: int) -> list[str]:
    counter = Counter(words)

    # 频率降序；频率相同时按字典序升序，方便结果稳定。
    items = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return [word for word, _ in items[:k]]
```

### 小顶堆版本

```python
from collections import Counter
import heapq


def top_k_frequent_heap(words: list[str], k: int) -> list[str]:
    counter = Counter(words)

    # Python 的 heapq 是小顶堆。这里先用排序规则简单实现，实际面试通常排序版本已够清楚。
    heap = []
    for word, count in counter.items():
        heapq.heappush(heap, (count, word))
        if len(heap) > k:
            heapq.heappop(heap)

    result = sorted(heap, key=lambda item: (-item[0], item[1]))
    return [word for _, word in result]
```

### 复杂度

排序版本：

- 时间复杂度: `O(n + m log m)`，`n` 是词总数，`m` 是不同词数量。
- 空间复杂度: `O(m)`。

堆版本：

- 时间复杂度: `O(n + m log k)`。
- 空间复杂度: `O(m + k)`。

### 面试追问

如果面试官问“大数据场景怎么办”，可以说：可以用 MapReduce 或分片统计局部词频，再合并全局 top-k；单机内存有限时也可以用堆和外部排序。

---

## 3. 手写两个有序数组合并

### 面试官提问

给定两个升序数组，请合并成一个新的升序数组。

### 候选人回答

这个题使用双指针。两个指针分别指向两个数组当前未处理的最小元素，每次取较小的放入结果数组。

### 参考实现

```python
def merge_sorted_arrays(nums1: list[int], nums2: list[int]) -> list[int]:
    i = 0
    j = 0
    result = []

    while i < len(nums1) and j < len(nums2):
        if nums1[i] <= nums2[j]:
            result.append(nums1[i])
            i += 1
        else:
            result.append(nums2[j])
            j += 1

    result.extend(nums1[i:])
    result.extend(nums2[j:])
    return result
```

### 复杂度

- 时间复杂度: `O(m + n)`
- 空间复杂度: `O(m + n)`

### 面试追问

如果题目是 LeetCode 88 那种“把 `nums2` 合并到 `nums1` 里”，可以从后往前填，避免覆盖 `nums1` 中尚未处理的元素。

```python
def merge_in_place(nums1: list[int], m: int, nums2: list[int], n: int) -> None:
    i = m - 1
    j = n - 1
    write = m + n - 1

    while j >= 0:
        if i >= 0 and nums1[i] > nums2[j]:
            nums1[write] = nums1[i]
            i -= 1
        else:
            nums1[write] = nums2[j]
            j -= 1
        write -= 1
```

---

## 4. 手写字符串反转，但要求保留单词顺序

### 面试官提问

给定字符串 `"hello world"`，要求反转每个单词内部字符，但保留单词顺序，输出 `"olleh dlrow"`。

### 候选人回答

这个题的关键是理解“反转字符串”和“保留单词顺序”的区别。不是把整个句子反转，而是每个单词单独反转。

### 简单实现

```python
def reverse_words_keep_order(s: str) -> str:
    words = s.split(" ")
    reversed_words = [word[::-1] for word in words]
    return " ".join(reversed_words)
```

### 保留任意空白的实现

如果面试官要求保留多个空格、制表符等原始分隔符，可以用正则把“单词”和“非单词分隔符”分开处理。

```python
import re


def reverse_words_keep_spaces(s: str) -> str:
    parts = re.split(r"(\s+)", s)
    return "".join(part[::-1] if not part.isspace() else part for part in parts)
```

### 复杂度

- 时间复杂度: `O(n)`
- 空间复杂度: `O(n)`

### 面试追问

如果面试官问“中文怎么办”，可以说明：中文没有天然空格分词，如果是中文文本，需要依赖分词器，比如 `jieba` 或模型分词，而不是简单按空格切。

---

## 5. 手写判断括号是否合法

### 面试官提问

给定只包含 `()[]{}` 的字符串，判断括号是否合法。

### 候选人回答

括号匹配是典型栈问题。遇到左括号入栈，遇到右括号时检查栈顶是否是对应的左括号。

如果最后栈为空，说明所有括号都匹配成功。

### 参考实现

```python
def is_valid_parentheses(s: str) -> bool:
    pairs = {
        ")": "(",
        "]": "[",
        "}": "{",
    }
    stack = []

    for ch in s:
        if ch in "([{":
            stack.append(ch)
        elif ch in pairs:
            if not stack or stack[-1] != pairs[ch]:
                return False
            stack.pop()
        else:
            return False

    return not stack
```

### 复杂度

- 时间复杂度: `O(n)`
- 空间复杂度: `O(n)`

### 面试追问

如果输入可能包含普通字符，比如 `"a(b)c"`，可以选择忽略非括号字符。这个要先和面试官确认。

---

## 6. 手写一个简单的 BM25 计算函数

### 面试官提问

请手写一个简单 BM25 计算函数，输入 query 和文档集合，返回每个文档的 BM25 分数。

### 候选人回答

BM25 是经典关键词相关性算法。它主要考虑三件事：

- query 词是否出现在文档里。
- 词在当前文档中出现得多不多，也就是 TF。
- 词在整个语料里罕不罕见，也就是 IDF。
- 文档长度是否过长，需要做长度归一化。

BM25 常见公式是：

```text
score(D, Q) = Σ IDF(qi) * tf(qi, D) * (k1 + 1)
              / (tf(qi, D) + k1 * (1 - b + b * len(D) / avgdl))
```

其中：

- `tf(qi, D)` 是词 `qi` 在文档 `D` 中的词频。
- `len(D)` 是文档长度。
- `avgdl` 是平均文档长度。
- `k1` 控制词频饱和，常用 `1.2` 或 `1.5`。
- `b` 控制文档长度归一化，常用 `0.75`。

### 参考实现

```python
import math
from collections import Counter


def tokenize(text: str) -> list[str]:
    return text.lower().split()


def bm25_scores(query: str, docs: list[str], k1: float = 1.5, b: float = 0.75) -> list[float]:
    tokenized_docs = [tokenize(doc) for doc in docs]
    query_terms = tokenize(query)

    n_docs = len(docs)
    doc_lens = [len(doc) for doc in tokenized_docs]
    avgdl = sum(doc_lens) / n_docs if n_docs else 0

    doc_freq = Counter()
    for doc in tokenized_docs:
        for term in set(doc):
            doc_freq[term] += 1

    scores = []
    for doc, doc_len in zip(tokenized_docs, doc_lens):
        tf = Counter(doc)
        score = 0.0

        for term in query_terms:
            if term not in tf:
                continue

            df = doc_freq.get(term, 0)
            idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
            numerator = tf[term] * (k1 + 1)
            denominator = tf[term] + k1 * (1 - b + b * doc_len / avgdl)
            score += idf * numerator / denominator

        scores.append(score)

    return scores
```

### 示例

```python
docs = [
    "redis cache expiration strategy",
    "postgresql transaction isolation",
    "cache invalidation and redis memory",
]

print(bm25_scores("redis cache", docs))
```

### 结合项目说明

你的 RAG 项目里 BM25 不是只返回文档分数，而是进一步把每个文本编码成 `{token_id: weight}` 的稀疏向量，然后存入 Milvus 的 `SPARSE_FLOAT_VECTOR` 字段。查询时，用户问题也会生成稀疏向量，再用点积做 sparse 检索。

### 复杂度

- 建统计信息: `O(total_terms)`
- 单次 query 评分: `O(num_docs * query_terms)`

---

## 7. 手写一个余弦相似度函数

### 面试官提问

给定两个向量，请手写余弦相似度函数。

### 候选人回答

余弦相似度衡量的是两个向量方向是否接近。公式是：

```text
cosine(a, b) = dot(a, b) / (||a|| * ||b||)
```

如果两个向量方向越接近，结果越接近 1；如果方向相反，结果可能接近 -1。

### 参考实现

```python
import math


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError("Vectors must have the same dimension")

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)
```

### 结合项目说明

在你的 RAG 项目里，BGE-M3 dense embedding 使用了归一化。向量归一化后，`dot product` 和 `cosine similarity` 的排序效果基本一致，所以 Milvus 里使用 `IP` 是合理的。

### 复杂度

- 时间复杂度: `O(n)`
- 空间复杂度: `O(1)`

---

## 8. 手写一个简单的文本分块函数，支持 chunk size 和 overlap

### 面试官提问

请手写一个文本分块函数，支持 `chunk_size` 和 `overlap`。

### 候选人回答

文本分块在 RAG 中很常见。`chunk_size` 控制每个块的最大长度，`overlap` 控制相邻块之间重叠多少内容。

重叠的作用是避免重要上下文刚好被切断，比如一句话前半段在上一个块，后半段在下一个块。

### 字符级分块实现

```python
def split_text(text: str, chunk_size: int, overlap: int = 0) -> list[str]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0:
        raise ValueError("overlap cannot be negative")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start = end - overlap

    return chunks
```

### 单词级分块实现

```python
def split_words(text: str, chunk_size: int, overlap: int = 0) -> list[str]:
    words = text.split()

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0:
        raise ValueError("overlap cannot be negative")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    chunks = []
    start = 0

    while start < len(words):
        end = start + chunk_size
        chunks.append(" ".join(words[start:end]))
        start = end - overlap

    return chunks
```

### 结合项目说明

你的 RAG 项目里做得更进一步，不是简单单层分块，而是三层父子分块：

- L1: 大块，保留完整上下文。
- L2: 中块，作为中间父节点。
- L3: 小块，进入 Milvus 做精细检索。

检索命中 L3 后，再通过 parent chunk 做 auto-merging，兼顾召回精度和上下文完整性。

### 复杂度

- 时间复杂度: `O(n)`
- 空间复杂度: `O(n)`

---

## 9. 手写一个装饰器，统计函数执行时间

### 面试官提问

请手写一个 Python 装饰器，用来统计函数执行时间。

### 候选人回答

装饰器本质上是一个接收函数并返回新函数的高阶函数。统计耗时的装饰器通常在函数执行前后分别记录时间，然后计算差值。

### 参考实现

```python
import time
from functools import wraps


def timing(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            end = time.perf_counter()
            print(f"{func.__name__} took {end - start:.4f}s")

    return wrapper
```

### 使用示例

```python
@timing
def slow_add(a: int, b: int) -> int:
    time.sleep(0.1)
    return a + b


print(slow_add(1, 2))
```

### 关键点

`functools.wraps` 很重要，它可以保留原函数的函数名、文档字符串等元信息。  
`time.perf_counter()` 比 `time.time()` 更适合做性能计时。

---

## 10. 手写一个重试装饰器，失败后最多重试 3 次

### 面试官提问

请手写一个重试装饰器，函数失败后最多重试 3 次。

### 候选人回答

重试装饰器常用于调用外部服务，比如模型 API、天气 API、数据库连接等临时失败场景。核心逻辑是：

- 捕获指定异常。
- 失败后等待一小段时间。
- 最多重试固定次数。
- 如果最终仍失败，抛出最后一次异常。

### 参考实现

```python
import time
from functools import wraps


def retry(max_attempts: int = 3, delay: float = 0.5, exceptions: tuple[type[Exception], ...] = (Exception,)):
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive")

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_error = exc
                    if attempt == max_attempts:
                        break
                    time.sleep(delay)

            raise last_error

        return wrapper

    return decorator
```

### 使用示例

```python
@retry(max_attempts=3, delay=1.0, exceptions=(TimeoutError, ConnectionError))
def call_external_service():
    ...
```

### 面试追问

如果面试官问“重试会不会有风险”，可以回答：会。对于写操作，要注意幂等性，避免重复提交订单、重复扣款、重复写入数据。对于读操作或幂等接口，重试更安全。

---

## 11. 手写一个 FastAPI 接口，接收文件上传并保存

### 面试官提问

请手写一个 FastAPI 文件上传接口，把文件保存到本地。

### 候选人回答

FastAPI 中可以用 `UploadFile` 接收文件。相比直接接收 bytes，`UploadFile` 更适合大文件，因为它内部使用类文件对象，不需要一次性把所有内容读入内存。

保存文件时要注意：

- 限制上传目录。
- 避免直接信任用户传来的文件名。
- 必要时校验文件类型和大小。
- 保存时使用分块读取，避免大文件占用过多内存。

### 参考实现

```python
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile


app = FastAPI()
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    allowed_suffixes = {".pdf", ".docx", ".xlsx", ".txt"}
    original_name = file.filename or ""
    suffix = Path(original_name).suffix.lower()

    if suffix not in allowed_suffixes:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    safe_name = f"{uuid4().hex}{suffix}"
    save_path = UPLOAD_DIR / safe_name

    try:
        with save_path.open("wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
    finally:
        await file.close()

    return {
        "filename": original_name,
        "saved_as": safe_name,
        "size": save_path.stat().st_size,
    }
```

### 结合项目说明

你的 RAG 项目里文档上传后，不只是保存文件，还会继续进入解析、分块、embedding、写入 Milvus 和 BM25 统计更新流程。  
所以 FastAPI 上传接口只是入口，后面还有完整的知识库入库链路。

### 面试追问

如果面试官问“文件名为什么不能直接用用户上传的”，可以回答：用户文件名可能包含路径穿越、特殊字符或重名风险，所以通常要生成服务端安全文件名，同时把原始文件名作为 metadata 保存。

---

## 12. 手写一个异步接口，模拟调用外部模型服务

### 面试官提问

请手写一个异步接口，模拟调用外部模型服务。

### 候选人回答

在 AI 应用里，调用外部模型服务通常是 I/O 密集型任务，适合用异步接口。  
FastAPI 原生支持 `async def`，可以在接口里使用 `await` 调用异步 HTTP 客户端，比如 `httpx.AsyncClient`。

### 模拟版本

```python
import asyncio

from fastapi import FastAPI
from pydantic import BaseModel


app = FastAPI()


class ModelRequest(BaseModel):
    prompt: str


class ModelResponse(BaseModel):
    answer: str


async def fake_model_call(prompt: str) -> str:
    await asyncio.sleep(1)
    return f"模型模拟回答：{prompt}"


@app.post("/model/call", response_model=ModelResponse)
async def call_model(req: ModelRequest):
    answer = await fake_model_call(req.prompt)
    return ModelResponse(answer=answer)
```

### 真实外部 HTTP 调用版本

```python
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


app = FastAPI()


class ModelRequest(BaseModel):
    prompt: str


@app.post("/model/external")
async def call_external_model(req: ModelRequest):
    payload = {
        "prompt": req.prompt,
        "max_tokens": 512,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post("https://example.com/model-api", json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Model service timeout")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Model service error: {exc}")

    return {
        "answer": data.get("answer", ""),
    }
```

### 结合项目说明

你的项目里流式聊天和 RAG trace 都和异步编程有关。比如 `/chat/stream` 用的是 SSE 流式返回，后端要一边接收 Agent 输出，一边把 `content`、`rag_step`、`trace` 推给前端。  
所以异步接口不只是为了“写法现代”，而是为了让模型调用、流式输出、外部服务请求可以更高效地协同。

### 面试追问

如果面试官问“为什么不能在 async 接口里直接用 requests”，可以回答：`requests` 是同步阻塞库，在高并发 async 服务里会阻塞事件循环。更推荐使用 `httpx.AsyncClient` 或者把阻塞调用丢到线程池。

---

## 总结

这一组手写题覆盖了几类高频能力：

- 数据结构：`LRU Cache`、括号匹配、top-k。
- 双指针：有序数组合并。
- 字符串处理：单词内部反转。
- AI 应用基础：BM25、余弦相似度、文本分块。
- Python 工程能力：装饰器、重试机制。
- Web 后端能力：FastAPI 文件上传、异步外部服务调用。

面试时不需要死记所有代码，但一定要记住每题背后的核心思想。能把“为什么这样写”讲清楚，通常比只写出代码更重要。
