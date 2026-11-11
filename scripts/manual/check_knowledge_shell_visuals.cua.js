// Run through Computer Use/CUA with the disposable audit app on port 8913.
// Pass the documented browser viewport capability and a node:fs/promises writer.
export async function runKnowledgeShellVisualChecks(tab, viewport, fs, outputPath) {
  const origin = new URL(await tab.url()).origin;
  if (origin !== 'http://127.0.0.1:8913') throw Error('Refusing a non-audit origin');
  const results = [];
  const role = (name) => tab.playwright.getByRole('button', {name, exact: true});
  async function home(width, height) {
    await viewport.set({width, height});
    await tab.goto(origin + '/audit/login/alice');
    await tab.goto(origin + '/full');
    const actual = await tab.playwright.evaluate(() => ({width: innerWidth, height: innerHeight}));
    if (actual.width !== width || actual.height !== height) {
      const error = Error('Viewport override did not take effect: ' + JSON.stringify(actual));
      error.blocked = true; throw error;
    }
    if (await role('展开导航').isVisible()) await role('展开导航').click();
    await role('打开公司知识库').click();
    await tab.playwright.getByRole('searchbox', {name: '搜索资料', exact: true}).waitFor({state: 'visible'});
  }
  async function check(id, run) {
    try {
      const actual = await run();
      results.push({id, status: actual.passed ? 'passed' : 'failed', actual});
    } catch (error) {
      results.push({id, status: error.blocked ? 'blocked' : 'failed', error: String(error)});
    }
    await fs.writeFile(outputPath, JSON.stringify(results, null, 2));
  }
  try {
    await check('mobile-home-search-readable-width', async () => {
      await home(375, 812);
      const actual = await tab.playwright.getByRole('searchbox', {name: '搜索资料', exact: true})
        .evaluate(el => ({width: el.getBoundingClientRect().width, parentWidth: el.parentElement.getBoundingClientRect().width, viewport: innerWidth}));
      // Review guard for short Chinese keywords; does not prescribe a universal design size.
      return {...actual, passed: actual.width >= 120};
    });
    await check('mobile-upload-primary-not-covered', async () => {
      await home(375, 812);
      await tab.playwright.getByRole('searchbox', {name: '搜索资料', exact: true}).fill('访谈');
      await role('搜索资料').click();
      await tab.playwright.getByRole('heading', {name: '全部文件', exact: true}).waitFor({state: 'visible'});
      await role('上传文件').click();
      const dialog = tab.playwright.getByRole('dialog', {name: '上传文件', exact: true});
      await dialog.waitFor({state: 'visible'});
      let actual, previous, stable = 0;
      // CUA exposes geometry but not Web Animations. Read until geometry/hit target settle.
      for (let attempt = 0; attempt < 12; attempt++) {
        actual = await dialog.getByRole('button', {name: '上传并归档', exact: true}).evaluate(el => {
        const rect = el.getBoundingClientRect();
        const hit = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
        const points = [[0.5,0.5],[0.5,0.85],[0.85,0.5],[0.85,0.85]].map(([x,y]) => {
          const target = document.elementFromPoint(rect.x + rect.width*x, rect.y + rect.height*y);
          return {x,y,hitsPrimary:target===el||el.contains(target),hitLabel:target?.closest('button')?.getAttribute('aria-label')};
        });
        return {centerHitsPrimary: hit === el || el.contains(hit), points, hitTag: hit?.tagName, hitLabel: hit?.closest('button')?.getAttribute('aria-label'), viewport: innerWidth, primary: {x: rect.x, y: rect.y, width: rect.width, height: rect.height}};
        });
        const sample = JSON.stringify(actual);
        stable = sample === previous ? stable + 1 : 0;
        if (stable >= 3) break;
        previous = sample;
        await tab.playwright.domSnapshot();
      }
      if (stable < 3) { const error = Error('Modal geometry did not settle'); error.blocked = true; throw error; }
      await dialog.getByRole('button', {name: '取消', exact: true}).click();
      await dialog.waitFor({state: 'hidden'});
      return {...actual, passed: actual.points.every(point => point.hitsPrimary)};
    });
    await check('tablet-home-search-readable-width', async () => {
      await home(768, 1024);
      const width = await tab.playwright.getByRole('searchbox', {name: '搜索资料', exact: true}).evaluate(el => el.getBoundingClientRect().width);
      return {width, passed: width >= 120};
    });
    await check('keyboard-tabs-arrow-key-switches-focus-and-view', async () => {
      await home(1440, 900);
      await tab.playwright.getByRole('tab', {name: '知识库首页', exact: true}).press('ArrowRight');
      const actual = await tab.playwright.evaluate(() => ({focusedId: document.activeElement?.id, selectedId: document.querySelector('[role=tab][aria-selected=true]')?.id}));
      return {...actual, passed: actual.focusedId === 'ckb-library-tab' && actual.selectedId === 'ckb-library-tab'};
    });
  } finally { await viewport.reset(); }
  return results;
}
