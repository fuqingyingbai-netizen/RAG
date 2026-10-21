"""Verify the real Markdown sanitizer in an isolated browser with networking blocked."""
import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets-dir', type=Path, default=ROOT / 'work/account-ui/vendor')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'work/markdown-ui')
    parser.add_argument('--browser-channel', default='msedge')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=args.browser_channel, headless=True)
        context = browser.new_context(viewport={'width': 1000, 'height': 800})
        context.route('**/*', lambda route: route.abort())
        page = context.new_page()
        page.set_content('<!doctype html><meta charset="UTF-8"><title>Markdown 隔离验证</title>'
                         '<style>body{font:16px system-ui;padding:32px;color:#17324d}table{border-collapse:collapse}'
                         'td,th{padding:12px;border:1px solid #cbd5e1}pre{padding:16px;background:#f1f5f9}</style>'
                         '<h1>AI 回复 HTML 净化验证</h1><div id="result"></div>')
        page.add_script_tag(path=str(args.assets_dir / 'marked.js'))
        page.add_script_tag(path=str(ROOT / 'frontend/vendor/purify-3.4.17.min.js'))
        page.add_script_tag(path=str(ROOT / 'frontend/safe-markdown.js'))
        attack = 'window.__markdownAttack=true'
        samples = [f'<script>{attack}</script>', f'<img src="https://invalid.test/x" onerror="{attack}">',
                   f'<svg onload="{attack}"><circle></circle></svg>',
                   f'<math><mtext><img src=x onerror="{attack}"></mtext></math>',
                   f'<iframe srcdoc="<script>{attack}</script>"></iframe>',
                   f'<a href="javascript:{attack}">危险链接</a>',
                   '<a href="java&#x73;cript:attack()">编码链接</a>',
                   '<a href="data:text/html,attack">数据链接</a>',
                   '<form><input name="SafeMarkdown"><button>提交</button></form>',
                   '<p style="position:fixed;inset:0" onclick="attack()">正文</p>']
        render = '(text) => { document.querySelector("#result").innerHTML = SafeMarkdown.render(text); }'
        for sample in samples:
            page.evaluate(render, sample)
            assert page.locator('#result script, #result svg, #result math, #result iframe, #result form, #result input, #result button').count() == 0
            assert page.evaluate('''() => [...document.querySelectorAll('#result *')].every(node =>
                [...node.attributes].every(attr => !/^on/i.test(attr.name) && attr.name !== 'style' &&
                  !(['href','src'].includes(attr.name) && /^(?:javascript|vbscript|file):/i.test(attr.value))))''')
            assert page.evaluate('window.__markdownAttack !== true')
        normal = ('## 正常 Markdown 内容\n\n**加粗**、列表、链接和表格保留。\n\n'
                  '- 资料已净化\n- 保留可读格式\n\n[安全链接](https://example.com)\n\n'
                  '| 检查项 | 结果 |\n| --- | --- |\n| 脚本、事件属性 | 移除 |\n| 正常排版 | 保留 |\n\n'
                  '```python\nprint("hello")\n```')
        page.evaluate(render, normal)
        assert page.locator('#result h2').inner_text() == '正常 Markdown 内容'
        assert page.locator('#result strong').inner_text() == '加粗'
        assert page.locator('#result li').count() == 2
        assert page.locator('#result table').count() == 1
        assert page.locator('#result a').get_attribute('href') == 'https://example.com'
        assert 'print' in page.locator('#result pre code').inner_text()
        page.screenshot(path=str(args.output_dir / 'sanitized-markdown.png'), full_page=True)
        page.evaluate('window.DOMPurify = undefined')
        page.evaluate(render, samples[1])
        assert page.locator('#result').inner_text() == samples[1]
        assert page.locator('#result img').count() == 0
        browser.close()
    print('Browser Markdown checks passed: 10 hostile samples, preserved formatting, plaintext fallback; no external requests')


if __name__ == '__main__':
    main()
