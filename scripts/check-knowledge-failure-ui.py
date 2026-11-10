"""Failed upload controls against real routes and an isolated catalogue."""
import json
from playwright.sync_api import expect


def configure(state,args,patch):
    return {'response':lambda path:None,'check':check}


def check(page,state,p,args,temp,errors):
    from test_company_workspace import upload,project,stored_original
    from company_catalog import CompanyDocument
    library=project(state,'失败资料测试')
    parent=state.client.post('/company-knowledge/projects/'+library['id']+'/folders',json={'name':'访谈资料'}).json()
    child=state.client.post('/company-knowledge/projects/'+library['id']+'/folders',json={'name':'团队','parent_id':parent['id']}).json()
    data=[]
    for name,fields in [('根目录失败.txt',{'root':'true'}),('项目失败.txt',{'project_id':library['id'],'folder_id':child['id']}),('经验失败.txt',{'project_id':p['id']})]:
        row=upload(state,payload=b'original evidence',name=name,**fields).json()
        with state.db() as db:
            d=db.get(CompanyDocument,row['id']);d.state='failed';d.status_message='测试解析失败：可重试或重新上传修正文件';db.commit()
        data.append(row)
    from test_company_notes import save,publish
    note=state.client.post('/company-knowledge/notes',json={'project_id':p['id']}).json()
    note=publish(state,save(state,note,title='失败图文笔记'))
    with state.db() as db:
        d=db.get(CompanyDocument,note['pending_document_id']);d.state='failed';d.status_message='笔记索引失败测试';db.commit()
    page.goto(page.url+'full');page.get_by_role('tab',name='资料库',exact=True).click()
    root=page.locator('[data-failure-id="'+data[0]['id']+'"]');expect(root).to_be_visible()
    expect(root.get_by_role('button',name='重试处理',exact=True)).to_be_visible()
    expect(root.get_by_role('button',name='重新上传',exact=True)).to_be_visible()
    root.get_by_role('button',name='失败详情',exact=True).click()
    box=page.locator('.el-message-box');expect(box).to_contain_text('测试解析失败')
    box.get_by_role('button',name='知道了',exact=True).click()
    page.get_by_role('button',name='处理失败',exact=False).click()
    failed=page.locator('[data-failure-id="'+data[1]['id']+'"]');expect(failed).to_be_visible()
    failed.get_by_role('button',name='重新上传',exact=True).click()
    dialog=page.get_by_role('dialog',name='重新上传到原位置',exact=True)
    expect(dialog.get_by_label('上传位置',exact=True)).to_have_value(library['id'])
    destination=dialog.get_by_role('region',name='文件保存位置')
    # A named section is exposed as a region, and includes every ancestor.
    expect(destination).to_contain_text('资料库 / 失败资料测试 / 访谈资料 / 团队')
    page.screenshot(path=str(args.output_dir/'reupload-full-destination.png'),animations='disabled')
    source=temp/'修正版.txt';source.write_text('Corrected evidence',encoding='utf-8')
    dialog.get_by_label('选择上传资料',exact=True).set_input_files(str(source))
    dialog.get_by_role('button',name='上传并归档',exact=True).click()
    expect(dialog.get_by_role('button',name='打开所在目录',exact=True)).to_be_visible(timeout=30000)
    expect(destination).to_contain_text('已保存到')
    expect(destination).to_contain_text('资料库 / 失败资料测试 / 访谈资料 / 团队')
    docs=state.client.get('/company-knowledge/documents').json()['documents']
    corrected=next(d for d in docs if d['title']==data[1]['title'] and d['version']==2)
    assert corrected['knowledge_project_id']==library['id']
    assert corrected['folder_id']==child['id']
    assert stored_original(state,data[1]['id'])==b'original evidence'
    page.screenshot(path=str(args.output_dir/'reupload-result-destination.png'),animations='disabled')
    page.set_viewport_size({'width':390,'height':844});expect(destination).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth')<=390
    page.screenshot(path=str(args.output_dir/'reupload-result-mobile.png'),animations='disabled')
    page.set_viewport_size({'width':1440,'height':1000})
    dialog.get_by_role('button',name='查看本次上传文件',exact=True).click()
    reader=page.locator('.ckb-reader-dialog');expect(reader).to_be_visible()
    expect(reader).to_contain_text('项目失败.txt')
    expect(reader).to_contain_text('V2')
    reader.locator('.el-dialog__headerbtn').click();expect(reader).not_to_be_visible()
    # Reopen the original failed item to verify the directory action as well.
    failed.get_by_role('button',name='重新上传',exact=True).click()
    source.write_text('Corrected evidence third version',encoding='utf-8')
    dialog.get_by_label('选择上传资料',exact=True).set_input_files(str(source))
    dialog.get_by_role('button',name='上传并归档',exact=True).click()
    expect(dialog.get_by_role('button',name='打开所在目录',exact=True)).to_be_visible(timeout=30000)
    dialog.get_by_role('button',name='打开所在目录',exact=True).click()
    expect(page.locator('.ckb-directory-path')).to_contain_text('失败资料测试')
    expect(page.locator('.ckb-directory-path')).to_contain_text('访谈资料')
    expect(page.locator('.ckb-directory-path')).to_contain_text('团队')
    # Return to failures; cancellation never changes a stored record.
    page.get_by_role('button',name='处理失败',exact=False).click()
    failed.get_by_role('button',name='删除失败资料：项目失败.txt',exact=True).click()
    expect(box).to_contain_text('10 天内可恢复');box.get_by_role('button',name='取消',exact=True).click()
    expect(failed).to_be_visible()
    failed.get_by_role('button',name='删除失败资料：项目失败.txt',exact=True).click();box.get_by_role('button',name='删除',exact=True).click()
    expect(failed).to_have_count(0,timeout=30000)
    assert state.client.get('/company-knowledge/documents/'+data[1]['id']+'/original').status_code==404
    assert stored_original(state,data[1]['id'])==b'original evidence'
    # Same controls and retry route in experience.
    page.get_by_role('tab',name='经验沉淀',exact=True).click();page.get_by_role('button',name='处理失败',exact=False).click()
    note_row=page.locator('tr').filter(has_text='失败图文笔记');expect(note_row).to_contain_text('笔记索引失败测试')
    expect(note_row.get_by_role('button',name='编辑笔记：失败图文笔记',exact=True)).to_have_text('编辑并重试发布')
    note_row.get_by_role('button',name='删除笔记：失败图文笔记',exact=True).click();expect(box).to_be_visible()
    box.get_by_role('button',name='取消',exact=True).click();expect(note_row).to_be_visible()
    experience=page.locator('[data-failure-id="'+data[2]['id']+'"]');expect(experience).to_be_visible()
    experience.get_by_role('button',name='重试处理',exact=True).click();expect(experience).to_have_count(0,timeout=30000)
    assert data[2]['id'] in state.scheduled
    # Server refusal before registration offers discard and a fresh selection.
    page.get_by_role('tab',name='资料库',exact=True).click();page.get_by_role('button',name='上传文件',exact=True).click()
    upload_dialog=page.get_by_role('dialog',name='上传文件',exact=True)
    source=temp/'failed.txt';source.write_text('upload',encoding='utf-8')
    page.route('**/company-knowledge/uploads',lambda route:route.fulfill(status=422,json={'detail':'测试上传拒绝'}))
    upload_dialog.get_by_label('选择上传资料',exact=True).set_input_files(str(source));upload_dialog.get_by_role('button',name='上传并归档',exact=True).click()
    expect(upload_dialog.get_by_role('button',name='放弃上传',exact=True)).to_be_visible()
    expect(upload_dialog.get_by_role('button',name='重新选择文件',exact=True)).to_be_visible()
    upload_dialog.get_by_role('button',name='放弃上传',exact=True).click()
    expect(upload_dialog.locator('.ckb-upload-results li')).to_have_count(0)
    upload_dialog.get_by_role('button',name='取消',exact=True).click();page.unroute('**/company-knowledge/uploads')
    # A reader cannot delete or replace someone else's data in either UI or API.
    state.user.username='bob';state.user.id=2
    page.reload();page.get_by_role('tab',name='资料库',exact=True).click();page.get_by_role('button',name='处理失败',exact=False).click()
    expect(root).to_contain_text('归属人 alice')
    for name in ('重试处理','重新上传','删除'):
        expect(root.get_by_role('button',name=name,exact=True)).to_have_count(0)
    assert state.client.post('/company-knowledge/documents/'+data[0]['id']+'/retry').status_code==403
    assert state.client.delete('/company-knowledge/documents/'+data[0]['id']).status_code==403
    page.screenshot(path=str(args.output_dir/'failed-reader-permission.png'),animations='disabled')
    state.user.role='admin';page.reload();page.get_by_role('tab',name='资料库',exact=True).click();page.get_by_role('button',name='处理失败',exact=False).click()
    expect(root.get_by_role('button',name='重试处理',exact=True)).to_be_visible()
    page.screenshot(path=str(args.output_dir/'failed-admin-actions.png'),animations='disabled')
    page.set_viewport_size({'width':390,'height':844})
    # The table scrolls horizontally instead of widening the entire page.
    assert page.evaluate('document.documentElement.scrollWidth')<=390
    page.screenshot(path=str(args.output_dir/'failed-mobile.png'),animations='disabled')
    assert not errors,errors
    print(json.dumps({'status':'passed','checks':['full destination before and after reupload','open uploaded V2 directly','open exact nested directory','mobile destination','root failure actions','failure reason','reupload at original project creates V2','original retained','cancel deletion','confirmed recycle deletion','experience retry','pre-registration discard and reselect','reader buttons hidden and server returns 403','administrator controls','mobile'],'console_errors':errors},ensure_ascii=False),flush=True)
