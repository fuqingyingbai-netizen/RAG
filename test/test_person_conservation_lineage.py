"""Offline controller tests; these fixtures are not live review results."""
import copy,pytest
from person_conservation import conserve_requirements,key,writer_missing_items


def fixture():
    row=lambda text:{'analysis':text,'evidence_ids':['E-PFIXTURE']}
    original=row('原始基线：2018年主持会议，金额10万元。')
    old=row('某次中间改写：2018年主持会议，金额10万元。')
    missing=row('另一项原始基线：2019年监督项目。')
    current=row('最新已验证表达：2018年主持会议，金额10万元。')
    other=row('2019年监督项目，保留当前已知内容。')
    review={'items':[{'prior_index':i,'status':'covered','matched_claim_indices':[0],
        'matched_table_indices':[],'gaps':[],'missing_numeric_anchors':[],'missing_tenures':[]} for i in range(2)]}
    review['items'].append({'prior_index':2,'status':'missing','matched_claim_indices':[1],'gaps':[{'prior_quote':missing['analysis']}]})
    return [original,old,missing],[current,other],review,[original,missing]


def test_only_a_certified_intermediate_version_is_replaced_with_its_real_current_carrier():
    prior,active,review,protected=fixture();out,proof=conserve_requirements(prior,active,{1},review,protected)
    assert out==[prior[0],prior[2],active[0],active[1]]
    assert proof['prior_index_map']=={0:0,2:1}
    assert [r['prior_index'] for r in proof['certified_intermediate_replacements']]==[1]
    assert proof['certified_intermediate_replacements'][0]['current_carriers']==[active[0]]
    assert prior[0] in out and prior[2] in out


@pytest.mark.parametrize('status',['missing','pending_review','excluded_with_source_bound_reason'])
def test_noncovered_intermediate_versions_remain_requirements(status):
    prior,active,review,protected=fixture();review['items'][1]['status']=status
    out,proof=conserve_requirements(prior,active,{1},review,protected)
    assert prior[1] in out and not proof['certified_intermediate_replacements']


@pytest.mark.parametrize('field,value',[('matched_table_indices',[0]),('gaps',[{'prior_quote':'缺少条件'}]),
    ('missing_numeric_anchors',['10']),('missing_tenures',[{'role':'董事','term':'三年'}]),
    ('matched_claim_indices',[]),('matched_claim_indices',[9]),('matched_claim_indices',[True])])
def test_table_dependencies_or_incomplete_receipts_cannot_certify_compaction(field,value):
    prior,active,review,protected=fixture();review['items'][1][field]=value
    out,proof=conserve_requirements(prior,active,{1},review,protected)
    assert prior[1] in out and not proof['certified_intermediate_replacements']


def test_original_baseline_is_preserved_even_when_it_has_a_real_covered_receipt():
    prior,active,review,protected=fixture();protected.append(prior[1])
    out,proof=conserve_requirements(prior,active,{1},review,protected)
    assert all(r in out for r in prior) and not proof['certified_intermediate_replacements']


def test_missing_indices_are_remapped_for_the_writer_without_altering_original_audit_items():
    prior,active,review,protected=fixture();out,proof=conserve_requirements(prior,active,{1},review,protected)
    item=copy.deepcopy(review['items'][2]);result=writer_missing_items([item],proof['prior_index_map'])
    assert result[0]['prior_index']==1 and out[1]==prior[2]
    assert item['prior_index']==2 and result[0]['gaps']==item['gaps']


def test_source_reference_order_cannot_make_an_immutable_original_baseline_replaceable():
    prior,active,review,protected=fixture();prior[1]['evidence_ids']=['E-PSECOND','E-PFIXTURE']
    protected.append({**prior[1],'evidence_ids':['E-PFIXTURE','E-PSECOND']})
    out,proof=conserve_requirements(prior,active,{1},review,protected)
    assert prior[1] in out and not proof['certified_intermediate_replacements']


def test_all_real_carriers_of_a_multi_paragraph_certificate_are_preserved():
    prior,active,review,protected=fixture();review['items'][1]['matched_claim_indices']=[0,1]
    out,proof=conserve_requirements(prior,active,set(),review,protected)
    assert active[0] in out and active[1] in out


def test_controller_keeps_the_initial_immutable_baseline_fixed_across_real_loop_boundaries(monkeypatch):
    import person_content_acceptance as acceptance
    original={'analysis':'初始来源支持的当前正文。','evidence_ids':['E-PORIGINAL']}
    baseline={'analysis':'初始旧稿保留要求。','evidence_ids':['E-PBASELINE']}
    seen=[]
    def step(package,current,requirements,writing,invoke,emit,validate,prechecked,missing,protected):
        seen.append(list(protected));candidate=[{'analysis':'离线测试中间候选'+str(len(seen)),'evidence_ids':['E-PORIGINAL']}]
        if len(seen)==3:return candidate,[],{'status':'passed','requests':0}
        return current,['content_coverage_missing'],{'status':'pending_final_coverage','requests':0,
            'candidate_repair':candidate,'conserved_requirements':[*requirements,*current],
            'final_review':{'status':'pending_review','items':[],'issues':['content_coverage_missing']}}
    monkeypatch.setattr(acceptance,'_accept_once',step)
    acceptance.accept_content({'chapter':3},[original],[baseline],{},lambda *args:None,None,lambda *args:None)
    assert len(seen)==3 and all(rows==[baseline,original] for rows in seen)
