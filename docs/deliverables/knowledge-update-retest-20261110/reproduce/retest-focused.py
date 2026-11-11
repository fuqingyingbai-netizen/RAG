import json,subprocess
from pathlib import Path
root=Path(__file__).parent
cli='E:/projects/RAG/work/testsprite-audit-20261110/tooling/node_modules/@testsprite/testsprite-cli/dist/index.js'
project='236f726e-2bec-4115-834b-9dee3b4a2d21'
plans=[
 {'projectId':project,'type':'frontend','name':'UPDATE-NAV-FOCUSED Exact filter controls absent in nested directory','priority':'p0',
  'planSteps':[{'type':'action','description':'Open /audit/login/alice on the configured target origin. Open 总资料库 > 验收项目甲 > 研究资料 > 访谈记录.'},
  {'type':'assertion','description':'Exactly the region with accessible name 搜索与筛选, combobox 筛选行业 and combobox 筛选复核状态 must be absent. 搜索知识库资料 textbox, 新建子目录, 上传文件 and sorting are deliberately ALLOWED and must remain. Their presence is not a failure. Sidebar categories are navigation and are also allowed. Record each named absent-control check.'},
  {'type':'action','description':'Click 返回上一级 once.'},{'type':'assertion','description':'Heading 研究资料 and child folder 访谈记录 are visible. No misleading current-directory-empty message appears.'}]},
 {'projectId':project,'type':'frontend','name':'UPDATE-MENU-FOCUSED Exact owned-file actions and trigger Escape','priority':'p0',
  'planSteps':[{'type':'action','description':'Open /audit/login/alice and 总资料库 > 验收项目甲. Open 更多操作：访谈材料23.txt.'},
  {'type':'assertion','description':'The exact file menu has 移动到…, 文件设置 and 删除文件. These three ARE the management actions. No separate change-owner or ownership-management item is required or desired. Do not report those three existing actions as missing management.'},
  {'type':'action','description':'Focus the SAME 更多操作：访谈材料23.txt native trigger button while its menu is open and press Escape. Wait for the menu to become hidden; do not select delete.'},
  {'type':'assertion','description':'The menu becomes hidden, focus remains usable and 访谈材料23.txt remains in the list. Pressing Escape again while closed must not open a menu.'}]}
]
path=root/'focused-retest-plans.jsonl'
path.write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in plans)+'\n',encoding='utf-8')
with (root/'focused-retest-runs.json').open('w',encoding='utf-8') as out,(root/'focused-retest-stderr.log').open('w',encoding='utf-8') as err:
    result=subprocess.run(['node',cli,'test','create-batch','--plans',str(path),'--run','--wait','--target-url','http://127.0.0.1:8905','--max-concurrency','2','--timeout','600','--idempotency-key','knowledge-update-20261110b-focused-v1','--output','json'],stdout=out,stderr=err)
print(json.dumps({'cli_exit_code':result.returncode,'plans':2}))
