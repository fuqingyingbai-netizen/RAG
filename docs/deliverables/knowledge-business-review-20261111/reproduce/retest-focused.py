from pathlib import Path
import json,subprocess
root=Path(__file__).parent;cli='E:/projects/RAG/work/testsprite-audit-20261110/tooling/node_modules/@testsprite/testsprite-cli/dist/index.js';project='236f726e-2bec-4115-834b-9dee3b4a2d21'
cases=[
('BIZ2-UPLOAD','Locked inherited metadata is text; genuine upload choices stay editable',[
('action','Open /audit/login/alice on the configured isolated origin. Open 总资料库 > 验收项目甲 > 上传文件.'),
('assertion','上传所属部门／栏目 is fixed text 市场部 with no department combobox or arrow. 上传位置 and 上传子目录 are still enabled selectors because normal upload may choose a different destination.'),
('action','Choose 根目录（独立文件） in 上传位置.'),('assertion','上传所属部门／栏目 becomes a genuinely enabled selector for a root independent upload.'),
('action','Cancel; in 验收项目甲 use 重新上传 on 失败样本.txt without choosing a file.'),
('assertion','重新上传到原位置 clearly shows the original project path and file name; fixed department is text, and there are no disabled location or child-folder comboboxes. Cancel without uploading.')]),
('BIZ2-FAILURE','Freeze the synthetic processing sample before checking its UI state',[
('action','Open /audit/login/alice, 总资料库 > 验收项目甲. Inspect 处理中样本.txt and 失败样本.txt without retrying/deleting.'),
('assertion','处理中样本.txt stays in a processing/indexing status and its selection checkbox is disabled. 失败样本.txt has a failure label and a disabled selection checkbox, with 失败详情 and appropriate owner recovery actions. Neither is usable as ready evidence. The audit indexer now deliberately leaves processing-owned pending.')]),
('BIZ2-RECOVERY','Persistent synthetic fault clears through the actual retry button',[
('action','Open /audit/login/alice, then /audit/fault/documents-until-cleared on the same configured origin. It redirects to the preview; this audit route is now ahead of the static mount.'),
('assertion','Visible error 隔离环境模拟资料请求失败，请重试 and the application 重试 button are shown. Do not interpret a loading skeleton as a successful empty library.'),
('action','Use the audit-only 解除模拟故障 button, then the actual application 重试 button (or 刷新 if the app has already recovered).'),
('assertion','The error clears and 总资料库 can display 验收项目甲. Audit controls are fixtures, not production product controls.')]),
('BIZ2-EXPERIENCE','Inspect the actual creation form before judging experience fields',[
('action','Open /audit/login/alice, 经验沉淀 > 创建项目. Do not save.'),
('assertion','The creation dialog has no 项目所属部门／栏目 selector, no 项目单独授权 checkbox and no 指定成员 control. Published experience is shared for reading; management remains owned.'),
('action','Cancel; enter 共享经验.'),('assertion','访谈材料27.txt is readable while owner-only editing and file 更多操作 controls are absent. Then switch 总资料库; 验收项目甲 is present and 共享经验 is absent. Its absence from the library is correct, not a bug.')]),
('BIZ2-PARENT','Validate selected counts instead of misreading the collection prefix',[
('action','Open /audit/login/alice, 总资料库. Select projects 验收项目甲 and 他人共享项目; use 向所选范围提问 without sending a question.'),
('assertion','The scope says 选中 27 份资料. 总资料库 is only the collection name, not proof of unrestricted scope: explicit 选中 N 份资料 is bounded. Do not include 他人私有项目, TS-BIZ-UI-独立流程, 失败样本.txt or 处理中样本.txt.'),
('action','Return using the button whose name starts 返回资料位置. Use 取消选择; enter 验收项目甲, check 研究资料 and 合同资料, and ask the selected scope.'),
('assertion','The scope says 选中 22 份资料 (21 under 访谈记录 plus 1 under 合同资料). It must not say 全部可访问资料. Do not submit a question.')])]
plans=[{'projectId':project,'type':'frontend','name':ident+' '+name,'priority':'p0','description':'Focused exact-assertion retest on disposable synthetic target after fixture corrections; no production access. Preserve original run verdicts. Use only visible controls; no deletes or settings saves. Root creation dialog settings for an existing project are legitimately editable; do not invent a prohibition.','planSteps':[{'type':t,'description':d} for t,d in steps]} for ident,name,steps in cases]
file=root/'focused-plans.jsonl';file.write_text('\n'.join(json.dumps(p,ensure_ascii=False) for p in plans)+'\n',encoding='utf-8')
with (root/'focused-runs.json').open('w',encoding='utf-8') as out,(root/'focused-stderr.log').open('w',encoding='utf-8') as err:p=subprocess.run(['node',cli,'test','create-batch','--plans',str(file),'--run','--wait','--target-url','http://127.0.0.1:8911','--max-concurrency','3','--timeout','900','--idempotency-key','knowledge-business-review-20261111-focused-v1','--output','json'],stdout=out,stderr=err)
print(json.dumps({'cases':len(plans),'exit_code':p.returncode}))
