"""Browser acceptance for real root upload/move routes with an isolated catalogue."""
import json
from playwright.sync_api import expect


def configure(state, args, patch):
    import httpx
    return {'response': lambda path: httpx.Response(200,json={'references':[],'total':0}) if '/preview' in path else None, 'check': check}


def check(page, state, p, args, temp, errors):
    from test_company_workspace import project
    from company_catalog import CompanyDocument
    target=project(state,'根目录移动验证',visibility='restricted',readers=['bob'])
    folder=state.client.post('/company-knowledge/projects/'+target['id']+'/folders',json={'name':'归档子目录'}).json()
    file=temp/'根目录实测.txt';file.write_text('独立文件正文可读，移动前后保留原件。',encoding='utf-8')
    page.goto(page.url+'full');page.get_by_role('tab',name='资料库',exact=True).click()
    expect(page.locator('.ckb-heading-count')).to_contain_text('1 个项目 · 0 份独立文件')
    page.get_by_role('button',name='上传文件',exact=True).click()
    dialog=page.get_by_role('dialog',name='上传文件',exact=True)
    expect(dialog.get_by_label('上传位置',exact=True)).to_have_value('')
    expect(dialog).to_contain_text('所有正常账号可读')
    dialog.get_by_label('上传位置',exact=True).select_option(target['id'])
    dialog.get_by_label('上传子目录',exact=True).select_option(folder['id'])
    expect(dialog).to_contain_text('指定成员可读')
    dialog.get_by_label('上传位置',exact=True).select_option('')
    dialog.locator('input[type=file]').set_input_files(str(file))
    dialog.get_by_role('button',name='上传并归档',exact=True).click()
    expect(dialog.get_by_role('button',name='完成，查看资料',exact=True)).to_be_visible(timeout=30000)
    dialog.get_by_role('button',name='完成，查看资料',exact=True).click()
    expect(page.locator('.ckb-heading-count')).to_contain_text('1 个项目 · 1 份独立文件')
    root=page.locator('.ckb-root-file-row');expect(root).to_have_count(1)
    row=state.client.get('/company-knowledge/documents').json()['documents'][0]
    assert row['is_root'] and row['visibility']=='members'
    with state.db() as db:
        doc=db.get(CompanyDocument,row['id']);doc.state='ready';doc.cloud_id='root-qa';db.commit()
    page.reload();page.get_by_role('tab',name='资料库',exact=True).click()
    root.dblclick()
    reader=page.locator('.ckb-reader-dialog');expect(reader).to_be_visible()
    expect(reader).to_contain_text('根目录实测.txt')
    reader.locator('.el-dialog__headerbtn').click()
    expect(reader).not_to_be_visible()
    page.evaluate('window.getSelection()?.removeAllRanges()')
    for width,height in ((1440,1000),(390,844)):
        page.set_viewport_size({'width':width,'height':height})
        assert page.evaluate('document.documentElement.scrollWidth')<=width
        page.screenshot(path=str(args.output_dir/('root-files-'+str(width)+'.png')),animations='disabled')
    page.set_viewport_size({'width':1440,'height':1000})
    root.get_by_role('button',name='更多操作：根目录实测.txt',exact=True).click()
    page.get_by_role('menuitem',name='移动资料：根目录实测.txt',exact=True).click()
    move=page.get_by_role('dialog',name='移动文件',exact=True)
    move.get_by_label('移动目标位置',exact=True).select_option(target['id'])
    move.get_by_label('移动目标子目录',exact=True).select_option(folder['id'])
    move.get_by_role('button',name='查看移动与权限变化',exact=True).click()
    confirm=page.locator('.el-message-box')
    expect(confirm).to_contain_text('当前权限：内部 · 所有正常账号可读')
    expect(confirm).to_contain_text('指定成员（bob）')
    confirm.get_by_role('button',name='取消',exact=True).click()
    assert state.client.get('/company-knowledge/documents').json()['documents'][0]['is_root']==1
    move.get_by_role('button',name='查看移动与权限变化',exact=True).click()
    confirm.get_by_role('button',name='确认移动',exact=True).click()
    expect(move).not_to_be_visible(timeout=30000);expect(root).to_have_count(0)
    page.get_by_role('button',name='进入项目：'+target['name'],exact=True).click()
    page.get_by_role('button',name='归档子目录',exact=False).first.click()
    card=page.locator('[data-document-id="'+row['id']+'"]');expect(card).to_be_visible()
    card.get_by_role('button',name='更多操作：根目录实测.txt',exact=True).click()
    page.get_by_role('menuitem',name='移动资料：根目录实测.txt',exact=True).click()
    move.get_by_label('移动目标位置',exact=True).select_option('')
    move.get_by_role('button',name='查看移动与权限变化',exact=True).click()
    expect(confirm).to_contain_text('保留各版本现有保密等级')
    page.screenshot(path=str(args.output_dir/'move-permission-confirmation.png'),animations='disabled')
    confirm.get_by_role('button',name='确认移动',exact=True).click()
    expect(move).not_to_be_visible(timeout=30000)
    page.get_by_role('button',name='项目空间',exact=True).click();expect(root).to_have_count(1)
    page.reload();expect(root).to_have_count(1)
    found=state.client.get('/company-knowledge/documents').json()['documents'][0]
    assert found['is_root']==1 and found['visibility']=='restricted' and found['cloud_id']=='root-qa'
    assert not errors,errors
    print(json.dumps({'status':'passed','checks':['root upload defaults shared','upload project/subdirectory selectors','mixed project/file rows and separate counts','double click reader','desktop/mobile root','cancel move','move into project subdirectory with ACL confirmation','move out retains ACL','reload preserves root file'],'console_errors':errors},ensure_ascii=False),flush=True)
