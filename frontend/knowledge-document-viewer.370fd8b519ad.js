/* Local DOCX rendering. The document runs in an opaque sandbox, without credentials
   or network access. No document bytes are sent to an external Office viewer. */
(() => {
  const engine = new URL('vendor/knowledge-reader/knowledge-document-engine.f9248bf019bf.js', document.baseURI).href;
  window.KnowledgeDocumentViewer = {
    props: { blob: Blob, format: String, identity: String, trace: String },
    data() { return { source: '', text: '', error: '', loading: true, pages: 0, zoom: 100 }; },
    mounted() { this.start(); },
    beforeUnmount() { this.disposed = true; clearTimeout(this.deadline); window.removeEventListener('message', this.receive); },
    methods: {
      async start() {
        this.channel = crypto.randomUUID();
        if (['TXT', 'MD', 'CSV'].includes(this.format)) {
          try {
            const buffer = await this.blob.arrayBuffer();
            if (this.disposed) return;
            this.text = new TextDecoder('utf-8').decode(buffer);
            if (this.text.includes('\uFFFD')) this.text = new TextDecoder('gb18030').decode(buffer);
            this.loading = false;
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
            clearTimeout(this.deadline); this.loading = false; this.pages = event.data.pages;
          } else if (event.data.type === 'error') this.fail();
        };
        window.addEventListener('message', this.receive);
        this.deadline = setTimeout(() => this.fail(), 45000);
        this.source = `<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="referrer" content="no-referrer"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src ${origin} 'nonce-${nonce}'; style-src 'unsafe-inline'; img-src data: blob:; font-src data: blob:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"><style>
          *{box-sizing:border-box}html,body{margin:0;background:#e5eaf0;color:#1c2939;font-family:Arial,'Microsoft YaHei',sans-serif}#pages{padding:24px;min-height:100vh}.docx-wrapper{background:transparent!important;padding:0!important}.docx-wrapper>section.docx{position:relative;background:white;margin:0 auto 22px!important;box-shadow:0 3px 16px #26384b20!important;overflow:hidden}.docx-wrapper>section.docx article{position:relative;z-index:1}.viewer-watermark{position:absolute;inset:0;z-index:10;pointer-events:none;background-repeat:repeat;background-size:440px 300px;overflow:hidden;font-size:0;color:transparent}a{color:inherit;text-decoration:none}img{max-width:100%}
          </style></head><body><div id="pages"></div><script src="${engine}"><\/script><script nonce="${nonce}">
          const channel=${channel};let factor=1;let active=false;
          const send=(type,extra={})=>parent.postMessage({channel,type,...extra},'*');
          function fit(){const pages=document.querySelectorAll('section.docx');const width=pages[0]?.offsetWidth||794;document.getElementById('pages').style.zoom=Math.min(1,(innerWidth-12)/(width+48))*factor;}
          async function displayPackage(buffer){
            // Browsers lay Word's floating watermark out as a 6-inch header.
            // Replace only our tagged header drawings with the page overlays below.
            // This in-memory display package is never used by the download action.
            const zip=await JSZip.loadAsync(buffer);let changed=false;
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
              fit();send('rendered',{pages:pages.length});
            }catch(_){send('error');}
          });send('ready');
          <\/script></body></html>`;
      },
      fail() { if (this.disposed) return; clearTimeout(this.deadline); this.loading = false; this.error = '这份文件的在线排版未能完成，请下载带水印的原格式文件查看。'; },
      changeZoom(delta) { this.zoom = Math.min(160, Math.max(60, this.zoom + delta)); this.$refs.frame?.contentWindow.postMessage({ channel: this.channel, type: 'zoom', value: this.zoom }, '*'); },
    },
    template: `<div class="ckb-native-document"><div class="ckb-document-controls"><span><i class="fa-regular fa-file-lines" aria-hidden="true"></i>{{ format === 'DOCX' ? '文档版式' : '完整正文' }}<small v-if="pages">连续阅读</small></span><div v-if="format === 'DOCX'"><button :disabled="loading || zoom <= 60" aria-label="缩小文档" @click="changeZoom(-10)">−</button><span>{{ zoom }}%</span><button :disabled="loading || zoom >= 160" aria-label="放大文档" @click="changeZoom(10)">+</button></div></div><p v-if="loading" class="ckb-document-loading" role="status"><i class="fa-solid fa-circle-notch fa-spin" aria-hidden="true"></i>正在铺开完整文档…</p><p v-if="error" class="ckb-document-failure" role="alert">{{ error }}</p><iframe v-if="format === 'DOCX' && !error" ref="frame" :srcdoc="source" sandbox="allow-scripts" referrerpolicy="no-referrer" title="完整 Word 文档预览" class="ckb-document-frame"></iframe><div v-else-if="!error && !loading" class="ckb-fulltext-document"><div class="ckb-text-watermark" aria-hidden="true">{{ identity }} · {{ trace }}</div><pre>{{ text }}</pre></div><small class="ckb-document-footnote">{{ format === 'DOCX' ? '在线排版可能与 Word 略有差异，可下载原格式水印副本核对。' : '展示完整文件正文，检索片段仅作为问答依据。' }}</small></div>`,
  };
})();
