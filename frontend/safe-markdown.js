/* Only sanitized Markdown output may enter the assistant's v-html sink. */
(function (root) {
  'use strict';
  const escapeText = value => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[char]).replace(/\r\n?|\n/g, '<br>');

  root.SafeMarkdown = Object.freeze({
    render(value) {
      const text = String(value ?? '');
      if (!root.marked || typeof root.marked.parse !== 'function' ||
          !root.DOMPurify || root.DOMPurify.isSupported !== true) return escapeText(text);
      try {
        const html = root.marked.parse(text);
        if (typeof html !== 'string') return escapeText(text);
        return root.DOMPurify.sanitize(html, {
          ALLOWED_TAGS: ['p', 'br', 'hr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
            'ul', 'ol', 'li', 'strong', 'em', 'del', 's', 'blockquote', 'pre', 'code',
            'a', 'img', 'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td'],
          ALLOWED_ATTR: ['href', 'title', 'src', 'alt', 'width', 'height', 'start',
            'colspan', 'rowspan', 'align'],
          ALLOW_DATA_ATTR: false,
          ALLOW_ARIA_ATTR: false,
          ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto):|[^:]*$)/i,
        });
      } catch (_) {
        // If the parser or sanitizer cannot run, display escaped source text.
        return escapeText(text);
      }
    }
  });
})(window);
