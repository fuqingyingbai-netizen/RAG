// Run only in the documented CUA runtime with an isolated audit Tab and fs writer.
export async function runBusinessUiChecks(tab, fs, outputPath, selectedIds) {
  const current = new URL(await tab.url());
  if (current.origin !== 'http://127.0.0.1:8911') throw Error('Refusing a non-audit origin');
  let results = [];
  if (selectedIds) { try { results = JSON.parse(await fs.readFile(outputPath, 'utf8')); } catch {} }
  const role = (type, name) => tab.playwright.getByRole(type, { name, exact: true });
  const assert = (condition, message) => { if (!condition) throw Error(message); };
  async function check(id, run) {
    if (selectedIds && !selectedIds.includes(id)) return;
    try { const actual = await run(); results.push({ id, status: 'passed', actual }); }
    catch (error) { results.push({ id, status: 'failed', error: String(error) }); }
    await fs.writeFile(outputPath, JSON.stringify(results, null, 2));
  }
  async function library(actor = 'alice') {
    await tab.goto(current.origin + '/audit/login/' + actor);
    await role('button', '进入市场部').click();
    await role('heading', '市场部').waitFor({ state: 'visible', timeoutMs: 15000 });
    await role('button', '返回公司知识库').click();
    await role('tab', '总资料库').click();
    await role('heading', '项目空间').waitFor({ state: 'visible', timeoutMs: 15000 });
    await role('button', '进入项目：验收项目甲').waitFor({ state: 'visible', timeoutMs: 15000 });
  }
  await check('fixed-department-creation-four-entries', async () => {
    await library(); const actual = [];
    for (const label of ['市场部', '项目部', '制度文件', '专家资料']) {
      await role('button', '进入' + label).click();
      await role('heading', label).waitFor({ state: 'visible' });
      await role('button', '创建项目').first().click();
      const dialog = role('dialog', '创建项目'); await dialog.waitFor({ state: 'visible' });
      const value = await role('status', '项目所属部门／栏目').innerText();
      assert(value === label, 'Fixed department does not match entry');
      assert(await dialog.getByRole('combobox', { name: '项目所属部门／栏目', exact: true }).count() === 0, 'Fixed value still looks selectable');
      actual.push(value); await dialog.getByRole('button', { name: '取消', exact: true }).click();
      await dialog.waitFor({ state: 'hidden' });
    }
    return actual;
  });
  await check('global-project-department-is-editable', async () => {
    await library(); await role('button', '创建项目').first().click();
    await role('dialog', '创建项目').waitFor({ state: 'visible' });
    assert(await role('combobox', '项目所属部门／栏目').isEnabled(), 'Global department is not editable');
    assert(!(await role('button', '创建空项目').isEnabled()), 'Empty name can be submitted');
    await role('button', '取消').click(); await role('dialog', '创建项目').waitFor({ state: 'hidden' });
    return 'Choice enabled; empty name cannot submit';
  });
  await check('upload-inheritance-and-global-choice', async () => {
    await library(); await role('button', '进入项目：验收项目甲').click();
    await role('button', '上传文件').click(); await role('dialog', '上传文件').waitFor({ state: 'visible' });
    assert((await role('status', '上传所属部门／栏目').innerText()) === '市场部', 'Inherited department is not text');
    assert(await role('combobox', '上传所属部门／栏目').count() === 0, 'Inherited department has a dropdown');
    assert(await role('combobox', '上传位置').isEnabled(), 'Normal upload target is unexpectedly fixed');
    await role('combobox', '上传位置').selectOption('');
    await role('combobox', '上传所属部门／栏目').waitFor({ state: 'visible' });
    assert(await role('combobox', '上传所属部门／栏目').isEnabled(), 'Root independent upload lost department choice');
    await role('button', '取消').click(); await role('dialog', '上传文件').waitFor({ state: 'hidden' });
    return 'Inherited department is text; independent upload retains choice';
  });
  await check('reupload-path-is-explicit-and-fixed', async () => {
    await library(); await role('button', '进入项目：验收项目甲').click();
    await role('button', '重新上传').click(); const dialog = role('dialog', '重新上传到原位置');
    await dialog.waitFor({ state: 'visible' });
    assert(await dialog.getByRole('combobox').count() === 0, 'Fixed reupload still has destination dropdowns');
    assert((await role('region', '文件保存位置').innerText()).includes('验收项目甲'), 'Original destination missing');
    assert((await dialog.innerText()).includes('失败样本.txt'), 'Original file name missing');
    await dialog.getByRole('button', { name: '取消', exact: true }).click(); await dialog.waitFor({ state: 'hidden' });
    return 'Original path and file name are explicit; no fixed-value dropdowns';
  });
  await check('member-readonly-ui-with-reason', async () => {
    await library('bob'); await role('button', '进入项目：验收项目甲').click();
    await role('heading', '验收项目甲').waitFor({ state: 'visible' });
    assert(!(await role('button', '新建目录').isEnabled()), 'Member can create in another owner project');
    assert(!(await role('button', '上传文件').isEnabled()), 'Member can upload in another owner project');
    assert(await role('button', '更多操作：TS-收入表.txt').count() === 0, 'Member sees owner actions');
    assert((await tab.playwright.domSnapshot()).includes('只读项目：仅项目创建者或管理员'), 'Read-only reason missing');
    return 'Read allowed; create/upload disabled with reason; owner menu absent';
  });
  await check('parent-directory-bounded-scope', async () => {
    await library(); await role('button', '进入项目：验收项目甲').click();
    await role('checkbox', '选择目录：研究资料').check(); await role('checkbox', '选择目录：合同资料').check();
    await role('button', '向所选范围提问').click(); await role('region', '检索资料面板').waitFor({ state: 'visible' });
    const text = await role('region', '检索资料面板').innerText();
    assert(text.includes('选中 22 份资料'), 'Parent subtree count incorrect');
    assert(!text.includes('全部可访问资料'), 'Bounded selection expanded globally');
    return text.slice(0, 100);
  });
  await check('processing-and-failure-not-ready-evidence', async () => {
    await library(); await role('button', '进入项目：验收项目甲').click();
    assert(!(await role('checkbox', '选择资料：处理中样本.txt').isEnabled()), 'Processing evidence is selectable');
    assert(!(await role('checkbox', '选择资料：失败样本.txt').isEnabled()), 'Failed evidence is selectable');
    return 'Both pending and failed documents are unavailable for selection';
  });
  await check('existing-project-settings-editable-and-cancel-safe', async () => {
    await library(); await role('button', '进入项目：验收项目甲').click();
    await role('button', '编辑项目').click(); const dialog = role('dialog', '项目设置');
    await dialog.waitFor({ state: 'visible' }); const selector = role('combobox', '项目所属部门／栏目');
    const before = await selector.evaluate(element => element.value);
    assert(await selector.isEnabled(), 'Existing settings should remain editable for the owner');
    await selector.selectOption('project');
    assert((await selector.evaluate(element => element.value)) === 'project', 'Displayed choice cannot actually change');
    await dialog.getByRole('button', { name: '取消', exact: true }).click(); await dialog.waitFor({ state: 'hidden' });
    await role('button', '编辑项目').click(); await dialog.waitFor({ state: 'visible' });
    assert((await role('combobox', '项目所属部门／栏目').evaluate(element => element.value)) === before, 'Cancel persisted the draft change');
    await dialog.getByRole('button', { name: '取消', exact: true }).click(); await dialog.waitFor({ state: 'hidden' });
    return 'Owner setting is genuinely editable; cancel leaves original department unchanged';
  });
  return results;
}
