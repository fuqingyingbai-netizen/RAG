# FastAPI 基础面试问答

这份文档按“面试官提问 + 候选人回答”的形式整理，重点覆盖 FastAPI 基础概念、常见接口写法、异常处理、依赖注入，以及如何结合你的 RAG 项目来回答。

参考资料：

- FastAPI Features: https://fastapi.tiangolo.com/features/
- FastAPI Request Body: https://fastapi.tiangolo.com/tutorial/body/
- FastAPI Request Files: https://fastapi.tiangolo.com/tutorial/request-files/
- FastAPI Custom Response: https://fastapi.tiangolo.com/advanced/custom-response/
- FastAPI Dependencies: https://fastapi.tiangolo.com/tutorial/dependencies/

---

## 1. FastAPI 和 Flask 有什么区别？

### 面试官提问

FastAPI 和 Flask 有什么区别？你为什么会在项目里选择 FastAPI？

### 候选人回答

FastAPI 和 Flask 都是 Python Web 框架，但定位和设计风格不太一样。

Flask 更轻量、更灵活，核心非常小，很多能力需要自己通过扩展组合，比如参数校验、API 文档、异步支持、数据模型校验等。它的优点是简单、生态成熟、自由度高，适合小型服务或对框架控制粒度要求很高的项目。

FastAPI 更偏现代 API 开发，天然支持：

- Python 类型注解
- Pydantic 数据校验
- 自动生成 OpenAPI 文档
- 异步接口 `async def`
- 依赖注入 `Depends`
- 更方便的请求参数解析和响应模型定义

如果做 AI 应用后端，FastAPI 通常会更顺手。因为 AI 应用经常需要：

- 定义结构化请求体
- 做参数校验
- 调用外部模型服务
- 做流式响应
- 接收文件上传
- 做用户认证和权限控制

这些能力 FastAPI 都支持得比较自然。

结合我的 RAG 项目来说，我选择 FastAPI 是因为项目里有聊天接口、流式输出、文档上传、JWT 鉴权、管理员权限校验，这些场景和 FastAPI 的能力比较匹配。比如项目里的 `/chat/stream` 用 `StreamingResponse` 返回 SSE 流，文档上传接口用 `UploadFile` 接收文件，认证和权限控制则通过 `Depends(get_current_user)` 和 `Depends(require_admin)` 实现。

### 一句话总结

Flask 更像轻量自由的 Web 框架，FastAPI 更像面向现代 API 服务的工程化框架；在需要类型校验、自动文档、异步调用和依赖注入的 AI 应用里，FastAPI 更合适。

---

## 2. FastAPI 为什么性能比较好？

### 面试官提问

FastAPI 为什么性能比较好？

### 候选人回答

FastAPI 性能较好，主要有几方面原因。

第一，FastAPI 底层基于 Starlette。Starlette 是一个高性能的 ASGI 框架，天然支持异步请求处理。ASGI 相比传统 WSGI，更适合处理长连接、WebSocket、流式响应和高并发 I/O 场景。

第二，FastAPI 支持 `async def`。对于 AI 应用里常见的 I/O 密集型操作，比如调用模型 API、访问数据库、请求外部服务、读取文件等，异步可以避免线程被阻塞，从而提升并发能力。

第三，FastAPI 的数据校验基于 Pydantic。Pydantic 在类型解析和数据校验上比较高效，而且能把校验逻辑和类型注解结合起来，减少很多手写解析代码。

不过我不会简单说“FastAPI 一定比 Flask 快”。实际性能还取决于：

- 是否正确使用异步
- 数据库访问是否阻塞
- 模型调用耗时
- 部署方式
- worker 数量
- 是否存在 CPU 密集型任务

在我的 RAG 项目里，FastAPI 的优势主要体现在流式聊天和文件上传这些场景。比如 `/chat/stream` 可以一边等待 Agent 输出，一边把 token 和 RAG trace 推给前端，而不是等整个回答生成完再一次性返回。

### 一句话总结

FastAPI 性能好，核心原因是 ASGI + Starlette + 异步支持，但真正的线上性能还要看 I/O、数据库、模型调用和部署方式。

---

## 3. Pydantic 在 FastAPI 中起什么作用？

### 面试官提问

Pydantic 在 FastAPI 中起什么作用？

### 候选人回答

Pydantic 在 FastAPI 中主要承担三类工作：数据校验、数据解析和接口文档生成。

第一，数据校验。  
当客户端传入 JSON body 时，FastAPI 会根据 Pydantic 模型检查字段是否存在、类型是否正确、是否满足约束。如果参数非法，FastAPI 会自动返回 `422` 错误。

