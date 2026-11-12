/* Project categories reuse the existing single-target research endpoints. */
const ProjectWorkspace = (() => {
  const families = [
    {value:'all',label:'全部项目',description:'查看当前账号可访问的项目与成果。'},
    {value:'background',label:'背调项目',description:'围绕一个主要对象，组合开展背景调查。',types:['CA项目','VC项目','BDD项目','CDD项目','投后项目']},
    {value:'research',label:'研究项目',description:'围绕行业、赛道、竞品与专题形成研究成果。',types:['行业研究','赛道分析','竞品研究','专题研究']},
    {value:'ai',label:'AI 项目',description:'开展 AI 专项研究；应用建设先保存本机草稿。',types:['AI专项研究','AI公司尽调','AI应用建设']}
  ];
  const reports = {
    'BDD项目':[{value:'company',label:'公司背景报告'},{value:'person',label:'人物背景报告'}],
    'CDD项目':[{value:'industry',label:'行业报告'}],
    '行业研究':[{value:'industry',label:'行业研究报告'}],
    '赛道分析':[{value:'industry',label:'赛道分析报告'}],
    '竞品研究':[{value:'industry',label:'竞品研究报告'}],
    '专题研究':[{value:'industry',label:'专题研究报告'}],
    'AI专项研究':[{value:'industry',label:'AI 专项研究报告'}],
    'AI公司尽调':[{value:'company',label:'AI 公司尽调报告'}]
  };
  const pendingTypes=['CA项目','VC项目','投后项目','AI应用建设'];
  const familyOf = (_project, intake) => {
    const type = intake?.research_type;
    const match = families.find(f => f.types?.includes(type));
    // Legacy reports all belonged to the due-diligence workspace; object type is not business intent.
    return match?.value || 'background';
  };
  function install(options) {
    const originalData=options.data, previous={...options.methods}, computed={...options.computed};
    options.data=function(){return {...originalData.call(this), workspaceFamily:'all', workspaceTypeFilter:'',
      workspaceIntakes:{}, workspaceMetaErrors:{}, workspaceMetaSequence:0, workspaceMetaLoading:false,
      projectDetailTabs:{}, localProjectDrafts:[], localDraftId:null};};
    Object.assign(options.computed, {
      workspaceFamilies(){return families;},
      workspaceTitle(){return families.find(f=>f.value===this.workspaceFamily)?.label || '全部项目';},
      workspaceDescription(){return families.find(f=>f.value===this.workspaceFamily)?.description || '';},
      sidebarProjectView(){return ({all:'workbench',background:'due-diligence',research:'research',ai:'ai-services'})[this.workspaceFamily] || 'workbench';},
      workspaceTypes(){return families.filter(f=>this.workspaceFamily==='all'||f.value===this.workspaceFamily).flatMap(f=>f.types||[]);},
      ddTypes(){return families.find(f=>f.value===this.form.workspaceFamily)?.types || families[1].types;},
      formReportOptions(){return reports[this.form.ddType] || [];},
      executionAvailable(){return this.ddTypes.includes(this.form.ddType) && this.formReportOptions.length>0;},
      capabilityNotice(){return this.form.ddType==='AI应用建设'?'AI 应用建设尚未接入执行接口，目前仅可保存本机草稿，不会启动报告或应用建设。':`${this.form.ddType}专用报告尚未接入，目前仅可保存本机草稿，不会调用其他报告流程代替。`;},
      formFocusOptions(){return !this.executionAvailable||this.form.workspaceFamily!=='background'?[]:this.form.targetType==='company'?['高管背景','创始人背景','标的公司背景']:this.form.targetType==='person'?['高管背景','创始人背景']:[];},
      workspaceDrafts(){return this.localProjectDrafts.filter(d=>(this.workspaceFamily==='all'||d.form.workspaceFamily===this.workspaceFamily)&&(!this.workspaceTypeFilter||d.form.ddType===this.workspaceTypeFilter));},
      workspaceReportOptions(){
        const types=this.workspaceTypeFilter?[this.workspaceTypeFilter]:this.workspaceTypes;
        const values=new Set(types.flatMap(type=>(reports[type]||[]).map(r=>r.value)));
        for(const project of this.stageProjects){if(!this.workspaceTypeFilter||this.projectBusinessType(project)===this.workspaceTypeFilter)values.add(project.target_type);}
        return [...values].filter(value=>['company','person','industry'].includes(value)).map(value=>({value,label:this.reportTypeLabel(value,this.workspaceTypeFilter)}));
      },
      pageTitle(){return this.isTaskWorkspace ? this.activeView==='review'?'项目复核':this.activeView==='sources'?'溯源库':this.workspaceTitle : computed.pageTitle.call(this);},
      taskSectionTitle(){return this.workspaceTitle;},
      taskSectionHint(){return this.workspaceDescription;},
      stageProjects(){
        const rows=this.projects.filter(p=>this.workspaceFamily==='all'||this.projectFamily(p)===this.workspaceFamily);
        return this.activeView==='review'?rows.filter(p=>this.projectWorkflowStage(p)==='review'):rows;
      },
      filteredProjects(){return computed.filteredProjects.call(this).filter(p=>!this.workspaceTypeFilter||this.projectBusinessType(p)===this.workspaceTypeFilter);},
      hasTaskFilters(){return computed.hasTaskFilters.call(this)||!!this.workspaceTypeFilter;},
      taskEmptyText(){return this.hasTaskFilters?'暂无符合筛选条件的项目，请调整或清空筛选':'当前分类暂无项目';},
      activeTaskFilterCount(){return computed.activeTaskFilterCount.call(this)+Number(!!this.workspaceTypeFilter);}
    });
    Object.assign(options.watch, {
      workspaceTypeFilter(){this.taskPage=1;if(!this.workspaceReportOptions.some(r=>r.value===this.taskTargetFilter))this.taskTargetFilter='';},
      'form.ddType'(){this.syncFormReport();},
      'form.targetType'(value){
        const defaults={company:this.companyChapterVersion?this.modulesByTarget.company.filter(x=>x.selectable!==false).map(x=>x.value):newResearchForm().modules,person:this.modulesByTarget.person.map(x=>x.value),industry:this.modulesByTarget.industry.map(x=>x.value)};
        this.form.modules=defaults[value] || defaults.company;
        this.form.targetContext='';this.form.personContext='';this.form.personAliases='';
        if(value==='person'||value==='industry'){this.form.industry='';this.form.region='';}
        this.form.focusAreas=(this.form.focusAreas||[]).filter(x=>this.formFocusOptions.includes(x));
      }
    });
    Object.assign(options.methods, {
      projectFamily(project){return this.workspaceMetaErrors[project.id]?'unclassified':familyOf(project,this.workspaceIntakes[project.id]||this.projectDetails[project.id]?.intake);},
      projectBusinessType(project){
        if(this.workspaceMetaErrors[project.id])return '分类待确认';
        const type=(this.workspaceIntakes[project.id]||this.projectDetails[project.id]?.intake)?.research_type;
        return families.some(f=>f.types?.includes(type))?type:project.target_type==='industry'?'CDD项目':'BDD项目';
      },
      reportTypeLabel(value,type){return reports[type]?.find(r=>r.value===value)?.label||({company:'公司报告',person:'人物报告',industry:'行业报告'})[value]||'历史报告';},
      projectReportLabel(project){
        const type=this.projectBusinessType(project);
        return this.reportTypeLabel(project.target_type,type)+(pendingTypes.includes(type)?'（沿用旧流程）':reports[type]&&!reports[type].some(r=>r.value===project.target_type)?'（历史组合）':'');
      },
      workspaceCount(family){return this.projects.filter(p=>family==='all'||this.projectFamily(p)===family).length;},
      projectTab(project){return this.projectDetailTabs[project.id] || 'overview';},
      changeFormFamily(value){this.form.ddType=value==='background'?'BDD项目':families.find(f=>f.value===value)?.types?.[0]||'BDD项目';this.syncFormReport();},
      clearReportObject(){this.form.companyName='';this.form.identifier='';this.form.targetContext='';this.form.personContext='';this.form.personAliases='';},
      syncFormReport(){
        const choices=this.formReportOptions;
        if(choices.length&&!choices.some(r=>r.value===this.form.targetType)){
          this.form.targetType=choices[0].value;
          this.clearReportObject();
        }
        this.form.focusAreas=(this.form.focusAreas||[]).filter(x=>this.formFocusOptions.includes(x));
      },
      async setProjectTab(project, tab){this.projectDetailTabs[project.id]=tab;if(tab==='results'&&this.reviewProjectId&&this.reviewProjectId!==project.id&&!this.reviewWriteBusy)this.clearReviewSelection();},
      resetTaskFilters(){previous.resetTaskFilters.call(this);this.workspaceTypeFilter='';},
      switchView(view){
        const category=({workbench:'all','due-diligence':'background',research:'research','ai-services':'ai'})[view];
        if(category){this.workspaceFamily=category;this.resetTaskFilters();view='tasks';}
        if(view==='submit'){this.openProjectCreate();return;}
        if(['intake','deliverables'].includes(view))view='tasks';
        return previous.switchView.call(this,view);
      },
      async loadProjects(){
        await previous.loadProjects.call(this);
        const token=this.token, sequence=++this.workspaceMetaSequence;
        const pending=this.projects.filter(p=>!this.workspaceIntakes[p.id]);
        this.workspaceMetaLoading=!!pending.length;
        let next=0;
        const worker=async()=>{
          while(next<pending.length&&token===this.token&&sequence===this.workspaceMetaSequence){
            const project=pending[next++];
            try{
              const data=await this.readJSON(`/research/projects/${project.id}/run-intake`,'读取项目分类失败');
              if(token!==this.token||sequence!==this.workspaceMetaSequence)return;
              this.workspaceIntakes[project.id]=data.intake||{};delete this.workspaceMetaErrors[project.id];
            }catch(error){if(token===this.token&&sequence===this.workspaceMetaSequence)this.workspaceMetaErrors[project.id]=error.message;}
          }
        };
        await Promise.all(Array.from({length:Math.min(3,pending.length)},worker));
        if(token===this.token&&sequence===this.workspaceMetaSequence){this.workspaceMetaLoading=false;this.loadLocalProjectDrafts();}
      },
      async loadProjectDetail(project, opts){const result=await previous.loadProjectDetail.call(this,project,opts);if(result?.intake){this.workspaceIntakes[project.id]=result.intake;delete this.workspaceMetaErrors[project.id];}return result;},
      async viewProject(project){
        if(this.activeView!=='tasks'){this.workspaceFamily='all';this.switchView('tasks');await this.$nextTick();}
        this.$nextTick(()=>this.$refs.taskTable?.toggleRowExpansion(this.projects.find(p=>p.id===project.id)||project,true));
        try{await this.loadProjectDetail(project);}catch(_){/* Existing inline error retains its retry action. */}
      },
      async openTaskStage(project,view){
        if(view==='intake')return this.openClientRequirements(project);
        await this.viewProject(project);
        if(view==='review'){this.projectDetailTabs[project.id]='results';await this.selectReviewProject(project);}
      },
      async openHomeProject(project){this.workspaceFamily='all';return previous.openHomeProject.call(this,project);},
      openHomeTaskFilter(key){this.workspaceFamily='all';return previous.openHomeTaskFilter.call(this,key);},
      openProjectCreate(family=this.workspaceFamily){
        this.localDraftId=null;this.form=newResearchForm();this.form.workspaceFamily=family==='all'?'background':family;
        this.form.ddType=this.form.workspaceFamily==='background'?'BDD项目':families.find(f=>f.value===this.form.workspaceFamily)?.types?.[0]||'BDD项目';
        this.form.targetType=this.formReportOptions[0]?.value||'company';this.form.focusAreas=this.form.targetType==='company'&&this.form.workspaceFamily==='background'?['标的公司背景']:[];
        this.form.modules=this.form.targetType==='company'&&!this.companyChapterVersion?newResearchForm().modules:this.modulesByTarget[this.form.targetType].filter(x=>x.selectable!==false).map(x=>x.value);
        this.selectedFiles=[];this.clientRequirementFiles=[];this.taskCreateOpen=true;this.mobileNavOpen=false;
      },
      async submitTask(){
        if(!this.form.projectName.trim())return ElementPlus.ElMessage.warning('请填写项目名称');
        if(!this.form.companyName.trim())return ElementPlus.ElMessage.warning('请填写主要调查或研究对象');
        if(!this.ddTypes.includes(this.form.ddType))return ElementPlus.ElMessage.warning('请选择当前项目分类下的业务类型');
        if(!this.executionAvailable)return this.saveLocalProjectDraft();
        if(!this.formReportOptions.some(r=>r.value===this.form.targetType))return ElementPlus.ElMessage.warning('请选择当前业务下适用的报告类型');
        const family=this.form.workspaceFamily;
        const questions=this.splitLines(this.form.focusQuestions || this.form.keyQuestions).filter(q=>!q.startsWith('重点模块：'));
        if(family==='background')questions.push(...(this.form.focusAreas||[]).filter(x=>this.formFocusOptions.includes(x)).map(x=>'重点模块：'+x));
        this.form.focusQuestions=questions.join('\n');
        await previous.submitTask.call(this);
        // The original submitter resets the form on success. Reload only saved server metadata.
        if(!this.taskCreateOpen){this.workspaceFamily=family;await this.loadProjects().catch(()=>null);}
      },
      localDraftKey(){return this.currentUser?.username?`project-workspace:drafts:${encodeURIComponent(this.currentUser.username)}`:null;},
      loadLocalProjectDrafts(){
        this.localProjectDrafts=[];const key=this.localDraftKey();if(!key)return;
        try{const parsed=JSON.parse(localStorage.getItem(key)||'[]');if(Array.isArray(parsed))this.localProjectDrafts=parsed.filter(d=>d&&typeof d.id==='string'&&pendingTypes.includes(d.form?.ddType)&&typeof d.form.projectName==='string').map(d=>({...d,form:{...d.form,workspaceFamily:familyOf(null,{research_type:d.form.ddType})}}));}catch(_){/* A corrupt browser draft cannot affect server projects. */}
      },
      saveLocalProjectDraft(){
        const key=this.localDraftKey();if(!key)return ElementPlus.ElMessage.error('请重新登录后保存草稿');
        const draft={id:this.localDraftId||crypto.randomUUID(),updated_at:new Date().toISOString(),form:JSON.parse(JSON.stringify(this.form))};
        const records=[draft,...this.localProjectDrafts.filter(d=>d.id!==draft.id)];
        try{localStorage.setItem(key,JSON.stringify(records));this.localProjectDrafts=records;this.localDraftId=null;this.taskCreateOpen=false;this.workspaceFamily=draft.form.workspaceFamily;this.workspaceTypeFilter='';this.taskTargetFilter='';this.switchView('tasks');ElementPlus.ElMessage.success('已保存到当前账号的本机草稿，尚未提交服务器');}
        catch(_){ElementPlus.ElMessage.error('本机存储不可用，草稿尚未保存，请保留当前内容');}
      },
      editLocalProjectDraft(draft){this.form={...newResearchForm(),...JSON.parse(JSON.stringify(draft.form))};this.localDraftId=draft.id;this.selectedFiles=[];this.clientRequirementFiles=[];this.taskCreateOpen=true;},
      async deleteLocalProjectDraft(draft){
        const key=this.localDraftKey(),token=this.token;if(!key)return;
        try{await ElementPlus.ElMessageBox.confirm('仅删除此浏览器中的草稿，不影响服务器项目。','删除本机草稿',{type:'warning'});}catch(_){return;}
        if(token!==this.token||key!==this.localDraftKey())return;
        const records=this.localProjectDrafts.filter(d=>d.id!==draft.id);
        try{localStorage.setItem(key,JSON.stringify(records));this.localProjectDrafts=records;}catch(_){ElementPlus.ElMessage.error('删除失败，请重试');}
      },
      handleLogout(){++this.workspaceMetaSequence;this.workspaceIntakes={};this.workspaceMetaErrors={};this.workspaceMetaLoading=false;this.localProjectDrafts=[];this.localDraftId=null;this.projectDetailTabs={};this.workspaceFamily='all';return previous.handleLogout.call(this);}
    });
  }
  return {install,families,familyOf};
})();
