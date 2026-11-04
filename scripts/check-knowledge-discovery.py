"""Additional isolated-browser scenario, reused by the knowledge studio harness."""
import json
from playwright.sync_api import expect


def check(page, args, docs, mutations):
    page.get_by_role('tab', name='资料库', exact=True).click()
    page.get_by_role('button', name='搜正文', exact=True).click()
    page.get_by_role('textbox', name='搜索知识库资料', exact=True).fill('只在正文出现')
    page.get_by_role('button', name='搜索正文', exact=True).click()
    expect(page.locator('.ckb-content-results article')).to_have_count(1)
    expect(page.locator('.ckb-search-snippet mark')).to_have_text('只在正文出现')
    page.screenshot(path=str(args.output_dir/'body-search.png'), animations='disabled')
    page.locator('.ckb-search-result-title').click()
    expect(page.locator('.ckb-pdf-sheet[data-page="2"] .ckb-page-highlights mark')).to_be_visible()
    expect(page.get_by_role('status').filter(has_text='已匹配原文')).to_be_visible()
    geometry=page.locator('.ckb-reader-columns').bounding_box()
    assert geometry['y']<165 and geometry['height']>700, geometry
    page.get_by_role('combobox',name='PDF 章节目录',exact=True).select_option('2')
    page.get_by_role('button', name='放大 PDF', exact=True).click()
    expect(page.locator('.ckb-pdf-controls')).to_contain_text('110%')
    page.get_by_role('button', name='专注阅读', exact=True).click()
    expect(page.locator('.ckb-reader-question')).not_to_be_visible()
    page.screenshot(path=str(args.output_dir/'source-focus.png'), animations='disabled')
    page.get_by_role('button', name='退出专注', exact=True).click()
    page.get_by_role('button', name='Close this dialog').click()
    page.get_by_role('button', name='找文件', exact=True).click()
    page.get_by_role('button', name='清空搜索', exact=True).click()
    page.get_by_role('button', name='浏览全部文件', exact=True).click()
    expect(page.locator('.ckb-content-thumbnail.has-image').first).to_be_visible()
    page.screenshot(path=str(args.output_dir/'real-covers.png'), animations='disabled')
    # Word keeps native layout; matching crosses multiple text nodes in the sandbox.
    page.get_by_role('tab', name='经验沉淀', exact=True).click()
    page.get_by_role('button', name='浏览全部文件', exact=True).click()
    word=page.locator('.ckb-case-card').filter(has_text=docs[1]['title'])
    word.get_by_role('button',name='查看原件',exact=True).click()
    frame=page.frame_locator('iframe.ckb-document-frame')
    expect(frame.locator('section.docx')).to_have_count(2,timeout=60000)
    find=page.get_by_role('textbox',name='在原文中查找',exact=True)
    find.fill('第二页：完整上下文仍在');find.press('Enter')
    expect(page.get_by_role('status').filter(has_text='已匹配原文')).to_be_visible()
    assert frame.locator('body').evaluate("() => CSS.highlights.has('source')")
    page.screenshot(path=str(args.output_dir/'word-source-match.png'),animations='disabled')
    page.get_by_role('button',name='Close this dialog').click()
    page.get_by_role('button',name='随手记录',exact=True).click()
    dialog=page.get_by_role('dialog',name='随手记录一份经验',exact=True)
    dialog.get_by_label('经验名称',exact=True).fill('现场访谈的追问方法')
    dialog.get_by_label('适用场景',exact=True).fill('一线访谈')
    dialog.get_by_label('可复用做法',exact=True).fill('先确认时间，再询问具体事例。')
    dialog.get_by_label('选择上传资料',exact=True).set_input_files(str(args.output_dir/'synthetic-audio.wav'))
    page.screenshot(path=str(args.output_dir/'quick-capture.png'),animations='disabled')
    dialog.get_by_role('button',name='上传并归档',exact=True).click()
    expect(dialog.get_by_role('button',name='完成，查看资料',exact=True)).to_be_visible(timeout=15000)
    uploaded=next(row['body'] for row in reversed(mutations) if row['path'].endswith('/uploads'))
    created=next(row['body'] for row in reversed(mutations) if row['path']=='/company-knowledge/projects')
    assert created['category']=='项目经验' and created['name']=='随手记录 · 待整理'
    assert '现场访谈的追问方法' in uploaded['description'] and '可复用做法' in uploaded['description']
    dialog.get_by_role('button',name='完成，查看资料',exact=True).click()
    expect(page.locator('.ckb-directory-path')).to_contain_text('待整理')
    for width,height in [(390,844),(1440,960)]:
        page.set_viewport_size({'width':width,'height':height})
        assert page.evaluate('document.documentElement.scrollWidth')<=width
        page.screenshot(path=str(args.output_dir/f'discovery-{width}.png'),animations='disabled')
    return {'theme':args.theme,'body_search':True,'source_location':True,'word_match':True,'quick_capture':True,'reading_area':geometry}