第二，数据解析。  
比如客户端传入的是 JSON 字符串，Pydantic 可以把它解析成 Python 对象。日期、数字、布尔值、嵌套对象等都可以被转换和校验。

第三，生成 OpenAPI 文档。  
FastAPI 会根据 Pydantic 模型生成接口文档，前端或调用方可以在 `/docs` 里看到请求体结构和字段类型。

举个例子：

```python
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str | None = None
```

然后接口可以这样写：

```python
from fastapi import FastAPI


app = FastAPI()


@app.post("/chat")
async def chat(req: ChatRequest):
    return {"message": req.message, "session_id": req.session_id}
```

结合你的项目，`backend/schemas.py` 里定义了登录、注册、聊天、RAG trace 等模型。这样 API 层不用手动从 dict 里取字段，也不用到处写类型判断，接口更清晰。

### 一句话总结

Pydantic 是 FastAPI 的数据模型和校验层，它让请求参数、响应结构、接口文档都可以围绕 Python 类型注解自动工作。

---

## 4. GET、POST、PUT、DELETE 分别适合什么场景？

### 面试官提问

GET、POST、PUT、DELETE 分别适合什么场景？

### 候选人回答

这四个 HTTP 方法表达的是不同的资源操作语义。

`GET` 适合查询资源。  
比如获取会话列表、获取文档列表、获取某个用户信息。GET 一般不应该修改服务端状态。

`POST` 适合创建资源或提交操作。  
比如注册用户、登录、发送聊天消息、上传文件。POST 的语义比较灵活，常用于“提交一件事让服务端处理”。

`PUT` 适合整体更新资源。  
比如把某个用户配置整体替换成新的配置。PUT 通常强调幂等，也就是同样请求执行多次结果一致。

`DELETE` 适合删除资源。  
比如删除会话、删除文档。

结合你的项目可以这样对应：

- `POST /auth/register`: 注册用户，适合 POST。
- `POST /auth/login`: 登录并获取 token，适合 POST。
- `GET /sessions`: 获取会话列表，适合 GET。
- `DELETE /sessions/{session_id}`: 删除会话，适合 DELETE。
- `POST /documents/upload`: 上传文档并触发入库，适合 POST。
- `DELETE /documents/{filename}`: 删除文档，适合 DELETE。

### 一句话总结

GET 查，POST 建或提交，PUT 整体更新，DELETE 删除。面试时重点不是死背，而是能说清楚资源语义和幂等性。

---

## 5. FastAPI 中如何接收 query 参数、path 参数、body 参数？

### 面试官提问

FastAPI 中如何接收 query 参数、path 参数、body 参数？

### 候选人回答

FastAPI 会根据函数签名和路由路径自动判断参数来源。

如果参数名出现在路径中，比如 `/users/{user_id}`，那它就是 path 参数。

```python
from fastapi import FastAPI


app = FastAPI()


@app.get("/users/{user_id}")
async def get_user(user_id: int):
    return {"user_id": user_id}
```

如果参数没有出现在路径中，并且是简单类型，比如 `str`、`int`、`bool`，默认会被当成 query 参数。

```python
@app.get("/documents")
async def list_documents(keyword: str | None = None, page: int = 1):
    return {"keyword": keyword, "page": page}
```

调用方式是：

```text
GET /documents?keyword=rag&page=1
```

如果参数是 Pydantic 模型，通常会被当成 body 参数。

```python
from pydantic import BaseModel


class CreateUserRequest(BaseModel):
    username: str
    password: str


@app.post("/users")
async def create_user(req: CreateUserRequest):
    return {"username": req.username}
```

如果要加更细的校验，可以用 `Query`、`Path`、`Body`：

```python
from fastapi import Body, Path, Query


@app.put("/items/{item_id}")
async def update_item(
    item_id: int = Path(..., ge=1),
    q: str | None = Query(default=None, max_length=50),
    payload: dict = Body(...),
):
    return {"item_id": item_id, "q": q, "payload": payload}
```

结合你的项目，`session_id` 这种出现在 URL 路径里的就是 path 参数；`ChatRequest` 这种 Pydantic 模型是 body 参数；如果以后文档列表支持按文件名搜索，可以加 query 参数。

### 一句话总结

路径里声明的是 path 参数，简单类型默认是 query 参数，Pydantic 模型通常是 body 参数。

---

## 6. 如何实现文件上传？

### 面试官提问

FastAPI 如何实现文件上传？

### 候选人回答

FastAPI 中通常用 `UploadFile` 和 `File` 实现文件上传。

`UploadFile` 比直接用 `bytes` 更适合大文件，因为它内部是类文件对象，可以分块读取，不需要一次性把整个文件放进内存。

