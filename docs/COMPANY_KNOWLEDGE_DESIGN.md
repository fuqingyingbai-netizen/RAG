# 公司知识库：Knowledge Universe

2026-11-03，基于远端 main 的最新系统外壳，为研究首页、资料库、研究问答、案例库提供完整的深色视觉系统。所有装饰图形由 CSS 与 SVG 绘制，无新增框架、运行依赖、外部图片或模型调用。

| 页面 | 布局与视觉 | 保留的业务行为 |
| --- | --- | --- |
| 研究首页 | 网格底纹、缓慢移动的知识轨道、深色问题入口、项目统计与经验卡片 | 按真实可访问资料统计；查案例和比较资料各自进入对应流程 |
| 资料库 | 默认文件卡片、按格式着色的立体图标、悬停反馈、卡片/列表切换与清晰状态标签 | 标签/时间/项目组合筛选、跨页选择、固定表头和分页、原件阅读与管理 |
| 研究问答 | 私有研究空间、近期会话入口、资料叠层图形、三种问题建议、独立问题与答案区域 | 服务端历史恢复、检索范围、流式进度、表格、引用核对、错误和停止状态 |
| 案例库 | 文档网格封面、音频波形、视频播放符号；独立的空档案引导画面 | 案例分类、筛选、上传、阅读、播放、说明检索和属性编辑 |

上传、管理、权限审批、音视频阅读与引用核对弹窗共享深色控件和反馈规则。PDF 原件的图像颜色保持原貌。桌面上将系统使用帮助移到左侧，避免遮挡资料分页和问答发送按钮；移动端放入顶部导航区域。

## 资料库文件展示（第二轮）

参考 [Spacedrive SpaceUI](https://github.com/spacedriveapp/spaceui) 的 FileGrid、KindIcon、TagPill 与 FileList 组织思路，改为默认卡片浏览，并保留表格供密集核对使用。Word、PDF、表格、演示文稿、图片、音视频与文本分别使用颜色和图形表达类型；这些是格式示意封面，不伪造文件缩略图或内容摘要。实际名称、项目、标签、说明、状态与时间取自目录数据，说明为空时不生成虚构文字。

选中态、收藏、标签筛选、阅读、管理、失败重试和权限申请直接在卡片操作；卡片/列表切换保留已选资料，展示偏好按账号保存，不改变问答的证据范围。布局随窗口调整列数，底部操作不随正文增多而被裁掉；文件列表继续独立滚动。所有效果沿用现有 Vue/CSS，无新增依赖。

## 动效与可访问性

导航提供“暂停动效/开启动效”按钮，并正确设置 aria-pressed。操作系统的 prefers-reduced-motion 会禁用装饰动画及过渡。所有装饰图形和图标对辅助技术隐藏，按钮仍有明确名称与焦点轮廓。颜色使用青色和紫色作为强调，处理失败、受限、可检索仍有文字标签。

空列表、空案例库、未创建会话、引用、模拟连接中断、上传进度与管理表单都有独立显示状态。文件名、标签、说明及模型答案继续使用 Vue 文本绑定，表格单元格不执行 HTML。

## 参考与边界

参考 [Onyx](https://github.com/onyx-dot-app/onyx) 的知识问答工作区组织方向和 [Magic UI](https://github.com/magicuidesign/magicui) 的轻量图形动效思路，采用原创 Vue 模板、CSS 与 SVG 实现，未复制组件源码或品牌素材。既有项目导航、登录页与其他研究功能继续使用 main 上的系统外壳。

## 验证

```powershell
node --test test/company-knowledge-ui.test.cjs test/knowledge-request-lifecycle.test.cjs
.venv/Scripts/python.exe -m pytest test/test_company_workspace.py test/test_company_knowledge.py test/test_company_memory.py --disable-warnings -q
.venv/Scripts/python.exe scripts/check-knowledge-studio-ui.py --assets-dir work/knowledge-redesign/vendor --output-dir work/knowledge-universe-qa
```

浏览器脚本使用生产前端文件、缓存的 Vue/Element Plus/图标依赖，以及隔离的合成 API、可解码音视频与 SSE 记录。覆盖四页桌面/手机视图、动效开关、减少动态效果偏好、比较资料、标签/日期组合筛选、管理与上传、播放、答案表格、引用、错误提示及无案例时的引导。检查资料展示上沿位置、卡片/列表切换与选择保持、文件分页、受限资料禁选、无匹配结果、底部操作可见性、卡片和封面最小高度、页面横向溢出及运行错误。

本轮定向检查为 44 项前端、70 项后端；云端索引使用模拟接口，未对业务数据库或真实百炼执行验收写入。
