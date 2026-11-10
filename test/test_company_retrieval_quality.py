from company_retrieval import select_evidence


def node(doc,text,score=1,**metadata):
    return {'score':score,'text':text,'metadata':{'doc_id':doc,**metadata}}


def test_multi_file_comparison_retains_more_than_twelve_documents():
    allowed={str(i):{} for i in range(27)}
    nodes=[node(str(i),f'项目{i}收入{i+1}万元') for i in range(27)]
    old,ot=select_evidence(nodes,allowed,'index','比较所有项目收入',legacy=True)
    new,nt=select_evidence(nodes,allowed,'index','比较所有项目收入')
    assert len(old)==12 and len(new)==27
    assert nt['selected_documents']==27 and not nt['exhaustive']


def test_long_passage_locates_question_instead_of_losing_late_evidence():
    text='无关前言。'*3000+'核验专用指纹的值是738291。'+'其他内容。'*1000
    old,_=select_evidence([node('a',text)],{'a':{}},'index','核验专用指纹的值是什么',legacy=True)
    new,t=select_evidence([node('a',text)],{'a':{}},'index','核验专用指纹的值是什么')
    assert '738291' not in old[0][2] and '738291' in new[0][2]
    meta=new[0][1];assert text[meta['_excerpt_start']:meta['_excerpt_end']]==new[0][2]
    assert t['excerpted_count']==1


def test_dedup_uses_full_text_and_excludes_wrong_scope_and_index():
    prefix='相同开头'*3000
    selected,t=select_evidence([node('a',prefix+'结尾甲'),node('a',prefix+'结尾乙'),node('a',prefix+'结尾乙'),
        node('private','秘密'),node('a','其他索引',pipeline_id='other'),node('a','数值异常',score='invalid')],{'a':{}},'index')
    assert t['candidate_count']==3
    assert len(set(t['candidate_ids']))==3 and all(r[0]=='a' for r in selected)


def test_total_budget_is_bounded_without_silent_exhaustive_claim():
    nodes=[node(str(i),'正文'*15000) for i in range(90)]
    selected,t=select_evidence(nodes,{str(i):{} for i in range(90)},'index','汇总全部')
    assert len(selected)<=48 and sum(len(r[2]) for r in selected)<=80000
    assert t['selection_limited'] and not t['exhaustive']


def test_retrieval_batches_keep_explicit_scope_and_bounded_concurrency(monkeypatch):
    import asyncio
    import company_knowledge as kb
    import company_workspace as ws
    active=peak=0;filters=[]
    async def rpc(client,cfg,path,payload):
        nonlocal active,peak
        assert path.endswith('/retrieve')
        filters.append(payload['search_filters'][0]['doc_id'])
        active+=1;peak=max(peak,active)
        await asyncio.sleep(.01);active-=1
        return {'nodes':[]}
    monkeypatch.setattr(kb,'cloud_rpc',rpc)
    cfg={'index_id':'index','allowed_documents':{str(i):{} for i in range(301)}}
    async def run():return [event async for event in ws.grounded_answer(cfg,kb.KnowledgeQuestion(message='汇总项目'))]
    events=asyncio.run(run())
    assert peak==3 and sorted(len(ids) for ids in filters)==[1,100,100,100]
    assert {k for ids in filters for k in ids}==set(cfg['allowed_documents'])
    assert any(e['type']=='done' for e in events)
