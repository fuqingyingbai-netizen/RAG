/* Tiptap is vendored locally. Document JSON and image bytes never go to an editor service. */
(() => {
  let enginePromise;
  const imageLanes=[Promise.resolve(),Promise.resolve()];let nextImageLane=0;
  function engine() {
    if (window.KnowledgeNoteEngine) return Promise.resolve(window.KnowledgeNoteEngine);
    if (!enginePromise) enginePromise = new Promise((resolve,reject) => {
      const script=document.createElement('script');script.src=new URL('knowledge-note-engine.a6240990fbc8.js',document.baseURI).href;
      script.onload=()=>resolve(window.KnowledgeNoteEngine);script.onerror=()=>{script.remove();enginePromise=null;reject(Error('编辑器资源加载失败，请检查网络后重试。'));};document.head.append(script);
    });
    return enginePromise;
  }
  const clone=value=>JSON.parse(JSON.stringify(value));
  window.KnowledgeNoteEditor = {
    components:{KnowledgeGlassSurface:window.KnowledgeGlassSurface||{}},
    props:{noteId:String,fetchApi:Function,username:String},
    emits:['close','changed'],
    data:()=>({open:true,loading:true,loadError:'',note:null,title:'',editor:null,saveState:'saved',error:'',busy:false,
      uploads:[],helpOpen:false,historyOpen:false,events:[],historyError:'',recoverable:null,format:'paragraph',tick:0,
      assets:0,words:0,publishing:false,exporting:false,lastSaved:'',conflict:false,indexPoll:0}),
    computed:{
      dirty(){return this.saveState!=='saved';},
      saveLabel(){return this.saveState==='saving'?'正在保存…':this.saveState==='error'?'保存失败，内容仍在本窗口':this.saveState==='conflict'?'其他窗口已有更新':this.saveState==='pending'?'有修改，等待保存':'草稿已保存';},
      indexLabel(){const n=this.note;if(!n)return '';if(n.index_state==='failed')return '索引失败 · 可重试';if(['queued','uploading','parsing','indexing'].includes(n.index_state))return '已提交发布 · 正在建立索引';if(n.indexed_revision)return n.has_unpublished_changes?'有未发布修改 · 已发布版本仍可检索':'已发布 · 可检索';return '未发布 · 仅项目创建者和管理员可见';},
      blocked(){return this.loading||this.busy||this.publishing||this.conflict||!!this.recoverable||this.uploads.some(u=>u.state!=='done');},
      empty(){return !this.words&&!this.assets;},
    },
    async mounted(){
      this.urls=new Map();this.images=new Map();this.sequence=0;this.destroyed=false;
      this.leaveHandler=event=>{if(this.dirty||this.recoverable||this.uploads.some(u=>u.state!=='done')){event.preventDefault();event.returnValue='';}};
      window.addEventListener('beforeunload',this.leaveHandler);await this.load();
      this.indexPoll=setInterval(()=>this.pollIndex(),5000);
    },
    beforeUnmount(){this.destroyed=true;clearInterval(this.indexPoll);clearTimeout(this.saveTimer);window.removeEventListener('beforeunload',this.leaveHandler);this.editor?.destroy();for(const url of this.urls?.values()||[])URL.revokeObjectURL(url);},
    methods:{
      async request(path,options={}){const response=await this.fetchApi('/company-knowledge/notes/'+encodeURIComponent(this.noteId)+path,options);if(!response.ok){let detail;try{detail=(await response.json()).detail;}catch{}const error=Error(typeof detail==='string'?detail:'操作失败，请重试。');error.status=response.status;throw error;}return response;},
      key(){return 'knowledgeNoteRecovery:'+this.username+':'+this.noteId;},
      localBackup(){if(!this.editor||!this.note)return;try{localStorage.setItem(this.key(),JSON.stringify({revision:this.note.revision,title:this.title,content:this.editor.getJSON(),updated_at:new Date().toISOString()}));}catch{ /* Server save remains authoritative. Explicit local export is always available. */ }},
      clearBackup(){try{localStorage.removeItem(this.key());}catch{}},
      async load(){
        this.loading=true;this.loadError='';
        try{
          const [runtime,response]=await Promise.all([engine(),this.request('')]);const note=await response.json();if(this.destroyed)return;
          this.note=note;this.title=note.title;
          if(!note.can_manage)throw Error('你可以阅读已发布内容；编辑仅限项目创建者和管理员。');
          await this.$nextTick();this.editor?.destroy();
          const component=this;
          const NoteImage=runtime.Image.extend({
            draggable:true,
            addAttributes(){return {assetId:{default:''},width:{default:80},caption:{default:''},alt:{default:''},ocrText:{default:''}};},
            parseHTML(){return [{tag:'figure[data-note-image]',getAttrs:node=>({assetId:node.dataset.noteImage,width:Number(node.dataset.width)||80,caption:node.querySelector('figcaption')?.textContent||''})}];},
            renderHTML({node}){return ['figure',{'data-note-image':node.attrs.assetId,'data-width':node.attrs.width},['figcaption',{},node.attrs.caption||'图片']];},
            addNodeView(){return args=>component.imageView(args);},
          });
          const editor=new runtime.Editor({element:this.$refs.editorHost,content:clone(note.content),
            extensions:[runtime.StarterKit.configure({heading:{levels:[1,2,3]},link:{openOnClick:false},trailingNode:{node:'paragraph'}}),NoteImage,
              runtime.Table.configure({resizable:false,allowTableNodeSelection:true}),runtime.TableRow,runtime.TableHeader,runtime.TableCell],
            editorProps:{attributes:{class:'kn-prose',role:'textbox','aria-label':'笔记正文','aria-multiline':'true',spellcheck:'false'},
              handlePaste:(view,event)=>{const files=[...(event.clipboardData?.items||[])].filter(item=>item.kind==='file').map(item=>item.getAsFile()).filter(Boolean);if(files.length){event.preventDefault();this.addFiles(files);return true;}return false;},
              handleDrop:(view,event,_slice,moved)=>{const files=[...(event.dataTransfer?.files||[])];if(files.length&&!moved){event.preventDefault();const point=view.posAtCoords({left:event.clientX,top:event.clientY});if(point)view.dispatch(view.state.tr.setSelection(runtime.Selection.near(view.state.doc.resolve(point.pos))));this.addFiles(files);return true;}return false;},
              transformPastedHTML:html=>{const doc=new DOMParser().parseFromString(html,'text/html');if(doc.querySelector('img')){doc.querySelectorAll('img').forEach(img=>img.replaceWith(doc.createTextNode('[外部图片未导入，请粘贴截图或上传原图]')));this.error='粘贴的文字已保留。外部网页图片请下载后插入，避免图片失效。';}return doc.body.innerHTML;},
            },
            onUpdate:()=>{this.changed();this.count();},onSelectionUpdate:()=>{this.tick++;this.format=this.blockType();},
          });
          this.editor=Vue.markRaw(editor);this.count();this.saveState='saved';this.lastSaved=note.updated_at;
          try{const backup=JSON.parse(localStorage.getItem(this.key())||'null');if(backup&&JSON.stringify({title:backup.title,content:backup.content})!==JSON.stringify({title:note.title,content:note.content}))this.recoverable=backup;else this.clearBackup();}catch{}
        }catch(error){this.loadError=error.message;}finally{this.loading=false;}
      },
      blockType(){for(const level of [1,2,3])if(this.editor?.isActive('heading',{level}))return 'h'+level;return 'paragraph';},
      setBlock(){const chain=this.editor.chain().focus();if(this.format==='paragraph')chain.setParagraph().run();else chain.setHeading({level:Number(this.format.slice(1))}).run();},
      active(name){this.tick;return !!this.editor?.isActive(name);},
      command(name,attrs){if(!this.editor)return;this.editor.chain().focus()[name](attrs).run();this.tick++;},
      table(action){if(this.editor?.isActive('table'))this.command(action);},
      count(){if(!this.editor)return;this.words=this.editor.getText().replace(/\s/g,'').length;let count=0;this.editor.state.doc.descendants(node=>{if(node.type.name==='image')count++;});this.assets=count;},
      changed(){if(this.loading||this.destroyed)return;this.sequence++;this.localBackup();if(this.conflict)return;this.saveState='pending';clearTimeout(this.saveTimer);this.saveTimer=setTimeout(()=>this.save().catch(()=>{}),900);},
      async save(){
        clearTimeout(this.saveTimer);if(this.conflict)throw Error('请先处理版本冲突。');if(this.recoverable)throw Error('请先处理待恢复的本机副本。');
        if(this.savePromise){await this.savePromise;return this.save();}if(this.saveState==='saved')return this.note;
        const version=this.sequence,title=this.title.trim()||'未命名笔记',content=this.editor.getJSON();this.saveState='saving';
        this.savePromise=(async()=>{
          try{const response=await this.request('',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:this.note.revision,title,content})});const note=await response.json();if(this.destroyed)return;
            this.note=note;this.lastSaved=note.updated_at;
            if(version===this.sequence){this.saveState='saved';this.error='';this.clearBackup();}else {this.saveState='pending';this.localBackup();}
            this.$emit('changed');return note;
          }catch(error){if(error.status===409){this.conflict=true;this.saveState='conflict';}else this.saveState='error';this.error=error.message;this.localBackup();throw error;}
          finally{this.savePromise=null;}
        })();
        const result=await this.savePromise;if(this.saveState==='pending')return this.save();return result;
      },
      restoreLocal(){const backup=this.recoverable;if(!backup)return;this.recoverable=null;this.title=backup.title;this.editor.commands.setContent(backup.content,{emitUpdate:false});this.count();
        if(backup.revision!==this.note.revision){this.conflict=true;this.saveState='conflict';this.error='已恢复本窗口内容。服务器已有较新版本，请下载本机副本、查看服务器版本后再合并。';this.localBackup();}
        else this.changed();
      },
      async discardRecovery(){this.recoverable=null;this.clearBackup();this.conflict=false;this.error='';await this.load();},
      async reloadServer(){if(!window.confirm('载入服务器版本将替换本窗口正文。请先下载本机副本留存；确定继续吗？'))return;this.clearBackup();this.conflict=false;this.recoverable=null;this.error='';await this.load();},
      downloadLocal(){this.download(new Blob([JSON.stringify({title:this.title,content:this.editor?.getJSON(),baseRevision:this.note?.revision},null,2)],{type:'application/json'}),(this.title.trim()||'笔记')+'-本机恢复副本.json');},
      async close(done){
        if(this.uploads.some(u=>u.state!=='done')){this.error='还有图片正在上传或等待重试。请完成上传，或移除失败项后再关闭。';return;}
        try{if(this.conflict||this.recoverable)throw Error('尚有未处理的本机内容。');if(this.editor&&this.dirty)await this.save();this.open=false;this.$emit('close');if(typeof done==='function')done();}
        catch{if(window.confirm('内容尚未全部保存到服务器。本机已尝试保留恢复副本，建议先下载本机副本。仍然关闭吗？')){this.localBackup();this.open=false;this.$emit('close');if(typeof done==='function')done();}}
      },
      async addFiles(files){
        const images=files.filter(file=>/^image\/(png|jpeg|webp)$/.test(file.type));if(images.length!==files.length)this.error='插图支持 PNG、JPG 和 WebP；其他文件请使用项目中的“上传文件”。';
        for(const file of images){if(file.size>12*1024*1024){this.error='图片“'+file.name+'”超过 12 MB，请压缩后插入。';continue;}const item=Vue.markRaw({id:crypto.randomUUID(),file,state:'pending',error:''});this.uploads.push(item);await this.uploadImage(item);}
        if(this.$refs.imageInput)this.$refs.imageInput.value='';
      },
      async uploadImage(item){
        item.state='uploading';item.error='';this.uploads=[...this.uploads];
        try{const data=new FormData();data.append('file',item.file);const response=await this.request('/images',{method:'POST',body:data});const asset=await response.json();if(this.destroyed)return;
          // Insert at the current caret without discarding edits made during upload.
          const inserted=this.editor.chain().focus().setImage({assetId:asset.id,width:80,caption:'',alt:item.file.name.replace(/\.[^.]+$/,''),ocrText:''}).run();
          if(!inserted)throw Error('图片已保存，请将光标移到正文位置后重试插入。');
          let position=null,distance=Infinity;const caret=this.editor.state.selection.from;
          this.editor.state.doc.descendants((node,pos)=>{if(node.type.name==='image'&&node.attrs.assetId===asset.id&&Math.abs(pos-caret)<distance){position=pos;distance=Math.abs(pos-caret);}});
          this.continueAfterImage(position);item.state='done';this.error='';
        }catch(error){item.state='error';item.error=error.message;}finally{this.uploads=[...this.uploads];}
      },
      removeUpload(item){this.uploads=this.uploads.filter(value=>value!==item);},
      continueAfterImage(position){
        const editor=this.editor;if(!editor||typeof position!=='number')return;
        const image=editor.state.doc.nodeAt(position);if(image?.type.name!=='image')return;
        const after=position+image.nodeSize,tr=editor.state.tr,next=tr.doc.resolve(after).nodeAfter;
        // Reuse an empty following paragraph; preserve existing text and all other images.
        if(next?.type.name!=='paragraph'||next.content.size)tr.insert(after,editor.schema.nodes.paragraph.create());
        tr.setSelection(window.KnowledgeNoteEngine.Selection.near(tr.doc.resolve(after+1))).scrollIntoView();
        editor.view.dispatch(tr);editor.view.focus();
      },
      async assetUrl(id){
        if(this.urls.has(id))return this.urls.get(id);if(this.images.has(id))return this.images.get(id);
        const lane=nextImageLane++%imageLanes.length;
        const promise=imageLanes[lane].then(async()=>{if(this.destroyed)throw Error('编辑器已关闭');const response=await this.request('/images/'+encodeURIComponent(id));const url=URL.createObjectURL(await response.blob());if(this.destroyed){URL.revokeObjectURL(url);throw Error('编辑器已关闭');}this.urls.set(id,url);return url;});imageLanes[lane]=promise.catch(()=>{});
        this.images.set(id,promise);try{return await promise;}finally{this.images.delete(id);}
      },
      imageView({node,editor,getPos}){
        let current=node,disposed=false;const figure=document.createElement('figure');figure.className='kn-image';figure.contentEditable='false';figure.style.width=node.attrs.width+'%';
        const frame=document.createElement('div');frame.className='kn-image-frame';const img=document.createElement('img');img.draggable=false;img.alt=node.attrs.alt||'笔记图片';const status=document.createElement('button');status.type='button';status.className='kn-image-status';status.textContent='正在加载图片…';frame.append(img,status);
        const handle=document.createElement('button');handle.type='button';handle.className='kn-image-resize';handle.setAttribute('aria-label','拖动调整图片宽度');handle.title='拖动调整大小';handle.textContent='↔';frame.append(handle);
        const controls=document.createElement('div');controls.className='kn-image-controls';const width=document.createElement('select');width.setAttribute('aria-label','图片宽度');
        for(const value of [20,25,40,60,80,100]){const option=document.createElement('option');option.value=String(value);option.textContent=value+'%';width.append(option);}
        const customWidth=document.createElement('option');width.append(customWidth);
        const syncWidth=value=>{const custom=![20,25,40,60,80,100].includes(value);customWidth.hidden=!custom;customWidth.value=String(value);customWidth.textContent=value+'%';width.value=String(value);};syncWidth(node.attrs.width);
        const ocr=document.createElement('button');ocr.type='button';ocr.textContent='识别图片文字';const remove=document.createElement('button');remove.type='button';remove.textContent='移除图片';controls.append(width,ocr,remove);
        const caption=document.createElement('input');caption.className='kn-image-caption';caption.placeholder='添加图片说明（参与检索）';caption.setAttribute('aria-label','图片说明');caption.maxLength=1000;caption.value=node.attrs.caption;
        const details=document.createElement('details');details.className='kn-image-ocr';const summary=document.createElement('summary');summary.textContent='图片识别文字 · 请核对';const text=document.createElement('textarea');text.value=node.attrs.ocrText;text.maxLength=20000;text.setAttribute('aria-label','图片识别文字');text.placeholder='点击“识别图片文字”后可在这里校正，也可手动补充。';details.append(summary,text);details.hidden=!node.attrs.ocrText;
        const write=document.createElement('button');write.type='button';write.className='kn-image-continue';write.textContent='在图片下继续写正文 ↓';write.onclick=()=>this.continueAfterImage(getPos());
        figure.append(frame,controls,caption,details,write);
        const patch=attrs=>{if(disposed)return;const position=getPos();if(typeof position==='number')editor.view.dispatch(editor.state.tr.setNodeMarkup(position,undefined,{...current.attrs,...attrs}));};
        const load=async()=>{status.hidden=false;status.textContent='正在加载图片…';try{const url=await this.assetUrl(current.attrs.assetId);if(!disposed){img.src=url;status.hidden=true;}}catch{if(!disposed){status.textContent='图片加载失败，点击重试';status.hidden=false;}}};status.onclick=load;load();
        width.onchange=()=>patch({width:Number(width.value)});caption.oninput=()=>patch({caption:caption.value});text.oninput=()=>patch({ocrText:text.value});
        caption.onkeydown=event=>{if(event.key==='Enter'&&!event.isComposing){event.preventDefault();this.continueAfterImage(getPos());}};
        remove.onclick=()=>{const pos=getPos();if(typeof pos==='number')editor.chain().focus().deleteRange({from:pos,to:pos+current.nodeSize}).run();};
        ocr.onclick=async()=>{if(current.attrs.ocrText&&!window.confirm('重新识别会替换当前图片文字，已校正的内容可通过撤销恢复。继续吗？'))return;ocr.disabled=true;ocr.textContent='正在识别…';try{const response=await this.request('/images/'+current.attrs.assetId+'/ocr',{method:'POST'});const result=await response.json();if(!disposed){details.hidden=false;details.open=true;if(result.text){patch({ocrText:result.text});text.value=result.text;}else this.error=result.message;}}catch(error){this.error=error.message;}finally{ocr.disabled=false;ocr.textContent='识别图片文字';}};
        handle.onpointerdown=event=>{event.preventDefault();handle.setPointerCapture(event.pointerId);const start=event.clientX,initial=figure.getBoundingClientRect().width,parent=figure.parentElement.getBoundingClientRect().width;let percent=current.attrs.width;
          handle.onpointermove=move=>{percent=Math.max(20,Math.min(100,Math.round((initial+move.clientX-start)/parent*100)));figure.style.width=percent+'%';};
          handle.onpointerup=()=>{handle.onpointermove=null;handle.onpointerup=null;patch({width:percent});};handle.onpointercancel=()=>{handle.onpointermove=null;figure.style.width=current.attrs.width+'%';};};
        return {dom:figure,stopEvent:event=>!!event.target.closest('input,textarea,button,select,details'),ignoreMutation:()=>true,
          update:next=>{if(next.type!==current.type||next.attrs.assetId!==current.attrs.assetId)return false;current=next;figure.style.width=current.attrs.width+'%';syncWidth(current.attrs.width);if(document.activeElement!==caption)caption.value=current.attrs.caption;if(document.activeElement!==text)text.value=current.attrs.ocrText;details.hidden=!current.attrs.ocrText&&!details.open;return true;},destroy:()=>{disposed=true;}};
      },
      async publish(){if(this.blocked)return;if(this.empty){this.error='请先写正文或插入图片，再发布笔记。仅填写标题不会发布。';this.editor?.commands.focus();return;}this.publishing=true;this.error='';try{await this.save();const response=await this.request('/publish',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:this.note.revision})});this.note=await response.json();this.$emit('changed');}catch(error){this.error=error.message;}finally{this.publishing=false;}},
      async pollIndex(){if(this.destroyed||!this.note||this.loading||this.dirty||this.publishing||this.busy)return;try{const response=await this.request('');const next=await response.json();if(this.destroyed)return;if(next.revision!==this.note.revision){this.recoverable={revision:this.note.revision,title:this.title,content:this.editor.getJSON()};this.error='服务器版本已有更新，当前内容仍保留。请先留存本机副本，再载入服务器版本。';}else {const changed=next.index_state!==this.note.index_state;this.note=next;if(changed)this.$emit('changed');}}catch{/* Autosave and explicit operations display actionable errors. */}},
      download(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);},
      async exportFile(format){if(this.blocked||this.exporting)return;this.exporting=true;this.error='';try{await this.save();const response=await this.request('/export?draft=true&format='+format);const blob=await response.blob();this.download(blob,decodeURIComponent(response.headers.get('X-Download-Filename')||'笔记'+(format==='docx'?'.docx':'.zip')));}catch(error){this.error=error.message;}finally{this.exporting=false;}},
      async showHistory(){this.historyOpen=!this.historyOpen;if(!this.historyOpen)return;try{const response=await this.request('/history');this.events=(await response.json()).events.filter(event=>['note.create','note.save','note.publish'].includes(event.action));this.historyError='';}catch(error){this.historyError=error.message;}},
      historyLabel(action){return {'note.create':'创建草稿','note.save':'保存修改','note.publish':'发布版本'}[action]||action;},
      historyContent(change){return JSON.stringify(change,null,2);},
    },
    template:`<el-dialog v-model="open" title="图文笔记" width="min(1180px, 96vw)" class="ckb-dialog kn-dialog ckb-reveal-dialog" modal-class="ckb-glass-overlay" append-to-body :close-on-click-modal="false" :before-close="close" :close-on-press-escape="false">
      <template #header="{titleId,titleClass}"><div class="kn-window-heading"><span class="kn-window-icon" aria-hidden="true"><i class="fa-solid fa-pen-nib"></i></span><div><strong :id="titleId" :class="titleClass">图文笔记</strong><small>记录洞察 · 沉淀经验</small></div></div></template>
      <knowledge-glass-surface v-if="$options.components.KnowledgeGlassSurface.template"/>
      <div v-if="loading" class="kn-loading" role="status">正在打开你的写作空间…</div><div v-if="loadError" class="kn-error" role="alert">{{loadError}} <button @click="load">重新加载</button></div>
      <div v-show="!loading&&!loadError" class="kn-workspace">
        <header class="kn-top"><div class="kn-top-label"><span>EXPERIENCE / NOTES</span><strong>把经验，写成下一次的起点。</strong></div><div class="kn-save-status" :data-state="saveState" role="status"><i></i>{{saveLabel}}<small v-if="lastSaved && saveState==='saved'">{{new Date(lastSaved).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})}}</small></div>
          <button class="ckb-button ckb-button-outline" :disabled="blocked" @click="save().catch(()=>{})">保存</button><button class="ckb-button ckb-button-primary" :disabled="blocked||empty" :title="empty ? '请先写正文或插入图片，再发布笔记' : '保存并发布当前笔记'" @click="publish">{{publishing?'正在发布…':note?.index_state==='failed'&&!note?.has_unpublished_changes?'重试索引':'发布笔记'}}</button></header>
        <div v-if="recoverable" class="kn-notice"><span>发现本机保留的内容。服务器草稿仍完整保留，请选择使用哪一份。</span><button @click="restoreLocal">恢复本机内容</button><button @click="discardRecovery">使用服务器草稿</button></div>
        <div v-if="error" class="kn-error" role="alert">{{error}}<button v-if="!conflict && saveState==='error'" @click="save().catch(()=>{})">重试保存</button><button v-if="conflict" @click="reloadServer">载入服务器版本</button><button v-if="dirty||conflict" @click="downloadLocal">下载本机副本</button></div>
        <div class="kn-body"><div class="kn-writing">
          <div class="kn-toolbar" role="toolbar" aria-label="正文格式工具"><select v-model="format" aria-label="段落格式" @change="setBlock"><option value="paragraph">正文</option><option value="h1">一级标题</option><option value="h2">二级标题</option><option value="h3">三级标题</option></select>
            <button title="加粗 Ctrl+B" aria-label="加粗" :aria-pressed="active('bold')" @click="command('toggleBold')"><b>B</b></button><button title="斜体 Ctrl+I" aria-label="斜体" :aria-pressed="active('italic')" @click="command('toggleItalic')"><i>I</i></button><button title="下划线 Ctrl+U" aria-label="下划线" :aria-pressed="active('underline')" @click="command('toggleUnderline')"><u>U</u></button><span class="kn-divider"></span>
            <button title="无序列表" :aria-pressed="active('bulletList')" @click="command('toggleBulletList')">• 列表</button><button title="有序列表" :aria-pressed="active('orderedList')" @click="command('toggleOrderedList')">1. 列表</button><button title="引用" :aria-pressed="active('blockquote')" @click="command('toggleBlockquote')">引用</button><button title="插入三行三列表格" @click="command('insertTable',{rows:3,cols:3,withHeaderRow:true})">▦ 表格</button><button @click="$refs.imageInput.click()">＋ 图片</button><span class="kn-divider"></span><button title="撤销 Ctrl+Z" aria-label="撤销" @click="command('undo')">↶</button><button title="重做 Ctrl+Shift+Z" aria-label="重做" @click="command('redo')">↷</button>
            <input ref="imageInput" type="file" accept="image/png,image/jpeg,image/webp" multiple hidden @change="addFiles([...$event.target.files])"></div>
          <div v-if="active('table')" class="kn-table-tools"><span>表格操作</span><button @click="table('addRowAfter')">下方加行</button><button @click="table('addColumnAfter')">右侧加列</button><button @click="table('deleteRow')">删行</button><button @click="table('deleteColumn')">删列</button><button @click="table('mergeOrSplit')">合并 / 拆分</button><button @click="table('deleteTable')">删除表格</button></div>
          <div class="kn-paper-scroll"><div class="kn-paper"><input v-model="title" class="kn-title" aria-label="笔记标题" placeholder="给这份经验起个名字" maxlength="200" @input="changed"><div ref="editorHost"></div><p v-if="!words&&!assets" class="kn-writing-hint">请先写正文或插入图片，再发布笔记。草稿已保存，仅填写标题不会发布。</p></div></div>
          <div v-if="uploads.some(item=>item.state!=='done')" class="kn-upload-queue" aria-live="polite"><div v-for="item in uploads.filter(item=>item.state!=='done')" :key="item.id"><strong>{{item.file.name}}</strong><span>{{item.state==='uploading'?'正在保存图片…':item.error}}</span><button v-if="item.state==='error'" @click="uploadImage(item)">重新上传</button><button v-if="item.state==='error'" @click="removeUpload(item)">移除失败项</button></div></div>
          <footer class="kn-writing-footer"><span>{{words.toLocaleString()}} 字 · {{assets}} 张图片</span><span>支持粘贴截图 / 拖入图片 · Ctrl+Z 撤销</span></footer>
        </div><aside class="kn-inspector"><div class="kn-inspector-title"><i class="fa-solid fa-feather-pointed" aria-hidden="true"></i><span>写作与发布<small>FROM EXPERIENCE TO KNOWLEDGE</small></span></div>
          <section class="kn-publication"><span class="kn-section-label">发布状态</span><strong :class="{'kn-failed':note?.index_state==='failed'}">{{indexLabel}}</strong><p v-if="note?.index_state==='failed'">{{note.index_message}}。点击“重试索引”可重试；已有可检索版本继续可用。</p><p v-else>编辑时自动保存草稿，点击发布后才更新检索。资料库与经验沉淀保持独立。</p><small>草稿 R{{note?.revision}}<template v-if="note?.indexed_revision"> · 可检索 R{{note.indexed_revision}}</template></small></section>
          <section><span class="kn-section-label">随笔记一起保存</span><p>标题、正文、表格、图片说明与校正后的识别文字会进入检索；图片本身作为附件保留。</p><p class="kn-privacy"><i class="fa-solid fa-shield-halved" aria-hidden="true"></i>继承所在项目的保密等级与访问权限。</p><small>创建人：{{note?.created_by}}<br>最近修改：{{note?.modified_by}}</small></section>
          <section><span class="kn-section-label">导出当前草稿</span><button class="kn-export" :disabled="blocked||exporting" @click="exportFile('docx')"><span>W</span><strong>Word 文档<small>可编辑 · 内嵌图片 · 下载水印</small></strong><b>↗</b></button><button class="kn-export" :disabled="blocked||exporting" @click="exportFile('markdown')"><span>M↓</span><strong>MD ＋ 图片<small>完整 ZIP 包 · 保留图片相对路径</small></strong><b>↗</b></button><p v-if="exporting" role="status">正在准备带水印的文件，请稍候…</p></section>
          <section class="kn-help"><button :aria-expanded="helpOpen" @click="helpOpen=!helpOpen">操作提示 <span>{{helpOpen?'−':'＋'}}</span></button><div v-if="helpOpen"><p>插图后光标会进入下方正文，可以直接打字。填写图片说明后，点击“在图片下继续写正文”返回正文；说明框只填写这张图的说明。</p><p>拖动图片右下角或选择百分比调整大小。点击“识别图片文字”，核对后保存；识别不出时可手动补充。</p><p>表格中按 Tab 移动单元格，选中单元格后可加行、加列和合并。</p><p>关闭时会先保存。保存失败会明确提示，请重试或下载本机恢复副本。</p><p>标题、正文和发布操作都会记录操作人、时间与前后内容。草稿仅项目创建者和管理员可编辑查看。</p></div></section>
          <section class="kn-help"><button :aria-expanded="historyOpen" @click="showHistory">修改记录 <span>{{historyOpen?'−':'＋'}}</span></button><div v-if="historyOpen" class="kn-history"><p v-if="historyError">{{historyError}}</p><p v-if="!events.length&&!historyError">暂无记录。</p><details v-for="event in events" :key="event.id"><summary>{{historyLabel(event.action)}} · {{event.actor}}<small>{{new Date(event.created_at).toLocaleString('zh-CN')}}</small></summary><pre>{{historyContent(event.changes)}}</pre></details><small>显示最近 100 条操作。</small></div></section>
        </aside></div>
      </div>
    </el-dialog>`,
  };
})();
