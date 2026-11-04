/* Original rounded-lens displacement, inspired by the optical layering in
   https://github.com/shuding/liquid-glass and https://github.com/dpawlikowski/liquid-glass.
   The filter samples only the backdrop; form text never enters the SVG pipeline. */
(() => {
  let sequence = 0;
  const maps = new Map();
  function lensMap(width, height, radius) {
    const key = [width, height, radius].join(':');
    if (maps.has(key)) return maps.get(key);
    const ratio = Math.min(.7, 640 / Math.max(width, height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.ceil(width * ratio));
    canvas.height = Math.max(1, Math.ceil(height * ratio));
    const context = canvas.getContext('2d');
    const image = context.createImageData(canvas.width, canvas.height);
    for (let row = 0; row < canvas.height; row++) {
      for (let column = 0; column < canvas.width; column++) {
        const x = (column + .5) / canvas.width * width - width / 2;
        const y = (row + .5) / canvas.height * height - height / 2;
        const qx = Math.abs(x) - (width / 2 - radius);
        const qy = Math.abs(y) - (height / 2 - radius);
        const ox = Math.max(qx, 0), oy = Math.max(qy, 0);
        const corner = Math.hypot(ox, oy);
        const depth = radius - corner - Math.min(Math.max(qx, qy), 0);
        let nx = 0, ny = 0;
        if (corner > 0) { nx = Math.sign(x) * ox / corner; ny = Math.sign(y) * oy / corner; }
        else if (qx > qy) nx = Math.sign(x);
        else ny = Math.sign(y);
        const t = Math.max(0, Math.min(1, depth / 32));
        const bend = depth >= 0 && depth < 32 ? (Math.sin(t * Math.PI) * .72 + (1 - t) * .28) : 0;
        const offset = (row * canvas.width + column) * 4;
        image.data[offset] = Math.round(128 + nx * bend * 120);
        image.data[offset + 1] = Math.round(128 + ny * bend * 120);
        image.data[offset + 2] = 128;
        image.data[offset + 3] = 255;
      }
    }
    context.putImageData(image, 0, 0);
    const url = canvas.toDataURL('image/png');
    if (maps.size >= 4) maps.delete(maps.keys().next().value);
    maps.set(key, url);
    return url;
  }
  window.KnowledgeGlassSurface = {
    data() { return { host: null, target: null, left: 0, top: 0, filterId: 'ckb-lens-' + (++sequence), map: '', width: 1, height: 1, enhanced: false }; },
    mounted() {
      this.host = this.$el.closest('.ckb-dialog');
      if (!this.host) return;
      this.target = this.host.parentElement;
      this.glassDisposed = false;
      this.glassMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
      this.glassContrast = window.matchMedia('(prefers-reduced-transparency: reduce), (prefers-contrast: more)');
      this.glassMeasure = () => {
        if (this.glassDisposed) return;
        cancelAnimationFrame(this.glassResizeFrame);
        this.glassResizeFrame = requestAnimationFrame(() => {
          if (this.glassDisposed) return;
          const width = this.host.offsetWidth, height = this.host.offsetHeight;
          this.left = this.host.offsetLeft; this.top = this.host.offsetTop;
          if (!width || !height) return;
          // Chromium supports backdrop SVG displacement. Other browsers retain the frosted fallback.
          this.enhanced = !this.glassContrast.matches && /Chrome|Chromium|Edg\//.test(navigator.userAgent)
            && CSS.supports('backdrop-filter', 'url("#' + this.filterId + '")');
          if (!this.enhanced) { this.map = ''; return; }
          const radius = parseFloat(getComputedStyle(this.host).borderTopLeftRadius) || 30;
          if (width === this.width && height === this.height && this.map) return;
          this.width = width; this.height = height;
          try { this.map = lensMap(width, height, radius); }
          catch (_) { this.map = ''; this.enhanced = false; }
        });
      };
      this.glassPointer = event => {
        if (this.glassMotion.matches || this.glassContrast.matches || document.querySelector('.ckb-motion-paused')) return;
        const box = this.host.getBoundingClientRect();
        this.glassPosition = [Math.max(0, Math.min(100, (event.clientX - box.left) / box.width * 100)), Math.max(0, Math.min(100, (event.clientY - box.top) / box.height * 100))];
        if (this.glassPointerFrame) return;
        this.glassPointerFrame = requestAnimationFrame(() => {
          this.glassPointerFrame = 0;
          if (this.glassDisposed) return;
          this.$refs.surface?.style.setProperty('--kg-pointer-x', this.glassPosition[0] + '%');
          this.$refs.surface?.style.setProperty('--kg-pointer-y', this.glassPosition[1] + '%');
        });
      };
      this.glassLeave = () => {
        cancelAnimationFrame(this.glassPointerFrame); this.glassPointerFrame = 0;
        this.$refs.surface?.style.removeProperty('--kg-pointer-x'); this.$refs.surface?.style.removeProperty('--kg-pointer-y');
      };
      this.host.addEventListener('pointermove', this.glassPointer, { passive: true });
      this.host.addEventListener('pointerleave', this.glassLeave);
      this.glassContrast.addEventListener('change', this.glassMeasure);
      this.glassMotion.addEventListener('change', this.glassLeave);
      if (typeof ResizeObserver !== 'undefined') {
        this.glassObserver = new ResizeObserver(this.glassMeasure); this.glassObserver.observe(this.host);
      }
      window.addEventListener('resize', this.glassMeasure);
      this.$nextTick(this.glassMeasure);
    },
    beforeUnmount() {
      this.glassDisposed = true;
      cancelAnimationFrame(this.glassResizeFrame); cancelAnimationFrame(this.glassPointerFrame);
      this.glassObserver?.disconnect();
      if (this.glassMeasure) window.removeEventListener('resize', this.glassMeasure);
      if (this.host && this.glassPointer) {
        this.host.removeEventListener('pointermove', this.glassPointer); this.host.removeEventListener('pointerleave', this.glassLeave);
        this.glassContrast.removeEventListener('change', this.glassMeasure); this.glassMotion.removeEventListener('change', this.glassLeave);
        this.glassLeave();
      }
    },
    template: `<span class="ckb-glass-anchor" aria-hidden="true"><teleport v-if="target" :to="target"><div ref="surface" class="ckb-glass-surface" :class="{ 'has-refraction': enhanced && map }" :style="{ '--kg-optics-filter': 'url(#' + filterId + ')', width: width + 'px', height: height + 'px', left: left + 'px', top: top + 'px' }" aria-hidden="true"><svg class="ckb-optics-definitions" width="0" height="0" focusable="false"><defs><filter :id="filterId" x="0" y="0" :width="width" :height="height" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB"><feImage :href="map || undefined" :width="width" :height="height" preserveAspectRatio="none" result="lens"/><feDisplacementMap in="SourceGraphic" in2="lens" scale="44" xChannelSelector="R" yChannelSelector="G"/></filter></defs></svg><span class="ckb-glass-refraction"></span><span class="ckb-glass-material"></span><span class="ckb-glass-caustic"></span><span class="ckb-glass-rim"></span></div></teleport></span>`,
  };
})();
