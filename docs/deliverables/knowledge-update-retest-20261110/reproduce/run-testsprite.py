import json,subprocess,sys
from pathlib import Path

root=Path(__file__).parent
cli=Path('E:/projects/RAG/work/testsprite-audit-20261110/tooling/node_modules/@testsprite/testsprite-cli/dist/index.js')
project='236f726e-2bec-4115-834b-9dee3b4a2d21'
def command(args):
    p=subprocess.run(['node',str(cli),*args,'--output','json'],capture_output=True,text=True,encoding='utf-8')
    if p.returncode:raise RuntimeError(p.stderr[-1200:])
    return json.loads(p.stdout)
usage=command(['usage'])
credits=usage.get('credits',usage.get('activeOrg',{}).get('remaining',0))
(root/'usage-before.json').write_text(json.dumps({'credits':credits,'plan':usage.get('subPlan')},indent=2))
if credits<10:raise RuntimeError('Insufficient free credits for bounded suite; no upgrade attempted')
cases=[
('UPDATE-NAV','Nested location and back navigation',[
 ('action','Open /audit/login/alice on the configured target origin. Verify the header says 当前验收账号：alice. Open 总资料库, 验收项目甲, 研究资料, 访谈记录.'),
 ('assertion','The 访谈记录 heading and its file list are visible. The 搜索与筛选 toolbar region and industry/review/date filters are absent inside this directory; sidebar category navigation is allowed.'),
 ('action','Use 返回上一级 once.'),('assertion','The heading changes to 研究资料 and 访谈记录 is a visible child folder. There is no misleading prompt claiming this folder-only directory is empty.')]),
('UPDATE-SEARCH','Branch search rejects a sibling file',[
 ('action','Open /audit/login/alice, then 总资料库 > 验收项目甲 > 研究资料 > 访谈记录. In 搜索知识库资料 search 访谈材料22.'),
 ('assertion','No matching file 访谈材料22.txt is shown in this branch. It belongs to sibling 合同资料. A settled no-match state is acceptable; loading is not evidence.'),
 ('action','Clear the search input.'),('assertion','访谈材料01.txt is visible again and the heading is still 访谈记录.')]),
('UPDATE-DEPT','Department filter and empty department isolation',[
 ('action','Open /audit/login/alice and 总资料库. Use 筛选所属部门／栏目 to select 市场部.'),
 ('assertion','验收项目甲 is listed and 他人共享项目 is absent.'),
 ('action','Change the same department selector to 项目部.'),('assertion','他人共享项目 is listed and 验收项目甲 is absent.'),
 ('action','Change the selector to 制度文件.'),('assertion','An explicit settled empty state is shown; neither other department project appears. Empty department must not fall back to all projects.')]),
('UPDATE-READONLY','Shared project management stays denied',[
 ('action','Open /audit/login/alice, 总资料库 > 他人共享项目.'),
 ('assertion','Its documents can be read, but 新建目录 and 上传文件 are disabled with a visible reason restricting management to the creator or administrator. No delete/edit project control is exposed.'),
 ('action','Open a readable file row more/options menu if present.'),('assertion','Alice cannot edit, move or delete Bob owned document. If no more menu is present for read-only files, report that as expected rather than inventing a missing control.')]),
('UPDATE-MENU','Owner file menu has clear actions and dismisses cleanly',[
 ('action','Open /audit/login/alice, 总资料库 > 验收项目甲. Locate the row TS-收入表.txt. Open its accessible 更多操作 menu.'),
 ('assertion','The menu exposes owner management actions for this exact file and does not act on a different file.'),
 ('action','Press Escape without choosing a destructive action.'),('assertion','The menu closes and the list remains usable with TS-收入表.txt still present.')]),
('UPDATE-SCOPE','Two selected files retain scope and return location',[
 ('action','Open /audit/login/alice, 总资料库 > 验收项目甲 > 研究资料 > 访谈记录. Check exactly 访谈材料01.txt and 访谈材料02.txt and use the selected-scope question action.'),
 ('assertion','智能问答 is selected and the scope explicitly contains exactly these two files, never all-library.'),
 ('action','Use 返回资料位置.'),('assertion','Return reaches 访谈记录 with both chosen checkboxes still selected.')]),
('UPDATE-EXPERIENCE','Experience and library switching keeps collection boundaries',[
 ('action','Open /audit/login/alice, then 经验沉淀.'),('assertion','共享经验 is present and 验收项目甲 is not shown as an experience project.'),
 ('action','Switch to 总资料库.'),('assertion','验收项目甲 is present and 共享经验 is absent. The selected tab and actual content agree.')]),
('UPDATE-THEME','Theme changes preserve directory and selection',[
 ('action','Open /audit/login/alice, 总资料库 > 验收项目甲 > 研究资料 > 访谈记录. Check 访谈材料01.txt. Toggle 切换知识库主题.'),
 ('assertion','The directory heading remains 访谈记录 and the same file remains selected; visible labels and actions remain readable.'),
 ('action','Toggle the theme back.'),('assertion','Directory and selection remain unchanged; no hidden overlay blocks file interaction.')]),
('UPDATE-NOTE','Published experience is readable by another member',[
 ('action','Open /audit/login/alice, 经验沉淀 > 新建图文笔记. Set 笔记标题 to TS-UPDATE-NOTE and 笔记正文 to PUBLIC-UPDATE-PARAGRAPH. Save and publish, wait for published state, then close the editor. Click fixture link 成员 Bob and confirm 当前验收账号：bob. Open 经验沉淀 > 全部文件, search TS-UPDATE-NOTE and read its published DOCX.'),
 ('assertion','Bob actually reads PUBLIC-UPDATE-PARAGRAPH in the rendered original. Finding only a document row is not sufficient. If conversion cannot finish, mark blocked, not passed. Bob has no edit/delete access to Alice note.')]),
('UPDATE-EXPORT','Saved synthetic answer exposes three export formats',[
 ('action','Open /audit/login/alice, 总资料库 > 验收项目甲. Check only TS-收入表.txt, start selected-scope chat and submit exactly 请生成合成收入表. This uses an explicitly synthetic provider to test file export, not real model quality. Wait for answer completion and save confirmation.'),
 ('assertion','A saved answer table includes 甲项目 120 and 乙项目 80, with source citations. It exposes Word, Excel and PNG/chart export actions; do not claim absent or disabled actions passed.'),
 ('action','Download Word, Excel and PNG/chart through their visible controls, choosing the income numeric column if asked. Do not navigate away until each completes.'),
 ('assertion','All three exports complete without application error. Record each format separately and retain actual download evidence; merely clicking a button is not proof of success.')])]
plans=[]
for ident,title,steps in cases:
    plans.append({'projectId':project,'type':'frontend','name':ident+' '+title,'priority':'p0',
        'description':'Current deployed frontend snapshot, independent synthetic data. Use configured target origin; never production. Execute concrete assertions; report unsupported capabilities blocked. Do not weaken a failed assertion or treat loading as success.',
        'planSteps':[{'type':kind,'description':description} for kind,description in steps]})
plan_file=root/'plans.jsonl'
plan_file.write_text('\n'.join(json.dumps(p,ensure_ascii=False) for p in plans)+'\n',encoding='utf-8')
args=['node',str(cli),'test','create-batch','--plans',str(plan_file),'--run','--wait','--target-url','http://127.0.0.1:8903','--max-concurrency','3','--timeout','900','--idempotency-key','knowledge-update-20261110b-v1','--output','json']
with (root/'testsprite-runs.json').open('w',encoding='utf-8') as out,(root/'testsprite-stderr.log').open('w',encoding='utf-8') as err:
    result=subprocess.run(args,stdout=out,stderr=err)
print(json.dumps({'cli_exit_code':result.returncode,'plans':len(plans),'credits_before':credits,'output':str(root/'testsprite-runs.json')}))
sys.exit(result.returncode)
