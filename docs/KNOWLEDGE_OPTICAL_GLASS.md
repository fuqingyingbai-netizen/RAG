# 知识库光学玻璃

弹窗使用三层材质：圆角镜片边缘、独立虚化的阅读区域、随指针移动的柔和高光。边缘通过每个弹窗尺寸生成的 SVG 位移贴图折射真实背景，文字与表单始终处于滤镜之外。材质位于 dialog 的同级，避免嵌套 backdrop 根节点导致中央虚化失效。只在弹窗打开或尺寸改变时生成贴图，保留四项无业务数据的尺寸缓存，不运行持续绘制循环。

Chromium / Edge 启用 SVG 折射；其他浏览器保留磨砂与边缘高光。减少透明度或增强对比度时使用实色底，减少动画或知识库暂停动效时停止指针高光。观察器、指针监听器与待执行动画帧在组件卸载时释放。卡片继续采用独立的磨砂样式。

设计参考 [shuding/liquid-glass](https://github.com/shuding/liquid-glass) 与 [dpawlikowski/liquid-glass](https://github.com/dpawlikowski/liquid-glass)，实现为本项目独立代码。

修改源文件 `knowledge-glass-optics.js`、`company-knowledge.js`、`company-knowledge-glass.css` 后，运行 `scripts/build-knowledge-assets.py` 生成内容摘要命名的资源并更新 index.html，避免旧页面加载一半新版资源。保留旧资源供已打开的页面使用。

## 无重启发布

这轮只涉及前端，不切换或覆盖服务器的行业研究后端。`deploy/publish-knowledge-ui.py` 接受受限暂存区内的固定提交资源包，校验资源摘要、当前 index 与组件基线，并同时持有部署和前端锁。先发布新资源，最后原子替换 HTML 中知识库的三个资源引用；原有资源不覆盖。

后台进程目录与 current 指向可能不同，发布工具分别验证两者的前端基线并在需要时更新两个入口。工具保存原始 HTML 与发布回执，检查进程编号、加载实例和后端文件摘要保持不变。失败恢复入口，保留已发布的摘要资源供已加载页面使用。此类发布不重启应用、不暂停任务、不修改生产环境变量和业务数据库。

原后端发布清单继续标识基础应用，单独的 `knowledge-ui-receipt-提交号.json` 标识前端覆盖版本，不将前端更新伪装成完整后端发布。
