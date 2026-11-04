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
          *{box-sizing:border-box}html,body{margin:0;background:#e5eaf0;color:#1c2939;font-family:Arial,'Microsoft YaHei',sans-serif}#pages{padding:24px;min-height:100vh}.docx-wrapper{background:transparent!important;padding:0!important}.docx-wrapper>section.docx{position:relative;background:white;margin:0 auto 22px!important;box-shadow:0 3px 16px #26384b20!important;overflow:hidden}.docx-wrapper>section.docx article{position:relative;z-index:1}.viewer-watermark{position:absolute;inset:0;z-index:10;pointer-events:none;display:grid;grid-template-columns:1fr 1fr;grid-template-rows:repeat(4,1fr);overflow:hidden}.viewer-watermark span{display:flex;align-items:center;justify-content:center;transform:rotate(-24deg);color:#355b83;opacity:.13;font:13px/1.8 Arial,sans-serif;white-space:pre-line;text-align:center}a{color:inherit;text-decoration:none}img{max-width:100%}
          </style></head><body><div id="pages"></div><script src="${engine}"><\/script><script nonce="${nonce}">
          const channel=${channel};let factor=1;let active=false;
          const send=(type,extra={})=>parent.postMessage({channel,type,...extra},'*');
          function fit(){const pages=document.querySelectorAll('section.docx');const width=pages[0]?.offsetWidth||794;document.getElementById('pages').style.zoom=Math.min(1,(innerWidth-12)/(width+48))*factor;}
          addEventListener('resize',fit);
          addEventListener('message',async event=>{if(event.source!==parent||event.data?.channel!==channel)return;const data=event.data;
            if(data.type==='zoom'){factor=data.value/100;fit();return;}
            if(data.type!=='render'||active)return;active=true;
            try{
              await docx.renderAsync(data.buffer,document.getElementById('pages'),null,{inWrapper:true,breakPages:true,ignoreLastRenderedPageBreak:false,renderHeaders:true,renderFooters:true,renderFootnotes:true,renderEndnotes:true,renderAltChunks:false,useBase64URL:true});
              document.querySelectorAll('a').forEach(a=>a.replaceWith(...a.childNodes));
              const pages=document.querySelectorAll('section.docx');if(!pages.length)throw Error('No pages');
              pages.forEach(page=>{const mark=document.createElement('div');mark.className='viewer-watermark';for(let n=0;n<8;n++){const line=document.createElement('span');line.textContent=data.identity+'\\n'+data.trace;mark.append(line);}page.append(mark);});
              fit();send('rendered',{pages:pages.length});
            }catch(_){send('error');}
          });send('ready');
          <\/script></body></html>`;
      },
      fail() { if (this.disposed) return; clearTimeout(this.deadline); this.loading = false; this.error = '这份文件的在线排版未能完成，请下载带水印的原格式文件查看。'; },
      changeZoom(delta) { this.zoom = Math.min(160, Math.max(60, this.zoom + delta)); this.$refs.frame?.contentWindow.postMessage({ channel: this.channel, type: 'zoom', value: this.zoom }, '*'); },
    },
    template: `<div class="ckb-native-document"><div class="ckb-document-controls"><span><i class="fa-regular fa-file-lines" aria-hidden="true"></i>{{ format === 'DOCX' ? '文档版式' : '完整正文' }}<small v-if="pages">{{ pages }} 页</small></span><div v-if="format === 'DOCX'"><button :disabled="loading || zoom <= 60" aria-label="缩小文档" @click="changeZoom(-10)">−</button><span>{{ zoom }}%</span><button :disabled="loading || zoom >= 160" aria-label="放大文档" @click="changeZoom(10)">+</button></div></div><p v-if="loading" class="ckb-document-loading" role="status"><i class="fa-solid fa-circle-notch fa-spin" aria-hidden="true"></i>正在铺开完整文档…</p><p v-if="error" class="ckb-document-failure" role="alert">{{ error }}</p><iframe v-if="format === 'DOCX' && !error" ref="frame" :srcdoc="source" sandbox="allow-scripts" referrerpolicy="no-referrer" title="完整 Word 文档预览" class="ckb-document-frame"></iframe><div v-else-if="!error && !loading" class="ckb-fulltext-document"><div class="ckb-text-watermark" aria-hidden="true">{{ identity }} · {{ trace }}</div><pre>{{ text }}</pre></div><small class="ckb-document-footnote">{{ format === 'DOCX' ? '在线排版可能与 Word 略有差异，可下载原格式水印副本核对。' : '展示完整文件正文，检索片段仅作为问答依据。' }}</small></div>`,
  };
})();
