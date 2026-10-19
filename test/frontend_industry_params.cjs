const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
let definition;
const knowledge = vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../frontend/company-knowledge.js'), 'utf8') + '\nCompanyKnowledge;');
let knowledgeRegistered = false;
const app = {
  component(name, value) {
    assert.equal(name, 'company-knowledge');
    assert.equal(value, knowledge);
    knowledgeRegistered = true;
    return this;
  },
  use() { return this; }, mount() {},
};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../frontend/script.js'), 'utf8'), {
  Vue: { createApp(value) { definition = value; return app; } },
  ElementPlus: {}, CompanyKnowledge: knowledge, localStorage: { getItem() { return null; } }, Date, JSON,
});
assert.ok(knowledgeRegistered);
const state = definition.data();
state.form.industryFocus = '协作机器人';
state.form.excludedSegments = '军工、玩具';
state.form.researchPurpose = '战略研究';
state.form.includeCapitalMarkets = false;
state.form.asOfDate = '2026-01-31';
const fields = definition.methods.industryRunFields.call(state, 'industry');
assert.equal(fields.industry_focus, '协作机器人');
assert.equal(fields.include_capital_markets, false);
assert.equal(fields.as_of_date, '2026-01-31');
assert.equal(JSON.stringify(fields.excluded_segments), JSON.stringify(['军工', '玩具']));
assert.equal(JSON.stringify(definition.methods.industryRunFields.call(state, 'company')), '{}');
const resumed = definition.methods.industryRunFields.call(state, 'industry', {
  industry_scope: { segments: ['焊接机器人'], geography: '欧洲', as_of_date: '2025-12-31', capital_market: 'none', purpose: '投资判断' },
  include_capital_markets: false,
});
assert.equal(resumed.as_of_date, '2025-12-31');
assert.equal(resumed.include_capital_markets, false);
assert.equal(resumed.research_purpose, '投资判断');
assert.ok(state.modulesByTarget.industry.some(row => row.value === '技术路线对比'));
console.log('Industry form and resume parameters passed');
const page = fs.readFileSync('frontend/index.html', 'utf8');
assert.ok(page.includes("artifact.metadata?.proposal_confirmation_status === 'pending'"));
assert.ok(page.includes('建议书待确认'));
assert.ok(page.includes('artifact.metadata?.risk_transparency?.version'));
assert.ok(page.includes("dimension.score ?? '未评估'")); // A risk score of zero is a real score.
assert.ok(page.includes('dimension.evidence_support.verified_metric_count'));
assert.ok(page.includes('尚未校准'));
console.log('Industry risk support presentation passed');
assert.equal(definition.methods.artifactTypeLabel('industry_run'), '运行记录');
assert.ok(page.includes('最后记录：'));
