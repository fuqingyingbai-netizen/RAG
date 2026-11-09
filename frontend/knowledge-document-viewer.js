/* Local DOCX rendering. The document runs in an opaque sandbox, without credentials
   or network access. No document bytes are sent to an external Office viewer. */
(() => {
  const engine = new URL('vendor/knowledge-reader/knowledge-document-engine.f9248bf019bf.js', document.baseURI).href;
  window.KnowledgeDocumentViewer = {
    props: { blob: Blob, format: String, identity: String, trace: String, findText: String },
    data() { return { source: '', text: '', error: '', loading: true, pages: 0, zoom: 100, outline: [] }; },
    watch: { findText() { this.findSource(); } },
    mounted() { this.start(); },
    beforeUnmount() { this.disposed = true; clearTimeout(this.deadline); window.removeEventListener('message', this.receive); },
    methods: {
      async start() {
        this.channel = crypto.randomUUID();
        if (['TXT', 'MD', 'CSV'].includes(this.format)) {
          try {
            const buffer = await this.blob.arrayBuffer();
            if (this.disposed) return;
            const bytes=new Uint8Array(buffer),charset=(this.blob.type?.match(/charset=([^;]+)/i)||[])[1];
            const encoding=bytes[0]===255&&bytes[1]===254?'utf-16le':bytes[0]===254&&bytes[1]===255?'utf-16be':charset?.replace(/utf-8-sig/i,'utf-8').replace(/utf-16-le/i,'utf-16le').replace(/utf-16-be/i,'utf-16be')||'utf-8';
            this.text = new TextDecoder(encoding).decode(buffer);
            if (this.text.includes('\uFFFD')) this.text = new TextDecoder('gb18030').decode(buffer);
            this.loading = false; this.$nextTick(() => this.findSource());
          } catch (_) { this.fail(); }
          return;
        }
        const nonce = crypto.randomUUID().replaceAll('-', '');
        const channel = JSON.stringify(this.channel);
        const origin = new URL(engine).origin;
        this.receive = async event => {
          if (event.source !== this.$refs.frame?.contentWindow || event.data?.channel !== this.channel || this.disposed) return;
          if (event.data.type === 'ready') {
            try {
              const buffer = await this.blob.arrayBuffer();
              if (!this.disposed) this.$refs.frame.contentWindow.postMessage({ channel: this.channel, type: 'render', buffer, identity: this.identity, trace: this.trace }, '*', [buffer]);
            } catch (_) { this.fail(); }
          } else if (event.data.type === 'rendered') {
            clearTimeout(this.deadline); this.loading = false; this.pages = event.data.pages; this.outline=event.data.outline || []; this.findSource();
          } else if (event.data.type === 'located') { this.$emit('located', event.data.result);
          } else if (event.data.type === 'error') this.fail();
        };
        window.addEventListener('message', this.receive);
        this.deadline = setTimeout(() => this.fail(), 45000);
        this.source = `<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="referrer" content="no-referrer"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src ${origin} 'nonce-${nonce}'; style-src 'unsafe-inline'; img-src data: blob:; font-src data: blob:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"><style>
          *{box-sizing:border-box}html,body{margin:0;background:#e5eaf0;color:#1c2939;font-family:Arial,'Microsoft YaHei',sans-serif}#pages{position:absolute;left:0;top:0;padding:24px;transform-origin:0 0}.docx-wrapper{background:transparent!important;padding:0!important}.docx-wrapper>section.docx{position:relative;background:white;margin:0 auto 22px!important;box-shadow:0 3px 16px #26384b20!important;overflow:hidden}.docx-wrapper>section.docx article{position:relative;z-index:1}.viewer-watermark{position:absolute;inset:0;z-index:10;pointer-events:none;background-repeat:repeat;background-size:440px 300px;overflow:hidden;font-size:0;color:transparent}::highlight(source){background:#ffe08a;color:#18263a}.source-match{outline:2px solid #e8ae34;background:#fff0b8}a{color:inherit;text-decoration:none}img{max-width:100%}
          </style></head><body><div id="pages"></div><script src="${engine}"><\/script><script nonce="${nonce}">
          const channel=${channel};let factor=1;let active=false;let sourceOutline=[];
          const send=(type,extra={})=>parent.postMessage({channel,type,...extra},'*');
          function findSource(query,heading=false){
            document.querySelectorAll('.source-match').forEach(e=>e.classList.remove('source-match'));if(CSS.highlights)CSS.highlights.delete('source');
            const compact=value=>String(value||'').replace(/\\s/g,'').toLocaleLowerCase();
            // Word's printed table of contents repeats chapter names. Prefer the
            // actual heading paragraph, rather than a substring in the TOC.
            const target=heading?[...document.querySelectorAll('article p')].find(p=>compact(p.textContent)===compact(query)):null;
            const nodes=[],offsets=[];let full='';const walker=document.createTreeWalker(target||document.getElementById('pages'),NodeFilter.SHOW_TEXT,{acceptNode:n=>n.parentElement.closest('.viewer-watermark,style,script')?NodeFilter.FILTER_REJECT:NodeFilter.FILTER_ACCEPT});
            while(walker.nextNode()){const node=walker.currentNode;nodes.push(node);for(let i=0;i<node.textContent.length;i++){if(!/\\s/.test(node.textContent[i])){full+=node.textContent[i].toLocaleLowerCase();offsets.push([nodes.length-1,i]);}}}
            const terms=String(query||'').split('\\n').map(t=>t.replace(/^[#*\\s]+/,'').trim()).filter(t=>t.length>=(heading?1:4)).slice(0,8);let found=false;
            for(const term of terms){const needle=term.replace(/\\s/g,'').toLocaleLowerCase().slice(0,120),index=full.indexOf(needle);if(index<0||!needle)continue;const start=offsets[index],end=offsets[index+needle.length-1];if(!start||!end)continue;const range=document.createRange();range.setStart(nodes[start[0]],start[1]);range.setEnd(nodes[end[0]],end[1]+1);if(CSS.highlights&&typeof Highlight!=='undefined')CSS.highlights.set('source',new Highlight(range));else nodes[start[0]].parentElement.classList.add('source-match');const rect=range.getBoundingClientRect();scrollTo({top:Math.max(0,scrollY+rect.top-innerHeight*.22),left:0,behavior:'instant'});found=true;break;}
            send('located',{result:{matched:found,message:found?'已高亮原文':'原文未找到精确匹配，请对照引用片段核对。'}});
          }
          function fit(){
            const pages=document.querySelectorAll('section.docx'),width=pages[0]?.offsetWidth||794;
            // Keep Word's layout in its original units. CSS zoom on the iframe's
            // document can leave a stale paint surface inside a frosted dialog.
            const scale=Math.max(.1,Math.min(1,(innerWidth-12)/(width+48))*factor),container=document.getElementById('pages');
            container.style.width=Math.max(width+48,innerWidth/scale)+'px';
            container.style.transform='scale('+scale+')';
            document.body.style.height=Math.ceil(container.offsetHeight*scale)+'px';
            document.body.style.width=Math.ceil(Math.max(innerWidth,(width+48)*scale))+'px';
          }
          function firstBody(){
            const page=[...document.querySelectorAll('section.docx')].find(p=>(p.querySelector('article')?.textContent||'').replace(/\\s/g,'').length>160)||document.querySelector('section.docx');
            if(page)scrollTo({top:Math.max(0,scrollY+page.getBoundingClientRect().top-8),left:0,behavior:'instant'});
          }
          async function displayPackage(buffer){
            // Browsers lay Word's floating watermark out as a 6-inch header.
            // Replace only our tagged header drawings with the page overlays below.
            // This in-memory display package is never used by the download action.
            const zip=await JSZip.loadAsync(buffer);let changed=false;
            const main=zip.file('word/document.xml');if(main){const xml=new DOMParser().parseFromString(await main.async('string'),'application/xml'),ns='http://schemas.openxmlformats.org/wordprocessingml/2006/main';sourceOutline=[...xml.getElementsByTagNameNS(ns,'p')].filter(p=>{const style=p.getElementsByTagNameNS(ns,'pStyle')[0],outline=p.getElementsByTagNameNS(ns,'outlineLvl')[0];return /heading|标题/i.test(style?.getAttributeNS(ns,'val')||'')||(outline&&Number(outline.getAttributeNS(ns,'val'))<9);}).map(p=>[...p.getElementsByTagNameNS(ns,'t')].map(t=>t.textContent).join('').slice(0,160)).filter(Boolean).slice(0,150);}

            for(const file of Object.values(zip.files)){
              if(file.dir||!/^word\\/header[^/]*\\.xml$/.test(file.name))continue;
              const xml=new DOMParser().parseFromString(await file.async('string'),'application/xml');let dirty=false;
              for(const drawing of [...xml.getElementsByTagNameNS('http://schemas.openxmlformats.org/wordprocessingml/2006/main','drawing')]){
                const tag=drawing.getElementsByTagNameNS('http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing','docPr')[0];
                if(tag?.getAttribute('name')?.startsWith('CKB watermark ')){drawing.remove();dirty=true;}
              }
              if(dirty){zip.file(file.name,new XMLSerializer().serializeToString(xml));changed=true;}
            }
            return changed?zip.generateAsync({type:'arraybuffer',compression:'STORE'}):buffer;
          }
          addEventListener('resize',fit);
          addEventListener('message',async event=>{if(event.source!==parent||event.data?.channel!==channel)return;const data=event.data;
            if(data.type==='find'||data.type==='heading'){findSource(data.text,data.type==='heading');return;}
            if(data.type==='body'){firstBody();return;}
            if(data.type==='reflow'){fit();requestAnimationFrame(()=>{scrollBy(0,1);requestAnimationFrame(()=>scrollBy(0,-1));});return;}
            if(data.type==='zoom'){factor=data.value/100;fit();return;}
            if(data.type!=='render'||active)return;active=true;
            try{
              await docx.renderAsync(await displayPackage(data.buffer),document.getElementById('pages'),null,{inWrapper:true,breakPages:true,ignoreLastRenderedPageBreak:false,renderHeaders:true,renderFooters:true,renderFootnotes:true,renderEndnotes:true,renderAltChunks:false,useBase64URL:true});
              document.querySelectorAll('a').forEach(a=>a.replaceWith(...a.childNodes));
              const pages=document.querySelectorAll('section.docx');if(!pages.length)throw Error('No pages');
              const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('width','440');svg.setAttribute('height','300');
              const lines=[data.identity,data.trace].flatMap(line=>Array.from(String(line).matchAll(/.{1,44}/gu),m=>m[0]));
              lines.forEach((line,n)=>{const t=document.createElementNS(svg.namespaceURI,'text');t.setAttribute('x','220');t.setAttribute('y',String(145+n*18));t.setAttribute('text-anchor','middle');t.setAttribute('transform','rotate(-24 220 150)');t.setAttribute('font-family','Arial,sans-serif');t.setAttribute('font-size','12');t.setAttribute('fill','#355b83');t.setAttribute('fill-opacity','.13');t.textContent=line;svg.append(t);});
              const tile='url("data:image/svg+xml,'+encodeURIComponent(new XMLSerializer().serializeToString(svg))+'")';
              pages.forEach(page=>{const mark=document.createElement('div');mark.className='viewer-watermark';mark.setAttribute('aria-hidden','true');mark.textContent=data.identity+' '+data.trace;mark.style.backgroundImage=tile;page.append(mark);});
              // The sandbox can finish its DOM while the dialog is still laying
              // out. Wait for layout, then establish the first page's viewport
              // before announcing that the original is ready to read.
              await new Promise(requestAnimationFrame);fit();
              await new Promise(requestAnimationFrame);
              scrollTo({top:Math.max(0,scrollY+pages[0].getBoundingClientRect().top-8),left:0,behavior:'instant'});
              await new Promise(requestAnimationFrame);
              send('rendered',{pages:pages.length,outline:sourceOutline});
            }catch(_){send('error');}
          });send('ready');
          <\/script></body></html>`;
      },
      reflow() { this.$refs.frame?.contentWindow.postMessage({channel:this.channel,type:'reflow'},'*'); },
      firstBody() { this.$refs.frame?.contentWindow.postMessage({channel:this.channel,type:'body'},'*'); },
      jumpHeading(text) { if(text)this.$refs.frame?.contentWindow.postMessage({channel:this.channel,type:'heading',text},'*'); },
      findSource() {
        if(this.loading || !this.findText?.trim())return;
        if(this.format==='DOCX')this.$refs.frame?.contentWindow.postMessage({channel:this.channel,type:'find',text:this.findText},'*');
        else { const index=this.text.toLocaleLowerCase().indexOf(this.findText.trim().toLocaleLowerCase());this.$emit('located',{matched:index>=0,message:index>=0?'已匹配原文':'原文未找到精确匹配，请对照引用片段核对。'});this.$nextTick(()=>this.$el.querySelector('mark')?.scrollIntoView({block:'center'})); }
      },
      textParts() { const query=this.findText?.trim(); const index=query?this.text.toLocaleLowerCase().indexOf(query.toLocaleLowerCase()):-1;return index<0?{before:this.text,hit:'',after:''}:{before:this.text.slice(0,index),hit:this.text.slice(index,index+query.length),after:this.text.slice(index+query.length)}; },
      fail() { if (this.disposed) return; clearTimeout(this.deadline); this.loading = false; this.error = '这份文件的在线排版未能完成，请下载带水印的原格式文件查看。'; },
      changeZoom(delta) { this.zoom = Math.min(160, Math.max(60, this.zoom + delta)); this.$refs.frame?.contentWindow.postMessage({ channel: this.channel, type: 'zoom', value: this.zoom }, '*'); },
    },
    template: `<div class="ckb-native-document"><div class="ckb-document-controls"><span><i class="fa-regular fa-file-lines" aria-hidden="true"></i>{{ format === 'DOCX' ? '文档版式' : '完整正文' }}<small v-if="pages">连续阅读</small></span><div v-if="format === 'DOCX'"><button :disabled="loading" style="width:auto;min-width:64px;white-space:nowrap;flex-shrink:0" @click="reflow" aria-label="重排预览">重排预览</button><button :disabled="loading" style="width:auto;min-width:64px;white-space:nowrap;flex-shrink:0" @click="firstBody" aria-label="跳到正文">跳到正文</button><select v-if="outline.length" aria-label="Word 章节目录" @change="jumpHeading($event.target.value)"><option value="">章节目录</option><option v-for="(heading,index) in outline" :key="index" :value="heading">{{ heading }}</option></select><button :disabled="loading || zoom <= 60" aria-label="缩小文档" @click="changeZoom(-10)">−</button><span>{{ zoom }}%</span><button :disabled="loading || zoom >= 160" aria-label="放大文档" @click="changeZoom(10)">+</button></div></div><p v-if="loading" class="ckb-document-loading" role="status"><i class="fa-solid fa-circle-notch fa-spin" aria-hidden="true"></i>正在铺开完整文档…</p><p v-if="error" class="ckb-document-failure" role="alert">{{ error }}</p><iframe v-if="format === 'DOCX' && !error" ref="frame" :srcdoc="source" sandbox="allow-scripts" referrerpolicy="no-referrer" title="完整 Word 文档预览" class="ckb-document-frame"></iframe><div v-else-if="!error && !loading" class="ckb-fulltext-document"><div class="ckb-text-watermark" aria-hidden="true">{{ identity }} · {{ trace }}</div><pre>{{ textParts().before }}<mark v-if="textParts().hit">{{ textParts().hit }}</mark>{{ textParts().after }}</pre></div><small class="ckb-document-footnote">{{ format === 'DOCX' ? '在线排版可能与 Word 略有差异，可下载原格式水印副本核对。' : '展示完整文件正文，检索片段仅作为问答依据。' }}</small></div>`,
  };
})();

