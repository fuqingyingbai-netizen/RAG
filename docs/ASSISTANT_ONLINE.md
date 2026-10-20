# 小助手按需联网

小助手沿用后端 `MODEL`、`BASE_URL`、`ARK_API_KEY` 模型配置。本机配置为 `qwen-plus`，不将服务商密钥发送到浏览器。

登录后所有页面均显示小助手，跨页面保留同一账号的对话。“当前页面帮助”会携带当前页面标识，覆盖个人首页、任务相关页面、溯源库、公司知识库和管理员账号管理。后端根据实际登录角色生成页面入口及操作说明，前端同时过滤管理员入口；小助手提供操作指引，具体资料问答仍在公司知识库中进行。

## 调用流程

系统操作问题优先由维护的使用说明直接回答；复杂问法可通过本地 `search_system_guide` 查询详细步骤，完整目录见 [系统使用指南](SYSTEM_USER_GUIDE.md)。识别为系统使用的问题不会绑定或执行公开网络工具。其他问题交给模型，模型可通过 Function Calling 选择 `get_weather` 或 `search_web`，普通闲聊和写作不执行网络工具。

天气缺少城市时先询问，可承接最近对话里明确提供的城市；不根据服务器 IP 或账号角色猜位置。天气复用原项目 wttr.in JSON 协议，支持当前服务返回值和最多三天预报。简单天气问题直接格式化服务字段，避免模型改写温度、观测时间或时区。服务只返回时分时，会明确说明观测日期和时区缺失；不能把查询时间当作观测时间。

网页搜索使用轻量摘要，不抓整页，不下载图片。每次只请求一家服务，独立于研究工作流的多引擎模式：

```env
# 默认有 Tavily 密钥时选 Tavily，否则选 Serper。
ASSISTANT_SEARCH_PROVIDER=tavily
TAVILY_API_KEY=your_existing_key
# 也可显式选择 serper，复用 SERPER_API_KEY。
```

要求官方或指定网站的信息可使用 `include_domains`；后端校验域名并再次过滤返回链接。来源仍需用户核对：搜索摘要、发布日期和网站的自述不等同于完整原文或独立验证。

## 边界与错误处理

- 单轮最多两次不同工具请求，重复请求复用本轮结果，模型最多执行三轮。HTTP 请求有连接和读取超时，SSE 有总等待时间及心跳，浏览器断开后不继续启动后续工具。
- 普通聊天不执行联网查询。工具执行状态、来源、发布日期/观测时间和北京时间查询时间通过 SSE 展示；缺少日期不会自动补成今天。
- 来源 URL 只接受无内嵌凭据的 HTTP(S) 链接。来源标题按文本展示，聊天 Markdown 延续 HTML 过滤。
- 搜索只发送本次需要的公开关键词；不查询项目资料，不把页面说明、角色或完整历史发给搜索服务。
- 工具结果是待分析的数据，不能作为系统指令。天气或搜索失败时说明失败，不编造实时事实，不把“接口不可用”解释为“没有记录”。
- 联网结果用于当前回答；答案和引用保存到当前账号的小助手聊天历史，不写入研究溯源库、对象存储或公司知识库。账号记忆、上下文压缩和清空规则见 [小助手记忆说明](ASSISTANT_MEMORY.md)。

## 验证与学习入口

`backend/assistant_online.py`：工具参数校验、单服务搜索、天气和来源格式。
`backend/system_guide.py`：模型工具绑定、工具调用循环、次数限制和本轮去重。
`backend/research_api.py`：后台调用、SSE 状态/来源事件、心跳和断开处理。
`frontend/index.html` 与 `frontend/script.js`：来源卡片、链接过滤及聊天历史。

针对性回归运行：

```powershell
$env:PYTHONPATH='backend'
E:\projects\RAG\.venv\Scripts\python.exe -m pytest test/test_assistant_online.py test/test_guide_and_report_archive.py -q
node --test test/system-guide-ui.test.cjs
```

接口参考：[wttr.in JSON 文档](https://github.com/chubin/wttr.in/blob/master/README.md#json-output)、[Tavily Search](https://docs.tavily.com/documentation/api-reference/endpoint/search)。
