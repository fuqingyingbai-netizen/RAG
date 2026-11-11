import json,subprocess,sys
from pathlib import Path
root=Path(__file__).parent
cli=Path('E:/projects/RAG/work/testsprite-audit-20261110/tooling/node_modules/@testsprite/testsprite-cli/dist/index.js')
project='236f726e-2bec-4115-834b-9dee3b4a2d21'
def command(args):
 p=subprocess.run(['node',str(cli),*args,'--output','json'],capture_output=True,text=True,encoding='utf-8',timeout=90)
 if p.returncode:raise RuntimeError(p.stderr[-1200:])
 return json.loads(p.stdout)
usage=command(['usage']);credits=usage.get('credits',0)
(root/'usage-before.json').write_text(json.dumps({'credits':credits,'plan':usage.get('subPlan')},indent=2))
if credits<12:raise RuntimeError('Free credits below bounded test budget; no purchase attempted')
cases=[
('BIZ-FIXED-DEPT','Fixed department must look fixed in all four creation dialogs',[
('action','Open /audit/login/alice on the configured isolated origin. Confirm 当前验收账号：alice. Use 进入市场部, then 创建项目.'),
('assertion','The project dialog displays 市场部 as plain output/text and has NO select/combobox or dropdown arrow for 项目所属部门／栏目. Do not confuse the underlying page filter with the dialog field.'),
('action','Cancel without saving. Repeat creation dialog checks through 进入项目部, 进入制度文件, and 进入专家资料, cancelling each.'),
('assertion','All four fixed creation fields are plain fixed labels matching their department. No new projects were saved.')]),
('BIZ-GLOBAL-CREATE','Global project creation retains a real choice',[
('action','Open /audit/login/alice, 总资料库 > 创建项目.'),
('assertion','项目所属部门／栏目 is an enabled selector with multiple department choices. Empty 项目名称 prevents creation, with no accidental project saved.'),
('action','Select 制度文件, enter TS-BIZ-CANCEL-ONLY as the project name, then 取消.'),
('assertion','Dialog closes and no TS-BIZ-CANCEL-ONLY project appears in the list.')]),
('BIZ-NESTED','Directory controls have context and breadcrumbs work',[
('action','Open /audit/login/alice, 总资料库 > 验收项目甲 > 研究资料 > 访谈记录.'),
('assertion','Heading is 访谈记录. Global 搜索与筛选 region, industry, department and review selectors are absent. Current-directory search, upload, create-folder and sorting are allowed. No card/list toggle or 搜正文 control appears.'),
('action','Use 返回上一级 once, then the 项目空间 breadcrumb.'),
('assertion','First return reaches 研究资料 with 访谈记录 child visible; 项目空间 reaches the project list. No sidebar/content mismatch.')]),
('BIZ-EMPTY','Empty and folder-only projects are distinguishable',[
('action','Open /audit/login/alice, 总资料库 > 仅目录项目.'),
('assertion','空子目录 appears. The page must not claim the entire directory has no contents while displaying a child folder.'),
('action','Open 空子目录, then return to 项目空间 and open 空项目.'),
('assertion','Both genuinely empty locations provide a settled accurate empty state with creator 新建目录 and 上传文件 available.')]),
('BIZ-SEARCH','No-match search explains recovery and excludes siblings',[
('action','Open /audit/login/alice, 总资料库 > 验收项目甲 > 研究资料 > 访谈记录. Search 访谈材料22 in 搜索知识库资料.'),
('assertion','Sibling 访谈材料22.txt is absent. Settled empty message says no matching material / change keyword / clear search, not misleading 当前目录暂无资料.'),
('action','Clear search.'),('assertion','访谈材料01.txt returns in the same directory.')]),
('BIZ-READONLY','Ordinary shared member sees reason and cannot manage',[
('action','Open /audit/login/bob, 总资料库 > 验收项目甲.'),
('assertion','Bob can see readable documents, but 新建目录 and 上传文件 are disabled with a visible creator/admin reason. 编辑项目 and owner-only file move/settings/delete are absent. Read-only does not mean the page itself cannot be browsed.')]),
('BIZ-ADMIN','Administrator retains management throughout hierarchy',[
('action','Open /audit/login/audit-admin, 总资料库 > 验收项目甲 > 研究资料 > 访谈记录.'),
('assertion','新建目录 and 上传文件 are enabled. A normal ready file 更多操作 menu offers 移动到, 文件设置 and 删除. Do not select delete or save changes.'),
('action','Dismiss menu with Escape.'),('assertion','Menu closes and document remains listed.')]),
('BIZ-SCOPE-RETURN','Explicit two-file question preserves exact return location',[
('action','Open /audit/login/alice, 总资料库 > 验收项目甲 > 研究资料 > 访谈记录. Check exactly 访谈材料01.txt and 访谈材料02.txt, then use selected-material question action.'),
('assertion','智能问答 opens with exactly two selected files in scope, not all-library.'),
('action','Use 返回资料位置.'),('assertion','访谈记录 returns and both same checkboxes remain selected.')]),
('BIZ-PARENT-SCOPE','Parent folders and root projects can define multi-selection',[
('action','Open /audit/login/alice, 总资料库. Select 验收项目甲 and 他人共享项目 using their project checkboxes. Start selected-material question action without submitting a question.'),
('assertion','Chat scope resolves readable ready documents from both selected projects, never includes 他人私有项目 and never silently uses the whole library.'),
('action','Return to the browse location, clear selected scope through visible controls, open 验收项目甲 and select 研究资料 plus 合同资料 folders, then start scoped question.'),
('assertion','Both parent folder subtrees can be used as a bounded scope. No inaccessible or processing document is counted as ready evidence.')]),
('BIZ-FAILURE','Failed and processing rows do not pretend to be ready',[
('action','Open /audit/login/alice, 总资料库 > 验收项目甲. Inspect 失败样本.txt and 处理中样本.txt without retrying or deleting.'),
('assertion','Failure has understandable status/details and relevant recovery actions. Processing has a processing state; neither can silently be used as ready question evidence. Do not label absence of a normal 更多 menu on failed rows as a bug if explicit failure actions replace it.')]),
('BIZ-MENU','Owner menu focus escape closes without mutation',[
('action','Open /audit/login/alice, 总资料库 > 验收项目甲. Open 更多操作：TS-收入表.txt.'),
('assertion','Exact-file menu includes 移动到, 文件设置 and 删除; no unrelated ownership-transfer control is required.'),
('action','Put keyboard focus back on the same 更多操作 trigger if necessary, then press Escape.'),
('assertion','Menu is closed and TS-收入表.txt still exists. Reopen and click outside; it closes again.')]),
('BIZ-EXPERIENCE','Shared experience and private drafts keep distinct permissions',[
('action','Open /audit/login/alice and 经验沉淀. Browse 共享经验.'),
('assertion','Alice can read Bob shared experience but cannot edit/move/delete Bob files. Experience forms should not ask users to restrict published reading to selected members; no confusing library-only department field.'),
('action','Switch to 总资料库.'),('assertion','验收项目甲 is visible, 共享经验 is not mixed into the library, and selected tab matches content.')]),
('BIZ-RECOVERY','Document request failure has retry and remains navigable',[
('action','Open /audit/login/alice, then navigate to /audit/fault/documents-once on the same isolated origin. Wait for the intentional one-time document-list 503.'),
('assertion','A visible load error or retry affordance is shown; it must not settle into a misleading successful empty catalogue with no error.'),
('action','Use visible 刷新 or retry, then open 总资料库 > 验收项目甲.'),
('assertion','Catalogue recovers, project contents return and navigation is usable without logging out.')]),
('BIZ-EXPLORE','Explore semantic UI contradictions rather than only click success',[
('action','Open /audit/login/alice. Explore total library, 进入市场部, project 验收项目甲, child 研究资料 and leaf 访谈记录. Open and cancel create/upload/settings dialogs as available. Do not save, delete, reclassify or change permissions.'),
('assertion','Audit whether shown choices are genuinely changeable, locked values look fixed, filters match current location, button labels describe resulting action, navigation and content agree, and every dead/disabled entry has understandable reason. Record exact reproducible contradictions with route/steps/actual/expected; do not invent unsupported business rules. If a product choice is uncertain, explicitly report needs-business-clarification rather than passing it as correct.')]),
]
plans=[{'projectId':project,'type':'frontend','name':ident+' '+title,'priority':'p0','description':'Only configured localhost isolated target with synthetic data; never production. Use real visible controls. Do not mutate shared fixtures, purchase anything, or silently weaken assertions. Test harness department buttons simulate real department entry props. Model/provider is synthetic; no model-quality claim. Report unsupported actions blocked; wait for settled states.','planSteps':[{'type':kind,'description':description} for kind,description in steps]} for ident,title,steps in cases]
file=root/'plans.jsonl';file.write_text('\n'.join(json.dumps(p,ensure_ascii=False) for p in plans)+'\n',encoding='utf-8')
args=['node',str(cli),'test','create-batch','--plans',str(file),'--run','--wait','--target-url','http://127.0.0.1:8911','--max-concurrency','3','--timeout','1200','--idempotency-key','knowledge-business-review-20261111-v1','--output','json']
with (root/'testsprite-runs.json').open('w',encoding='utf-8') as out,(root/'testsprite-stderr.log').open('w',encoding='utf-8') as err:p=subprocess.run(args,stdout=out,stderr=err)
print(json.dumps({'plans':len(plans),'cli_exit_code':p.returncode,'credits_before':credits}));sys.exit(p.returncode)