/* Reuse the authenticated, watermarked page endpoint. Only nearby pages are read;
   scrolling never downloads the unmarked original or starts a new export job. */
window.KnowledgePdfViewer = {
  props: { format: String, documentId: String, firstPage: String, pages: Number, fetchPage: Function, location: Object },
  data() { return { sheets: [], visiblePage: 1, zoom: 100, pageInput: 1, outline: [] }; },
  watch: { location: {deep:true,handler(value) { if(value?.page)this.$nextTick(()=>this.jumpTo(value.page)); }} },
  mounted() {
    this.wanted = new Set(); this.queue = []; this.owned = new Set(); this.controllers = new Set();
    this.sheets = Array.from({ length: Math.max(1, this.pages || 1) }, (_, i) => ({ number: i + 1, url: i ? '' : this.firstPage, ratio: 1 / Math.SQRT2, state: i ? 'idle' : 'ready', error: '' }));
    this.$nextTick(() => {
      if (this.disposed) return;
      if (typeof IntersectionObserver !== 'undefined') {
        this.observer = new IntersectionObserver(entries => {
          for (const entry of entries) {
            const number = Number(entry.target.dataset.page);
            if (entry.isIntersecting) { this.wanted.add(number); this.enqueue(number); }
            else this.wanted.delete(number);
          }
          this.prune();
        }, { root: this.$refs.scroll, rootMargin: '600px 0px' });
        this.$refs.scroll.querySelectorAll('[data-page]').forEach(page => this.observer.observe(page));
      }
      this.loadOutline(); this.trackPage(); if(this.location?.page)this.jumpTo(this.location.page);
    });
  },
  beforeUnmount() {
    this.disposed = true; this.observer?.disconnect(); cancelAnimationFrame(this.scrollFrame);
    for (const controller of this.controllers || []) controller.abort();
    for (const url of this.owned || []) URL.revokeObjectURL(url);
  },
  methods: {
    async loadOutline() { const controller=new AbortController();this.controllers.add(controller);try{const response=await this.fetchPage('/company-knowledge/documents/'+encodeURIComponent(this.documentId)+'/outline',{signal:controller.signal});if(response.ok){const data=await response.json();if(!this.disposed)this.outline=data.entries||[];}}catch{}finally{this.controllers.delete(controller);} },
    jumpTo(number) { const page=Math.min(this.sheets.length,Math.max(1,Number(number)||1));this.visiblePage=page;this.pageInput=page;this.wanted.add(page);this.enqueue(page);this.$refs.scroll?.querySelector('[data-page="'+page+'"]')?.scrollIntoView({block:'start'}); },
    changeZoom(delta) { this.zoom=Math.min(200,Math.max(70,this.zoom+delta));this.$nextTick(()=>this.jumpTo(this.visiblePage)); },
    enqueue(number, retry = false) {
      const sheet = this.sheets[number - 1];
      if (!sheet || sheet.url || sheet.state === 'loading' || sheet.state === 'queued' || (sheet.state === 'error' && !retry)) return;
      sheet.state = 'queued'; sheet.error = ''; this.queue.push(number); this.drain();
    },
    async drain() {
      if (this.draining || this.disposed) return;
      this.draining = true;
      try {
        while (this.queue.length && !this.disposed) {
          const number = this.queue.shift(), sheet = this.sheets[number - 1];
          if (!this.wanted.has(number)) { sheet.state = 'idle'; continue; }
          const controller = new AbortController(); this.controllers.add(controller); sheet.state = 'loading';
          try {
            const response = await this.fetchPage('/company-knowledge/documents/' + encodeURIComponent(this.documentId) + '/page?page=' + number, { signal: controller.signal });
            if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.detail || '这一页暂未加载成功，请重试。'); }
            const blob = await response.blob();
            if (this.disposed) return;
            const url = URL.createObjectURL(blob); this.owned.add(url); sheet.url = url; sheet.state = 'ready'; this.prune();
          } catch (error) {
            if (!this.disposed) { sheet.state = 'error'; sheet.error = error.message || '页面加载失败，请重试。'; }
          } finally { this.controllers.delete(controller); }
        }
      } finally { this.draining = false; }
    },
    prune() {
      const loaded = this.sheets.filter(sheet => sheet.url);
      const distant = loaded.filter(sheet => sheet.number !== 1 && !this.wanted.has(sheet.number)).sort((a, b) => Math.abs(b.number - this.visiblePage) - Math.abs(a.number - this.visiblePage));
      while (loaded.length > 8 && distant.length) {
        const sheet = distant.shift(); URL.revokeObjectURL(sheet.url); this.owned.delete(sheet.url); sheet.url = ''; sheet.state = 'idle'; loaded.pop();
      }
    },
    measure(sheet, event) {
      const image = event.target;
      if (image.naturalWidth && image.naturalHeight) {
        sheet.ratio = image.naturalWidth / image.naturalHeight;
        if (sheet.number === 1) for (const other of this.sheets) if (other.state === 'idle') other.ratio = sheet.ratio;
      }
    },
    trackPage() {
      cancelAnimationFrame(this.scrollFrame);
      this.scrollFrame = requestAnimationFrame(() => {
        const scroll = this.$refs.scroll; if (!scroll || this.disposed) return;
        const top = scroll.getBoundingClientRect().top;
        for (const page of scroll.querySelectorAll('[data-page]')) {
          const bounds = page.getBoundingClientRect();
          if (bounds.bottom > top + 60) { this.visiblePage = Number(page.dataset.page); this.pageInput=this.visiblePage; break; }
        }
        if (!this.observer) for (const page of scroll.querySelectorAll('[data-page]')) {
          const number = Number(page.dataset.page), bounds = page.getBoundingClientRect();
          if (bounds.bottom > top - 600 && bounds.top < top + scroll.clientHeight + 600) { this.wanted.add(number); this.enqueue(number); }
          else this.wanted.delete(number);
        }
      });
    },
  },
  template: `<div class="ckb-continuous-pdf"><div class="ckb-document-controls"><span><i class="fa-regular fa-file-pdf" aria-hidden="true"></i>{{ !format || format === 'PDF' ? 'PDF 原件' : format + ' 排版预览' }}<small>{{ format &amp;&amp; format !== 'PDF' ? '下载保留原格式' : '连续阅读' }}</small></span><div class="ckb-pdf-controls"><select v-if="outline.length" aria-label="PDF 章节目录" @change="jumpTo($event.target.value)"><option value="">章节目录</option><option v-for="(entry,index) in outline" :key="index" :value="entry.page">{{ entry.title }}</option></select><button aria-label="缩小 PDF" :disabled="zoom<=70" @click="changeZoom(-10)">−</button><span>{{ zoom }}%</span><button aria-label="放大 PDF" :disabled="zoom>=200" @click="changeZoom(10)">+</button><label>第 <input v-model.number="pageInput" type="number" min="1" :max="sheets.length" aria-label="跳转到页码" @keydown.enter="jumpTo(pageInput)" @change="jumpTo(pageInput)"> / {{ sheets.length }} 页</label></div></div><div ref="scroll" class="ckb-pdf-scroll" tabindex="0" role="region" aria-label="PDF 连续阅读区域" @scroll.passive="trackPage"><figure v-for="sheet in sheets" :key="sheet.number" :data-page="sheet.number" class="ckb-pdf-sheet" :style="{ aspectRatio: sheet.ratio, width: zoom + '%', maxWidth: 'none' }"><img v-if="sheet.url" :src="sheet.url" :alt="'PDF 原件第 ' + sheet.number + ' 页'" @load="measure(sheet, $event)"><div v-else class="ckb-pdf-placeholder" :aria-busy="sheet.state === 'loading'"><template v-if="sheet.error"><p role="alert">{{ sheet.error }}</p><button @click="enqueue(sheet.number, true)">重新加载这一页</button></template><span v-else><i v-if="sheet.state === 'loading'" class="fa-solid fa-circle-notch fa-spin" aria-hidden="true"></i> 第 {{ sheet.number }} 页{{ sheet.state === 'loading' ? ' · 正在加载' : '' }}</span></div><span v-if="location?.matched &amp;&amp; location.page === sheet.number" class="ckb-page-highlights" aria-hidden="true"><mark v-for="(rect,index) in location.rectangles" :key="index" :style="{left:rect.left*100+'%',top:rect.top*100+'%',width:rect.width*100+'%',height:rect.height*100+'%'}"></mark></span><figcaption>{{ sheet.number }} / {{ sheets.length }}</figcaption></figure></div></div>`,
};