简单示例：

```python
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile


app = FastAPI()
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".pdf", ".docx", ".xlsx"}:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    save_name = f"{uuid4().hex}{suffix}"
    save_path = UPLOAD_DIR / save_name

    with save_path.open("wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)

    await file.close()
    return {"filename": file.filename, "saved_as": save_name}
```

文件上传时要注意：

- 限制文件类型。
- 限制文件大小。
- 不要直接信任用户上传的文件名。
- 保存路径要限制在安全目录内。
- 上传后如果要解析文档，最好捕获解析异常。

结合你的项目，`backend/api.py` 里文档上传接口就是 `UploadFile = File(...)`，并限制了 PDF、Word、Excel 三类文件。上传成功后会继续触发文档解析、三层分块、embedding、写入 Milvus 和 BM25 统计更新。

### 一句话总结

FastAPI 文件上传用 `UploadFile + File`，工程上要注意类型校验、路径安全、分块写入和异常处理。

---

## 7. 如何返回文件、图片或流式响应？

### 面试官提问

FastAPI 如何返回文件、图片或流式响应？

### 候选人回答

FastAPI 可以通过不同的 Response 类型返回不同内容。

返回普通文件可以用 `FileResponse`：

```python
from fastapi.responses import FileResponse


@app.get("/files/{filename}")
async def get_file(filename: str):
    path = f"uploads/{filename}"
    return FileResponse(path, filename=filename)
```

返回图片本质上也是返回文件，只是设置正确的 `media_type`：

```python
from fastapi.responses import FileResponse


@app.get("/images/{name}")
async def get_image(name: str):
    return FileResponse(f"images/{name}", media_type="image/png")
```

返回流式响应可以用 `StreamingResponse`：

```python
import asyncio
from fastapi.responses import StreamingResponse


async def token_stream():
    for token in ["hello", " ", "world"]:
        yield token
        await asyncio.sleep(0.1)


@app.get("/stream")
async def stream():
    return StreamingResponse(token_stream(), media_type="text/plain")
```

如果是 SSE，通常返回格式是：

```python
import json
from fastapi.responses import StreamingResponse


async def sse_stream():
    for i in range(3):
        yield f"data: {json.dumps({'index': i})}\n\n"


@app.get("/events")
async def events():
    return StreamingResponse(sse_stream(), media_type="text/event-stream")
```

结合你的项目，`/chat/stream` 使用 `StreamingResponse` 返回 `text/event-stream`。这样前端能边接收模型输出，边显示回答内容、RAG 检索步骤和最终 trace。

### 一句话总结

文件和图片用 `FileResponse`，大模型 token、日志、SSE 这类持续输出用 `StreamingResponse`。

---

## 8. 如何定义统一响应格式？

### 面试官提问

FastAPI 如何定义统一响应格式？

### 候选人回答

统一响应格式一般是为了让前端处理更简单，也让接口风格更一致。常见格式是：

```json
{
  "code": 0,
  "message": "ok",
  "data": {}
}
```

可以用 Pydantic 泛型模型来定义：

```python
from typing import Generic, TypeVar

from pydantic import BaseModel
from pydantic.generics import GenericModel


T = TypeVar("T")


class ApiResponse(GenericModel, Generic[T]):
    code: int = 0
    message: str = "ok"
    data: T | None = None
```

使用时：

```python
class UserOut(BaseModel):
    id: int
    username: str


@app.get("/users/{user_id}", response_model=ApiResponse[UserOut])
async def get_user(user_id: int):
    user = UserOut(id=user_id, username="alice")
    return ApiResponse(data=user)
```

也可以写辅助函数：

```python
def success(data=None, message: str = "ok"):
    return {"code": 0, "message": message, "data": data}
```

但是要注意，流式响应不一定适合统一包一层 JSON。比如 SSE 是持续输出多个事件，如果强行套统一响应格式，反而会破坏流式协议。  
所以我的理解是：普通 REST 接口适合统一响应格式，流式接口要按流式协议单独设计。

结合你的项目，登录、注册、文档列表等接口可以统一响应；但 `/chat/stream` 这种 SSE 流接口应该保持 `data: {...}\n\n` 的事件格式。

### 一句话总结

统一响应格式适合普通 JSON API，但流式响应、文件下载这类接口要按内容类型单独处理。

---

## 9. 如何处理异常？比如模型推理失败、文件不存在、参数非法。

### 面试官提问

FastAPI 如何处理异常？比如模型推理失败、文件不存在、参数非法。

### 候选人回答

FastAPI 中常见异常处理有三种方式。

