// Run inside cua_repl with its tab handle. Browser actions use the documented Playwright API.
import assert from 'node:assert/strict';
const named=(p,role,name)=>p.getByRole(role,name==='返回资料位置'?{name:/^返回资料位置/}:{name,exact:true});
const passed=(log,id,rule)=>log.push({id,status:'passed',rule});
export async function root(tab){
  const p=tab.playwright;await named(p,'tab','资料库').click();
  await p.getByRole('button',{name:/^全部资料 \d+$/}).click();
  await named(p,'button','进入项目：验收项目甲').waitFor({state:'visible'});
  if(await named(p,'button','取消选择').count())await named(p,'button','取消选择').click();
}
export async function navigation(tab,log){
  const p=tab.playwright;await root(tab);
  assert.equal(await named(p,'region','搜索与筛选').count(),1);
  assert.equal(await named(p,'group','资料展示方式').count(),0);
  assert.equal(await named(p,'button','进入项目：他人私有项目').count(),0);
  passed(log,'NAV-01','总览筛选可见、列表固定、私有项目不可进入');
  await named(p,'button','更多筛选').click();assert.equal(await named(p,'combobox','处理状态').count(),0);
  passed(log,'FILTER-01','高级筛选不重复提供处理状态与标签');
  await named(p,'button','进入项目：验收项目甲').click();
  assert.equal(await named(p,'region','搜索与筛选').count(),0);
  assert.equal(await p.locator('.ckb-document-table tbody tr').count(),2);
  await named(p,'button','研究资料 1 个子目录 · 0 份资料').click();
  assert.equal(await p.locator('.ckb-document-table').count(),0);
  await named(p,'button','访谈记录 0 个子目录 · 21 份资料').click();
  assert.equal(await named(p,'region','搜索与筛选').count(),0);
  passed(log,'NAV-02','逐层进入目录，面包屑正确，无误导性的空文件表');
  await named(p,'textbox','搜索知识库资料').fill('访谈材料22');
  assert.equal(await named(p,'button','访谈材料22.txt').count(),0);
  await named(p,'button','清空搜索').click();await named(p,'button','研究资料').click();
  await named(p,'textbox','搜索知识库资料').fill('访谈记录');
  assert.equal(await named(p,'button','访谈记录 0 个子目录 · 21 份资料').count(),1);
  passed(log,'SEARCH-01','目录搜索含下级目录和文件，但不越出当前分支');
  await named(p,'button','清空搜索').click();await named(p,'button','返回上一级').click();
  assert.equal(await named(p,'heading','验收项目甲').count(),1);
  await p.getByRole('button',{name:/^研究成果 \d+$/}).click();
  assert.equal(await named(p,'button','进入项目：验收项目甲').count(),0);
  assert.equal(await named(p,'button','进入项目：他人共享项目').count(),1);
  passed(log,'NAV-03','从子目录切换分类时，选中菜单与正文同步');
  await named(p,'button','进入项目：他人共享项目').click();
  assert.notEqual(await named(p,'button','新建目录').getAttribute('disabled'),null);
  assert.notEqual(await named(p,'button','上传文件').getAttribute('disabled'),null);
  assert.equal(await p.locator('#ckb-directory-write-policy').count(),1);
  passed(log,'ACL-01','只读项目禁用新建和上传，并显示原因');
}
export async function selectProjects(tab,log){
  const p=tab.playwright;await root(tab);
  await named(p,'checkbox','选择项目：验收项目甲').check();
  await named(p,'checkbox','选择项目：他人共享项目').check();
  await named(p,'button','向所选范围提问').click();
  await named(p,'button','返回资料位置').waitFor({state:'visible'});
  assert.equal(await named(p,'tab','智能问答').getAttribute('aria-selected'),'true');
  passed(log,'SCOPE-01','多个项目选择后进入明确范围的问答，保留返回入口');
}
export async function nestedPageReturn(tab,log){
  const p=tab.playwright;await root(tab);
  await named(p,'button','进入项目：验收项目甲').click();
  await named(p,'button','研究资料 1 个子目录 · 0 份资料').click();
  await named(p,'button','访谈记录 0 个子目录 · 21 份资料').click();
  await named(p,'button','第 2 页资料').click();
  await named(p,'checkbox','选择资料：访谈材料11.txt').check();
  await named(p,'button','向所选范围提问').click();
  await named(p,'button','返回资料位置').waitFor({state:'visible'});
  await named(p,'button','返回资料位置').click();
  assert.equal(await named(p,'heading','访谈记录').count(),1);
  assert.equal(await named(p,'button','第 2 页资料').getAttribute('aria-current'),'page');
  assert.equal(await named(p,'checkbox','选择资料：访谈材料11.txt').evaluate(element=>element.checked),true);
  passed(log,'RETURN-01','三级目录第 2 页提问后，返回保持目录、页码与勾选');
}
