/* This guard does not depend on Vue or any other library. */

(() => {

  'use strict';

  const panel = document.getElementById('app-startup');

  const message = document.getElementById('app-startup-message');

  const retry = document.getElementById('app-startup-retry');

  const app = document.getElementById('app');

  if (!panel || !message || !retry || !app) return;

  let finished = false;

  const began = Date.now();

  function stop() {

    window.clearInterval(timer);

    window.removeEventListener('error', onError, true);

    window.removeEventListener('unhandledrejection', fail);

  }

  function fail() {

    if (finished) return;

    finished = true;

    stop();

    app.hidden = true;

    message.textContent = '页面未能加载完整。请检查网络连接后重新加载；如果仍然失败，请联系管理员。';

    retry.hidden = false;

  }

  function onError(event) {

    if (event.target?.tagName === 'SCRIPT' || event.target?.tagName === 'LINK' || event.target === window) fail();

  }

  function stylesLoaded() {

    try {

      return [...document.querySelectorAll('link[rel="stylesheet"]')].every(link => link.sheet && link.sheet.cssRules.length > 0);

    } catch (_) { return false; } // Failed requests can expose an unreadable CSSStyleSheet.

  }

  retry.addEventListener('click', () => window.location.reload());

  window.addEventListener('error', onError, true);

  window.addEventListener('unhandledrejection', fail);

  const timer = window.setInterval(() => {

    if (finished) return;

    if (!app.hasAttribute('v-cloak')) {

      if (!stylesLoaded()) { fail(); return; }

      finished = true;

      stop();

      panel.hidden = true;

    } else if (Date.now() - began >= 20000) fail();

    else if (Date.now() - began >= 8000) message.textContent = '加载时间比平时稍长，请稍候…';

  }, 100);

})();