第一种是直接抛出 `HTTPException`。  
这是最常用的方式，适合业务错误，比如参数非法、资源不存在、权限不足。

```python
from fastapi import HTTPException


@app.get("/documents/{doc_id}")
async def get_document(doc_id: str):
    doc = None
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc
```

第二种是使用全局异常处理器。  
适合统一处理自定义业务异常。

```python
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


app = FastAPI()


class ModelInferenceError(Exception):
    def __init__(self, message: str):
        self.message = message


@app.exception_handler(ModelInferenceError)
async def model_error_handler(request: Request, exc: ModelInferenceError):
    return JSONResponse(
        status_code=502,
        content={"code": 502, "message": exc.message, "data": None},
    )
```

第三种是依赖 Pydantic 自动参数校验。  
比如请求体字段类型不对、必填字段缺失，FastAPI 会自动返回 `422`。

不同错误可以对应不同状态码：

- 参数非法：`400` 或 `422`
- 未登录：`401`
- 无权限：`403`
- 文件不存在：`404`
- 模型服务超时：`504`
- 模型服务失败：`502`
- 服务内部异常：`500`

结合你的项目：

- 登录失败用 `401`
- 用户名重复用 `409`
- 会话不存在用 `404`
- 文档类型不支持用 `400`
- 非管理员访问文档管理接口用 `403`
- 文档处理失败用 `500`
- 模型或 Agent 调用失败时，可以根据错误类型返回 `500` 或 `502`

### 一句话总结

业务错误用 `HTTPException`，统一错误风格可以用全局异常处理器，参数类型错误交给 Pydantic 自动校验。

---

## 10. FastAPI 的依赖注入 Depends 用过吗？具体用在哪里？

### 面试官提问

FastAPI 的依赖注入 `Depends` 用过吗？具体用在哪里？

### 候选人回答

用过。`Depends` 是 FastAPI 里非常重要的依赖注入机制，可以把一些通用逻辑抽成依赖函数，然后在接口中复用。

常见使用场景有：

- 获取数据库 session
- 获取当前登录用户
- 校验权限
- 解析公共 query 参数
- 注入配置或服务对象

简单例子：

```python
from fastapi import Depends, FastAPI


app = FastAPI()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/users")
async def list_users(db=Depends(get_db)):
    return db.query(User).all()
```

认证场景：

```python
from fastapi import Depends, HTTPException, status


def get_current_user(token: str = Depends(oauth2_scheme)):
    user = decode_token(token)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return user


@app.get("/me")
async def me(current_user=Depends(get_current_user)):
    return current_user
```

权限场景：

```python
def require_admin(current_user=Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin required")
    return current_user


@app.post("/documents/upload")
async def upload_document(current_user=Depends(require_admin)):
    return {"ok": True}
```

结合你的项目，这一点非常典型：

- `Depends(get_db)` 用来注入数据库连接。
- `Depends(get_current_user)` 用来解析 JWT 并获取当前用户。
- `Depends(require_admin)` 用来限制文档上传、删除、列表这些管理接口。

所以我对 `Depends` 的理解是：它不是简单传参，而是把认证、权限、数据库连接这类横切逻辑从业务接口里抽离出来，让接口函数更专注于业务本身。

### 一句话总结

`Depends` 是 FastAPI 的依赖注入机制，我在项目中主要用它做数据库 session 注入、JWT 用户认证和管理员权限控制。

---

## 面试总结版

如果面试官连续问 FastAPI 基础，我可以这样整体回答：

FastAPI 是一个基于 Starlette 和 Pydantic 的现代 Python API 框架。它相比 Flask 更强调类型注解、自动校验、自动文档、异步支持和依赖注入。Pydantic 负责请求体和响应数据的结构定义与校验，`Depends` 用来抽离数据库、认证、权限等公共逻辑。GET、POST、PUT、DELETE 分别对应查询、创建或提交、整体更新和删除。参数方面，路径里的变量是 path 参数，简单类型默认是 query 参数，Pydantic 模型通常是 body 参数。文件上传用 `UploadFile + File`，文件返回用 `FileResponse`，流式输出用 `StreamingResponse`。异常处理上，业务错误通常用 `HTTPException`，模型调用失败、文件不存在、参数非法等要映射到合适的 HTTP 状态码。

结合我的 RAG 项目，FastAPI 主要承担 API 层职责，包括用户注册登录、JWT 鉴权、会话管理、文档上传删除、聊天接口和 SSE 流式输出。其中 `Depends(get_current_user)` 和 `Depends(require_admin)` 保证了普通用户和管理员权限隔离，`UploadFile` 支撑文档上传入库，`StreamingResponse` 支撑模型回答和 RAG trace 的实时返回。
