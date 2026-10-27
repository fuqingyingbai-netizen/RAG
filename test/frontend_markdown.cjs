const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('frontend/safe-markdown.js', 'utf8');
function renderer(window) {
  vm.runInNewContext(source, {window});
  return window.SafeMarkdown;
}
const payload = '<img src=x onerror="attack()">\n<script>attack()</script>';
for (const window of [{}, {marked: {parse() {throw new Error('parser failed');}}},
  {marked: {parse: value => value}, DOMPurify: {isSupported: false, sanitize: value => value}}]) {
  const html = renderer(window).render(payload);
  assert.ok(!html.includes('<img') && !html.includes('<script'));
  assert.ok(html.includes('&lt;img') && html.includes('<br>'));
}
let input;
const safe = renderer({marked: {parse: value => '<p>' + value + '</p>'}, DOMPurify: {
  isSupported: true, sanitize(html, config) {input = {html, config}; return '<p>sanitized</p>';}
}});
assert.equal(safe.render('text'), '<p>sanitized</p>');
assert.equal(input.html, '<p>text</p>');
assert.ok(input.config.ALLOWED_TAGS.includes('table'));
assert.ok(!input.config.ALLOWED_TAGS.includes('script'));
assert.ok(!input.config.ALLOWED_ATTR.includes('style'));
for (const url of ['javascript:attack()', 'vbscript:attack()', 'file:///private', 'data:text/html,hi']) {
  assert.equal(input.config.ALLOWED_URI_REGEXP.test(url), false);
}
for (const url of ['https://example.com', 'http://example.com', 'mailto:team@example.com', '/docs', '#heading']) {
  assert.equal(input.config.ALLOWED_URI_REGEXP.test(url), true);
}
const html = fs.readFileSync('frontend/index.html', 'utf8');
assert.ok(html.indexOf('vendor/purify-3.4.17.min.js') < html.indexOf('safe-markdown.js'));
assert.ok(html.indexOf('safe-markdown.js') < html.indexOf('src="script.js"'));
assert.ok(fs.readFileSync('frontend/script.js', 'utf8').includes('window.SafeMarkdown.render(text)'));
console.log('Markdown checks passed: sanitize delegation, parser/sanitizer fallback, URL policy and script order');
