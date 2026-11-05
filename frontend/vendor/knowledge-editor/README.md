# Knowledge note editor runtime

Pinned MIT-licensed Tiptap 3.32.2 / ProseMirror packages. The generated IIFE is
served from this application's origin; there are no CDN requests, document
conversion services, paid extensions, collaboration servers or editor API keys.

Build with Node 20+:

```sh
npm ci --ignore-scripts --no-audit --no-fund
npm run build
```

`engine.json` records the bundle digest. If the digest changes, update the engine
filename in `frontend/knowledge-note-editor.js`, then run
`python scripts/build-knowledge-assets.py` to update entry point hashes.
The lockfile includes transitive versions and registry integrity hashes.
`THIRD_PARTY_NOTICES.md` and `licenses/` retain the runtime package licenses.

Design references: [Tiptap](https://github.com/ueberdosis/tiptap) for editor
behavior, [Outline](https://github.com/outline/outline) for a quiet writing canvas
and document organization. Outline source code and assets are not incorporated.
