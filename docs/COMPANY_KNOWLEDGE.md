# 公司知识库接入

现有平台通过后端调用百炼已发布的知识问答服务；解析、切分、索引、检索和生成均由百炼执行，不重复写入本地 Milvus。

## 配置

在根目录 `.env` 中设置以下变量，具体值从百炼“知识问答 → 发布渠道 → API 调试”获取：

```env
BAILIAN_KNOWLEDGE_API_KEY=your_api_key
BAILIAN_KNOWLEDGE_BASE_URL=https://YOUR_WORKSPACE_ID.cn-beijing.maas.aliyuncs.com
BAILIAN_KNOWLEDGE_AGENT_ID=your_published_agent_id
BAILIAN_KNOWLEDGE_INDEX_ID=your_knowledge_index_id
COMPANY_KNOWLEDGE_USERS=employee_username_1,employee_username_2
```

密钥仅用于服务器请求，`.env` 不提交 Git。不得将其放到前端 JS。修改配置后重启后端。

默认仅管理员可访问；由于项目允许自行注册普通用户，普通账号必须被管理员显式加入 `COMPANY_KNOWLEDGE_USERS`。目前授权的是整个共享测试库，尚未提供部门或单文档权限隔离。

## 已接入功能

- 公司知识库菜单展示真实云端文件、处理状态、标签及分页加载。
- SSE 流式问答、最近 10 轮上下文、停止生成和错误提示。对话仅保存在当前页面内存，刷新后清空。
- 引用片段阅读，以及百炼返回的原件临时链接。未取得原件链接的文件不会展示虚构正文；原件入口在相关问答引用中提供。
- 问答等待期间展示云端实际阶段（连接、检索、资料整理、生成）、检索问题与文件/片段数量，并显示用时。每 3 秒无业务事件时发送 SSE 心跳，连接关闭时取消上游任务。规划阶段展示简短状态，不转发原始推理文本。
- 参考资料按文件 ID 合并为文件卡片，点击展开其全部片段并保留每个引用编号。同名不同文件不会合并。

资料上传、更新和删除目前在百炼控制台进行。页面“管理资料”提供控制台入口；上传并完成索引后，点击“刷新资料”。本轮没有将资料上传 API 或 Office 在线预览接入自有平台。PDF、Word 原件是否在浏览器显示或下载取决于浏览器和上游响应；页面内可阅读已返回的真实引用片段。

## 接口与验证

- `GET /company-knowledge/status`：配置与当前账号权限状态，不返回密钥。
- `GET /company-knowledge/documents`：需知识库授权，按页读取云端文档。
- `POST /company-knowledge/chat/stream`：需知识库授权，返回 `progress`、`heartbeat`、`status`、`citations`、`answer_delta`、`done` 或 `error` SSE 事件。

官方接口：[知识问答](https://help.aliyun.com/zh/model-studio/knowledgechat)、[文档列表](https://help.aliyun.com/zh/model-studio/rag-api-list-documents)。

回归测试：`$env:PYTHONPATH='backend'; .\.venv\Scripts\python.exe -m pytest test/test_company_knowledge.py -q`。覆盖认证、员工授权、密钥隔离、真实返回结构、流式完成/中断、错误映射和引用链接协议校验。

注意：待复核研究报告仍作为待复核资料使用，知识库接入成功不代表其中的业务结论已审核。

## 本次真实验证（2026-10-14）

云端文档列表和本地登录后的列表均读取到 5 份已完成索引的文件。真实比亚迪报告问答完整返回 5 条检索参考片段；浏览器验证了问候、多轮报告问答、引用片段弹窗。原件链接按 GET 下载验证返回 206，Word ZIP 文件头正确。相关回归测试 11 条通过；前端语法与浏览器控制台检查通过。验证摘要和截图保存在被 Git 排除的 `work/bailian-integration-check.json`、`work/company-knowledge-answer.png`。

本地服务重启时发现原有 Milvus 因 etcd 服务租约失效退出，已重新启动原容器并恢复健康，未删除或替换数据。云端知识库功能不依赖本地 Milvus。

## 进度与引用展示优化验证

后端 15 条测试、前端 Node 测试 3 条通过，覆盖心跳等待、取消上游任务、真实进度事件、同文件多片段合并以及同名不同文件保持独立。真实浏览器问答观察到连接、检索完成、资料整理和回答生成阶段，显示等待用时，完成后处理记录可展开。一次比亚迪资料问答返回 1 份文件、5 个片段，页面只展示 1 张文件卡片，打开后保留全部 `id_1` 至 `id_5` 片段。浏览器控制台无错误。截图：`work/company-knowledge-progress.png`。
