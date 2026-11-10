# Knowledge workspace design

This pass applies UI UX Pro Max's verified `minimalism-and-swiss-style` match
and Anthropic frontend-design's content-first, restrained design process.
Sources installed from `nextlevelbuilder/ui-ux-pro-max-skill` and
`anthropics/skills` on 2026-11-10. The initial design-system search suggested a
marketing landing page; that layout was rejected for this existing workspace.

## Direction

A research archive for consultants: names, locations, processing states and
evidence lead the interface. The distinctive element is the file list itself,
with legible names, quiet file-type icons and predictable aligned columns.
Keep the established project / directory / file structure and both collections.

- Canvas `#F7F9FC`; paper `#FFFFFF`; strong text `#243247`.
- Secondary text `#526175`; divider `#DCE3EC`; blue action `#315E91`.
- Reuse the existing semantic variables, light/dark modes and Chinese system
  font stack. No remote font or additional runtime dependency.
- Type: 24px page title, 16px section title, 14px controls/file names,
  12–13px metadata, 15px reading text. Use 4/8/12/16/24px spacing.
- Left align names, paths and labels; keep metadata columns stable. Give
  headings their own line before the search/action toolbar at constrained widths.
- Primary action: open/read. Keep favorite available; group move, file settings
  and delete in an accessible menu. Failure recovery stays visible.
- Reading: file identity and location, then actions and mode/search controls,
  then a wide document and compact evidence/question sidebar.

```text
knowledge views                         theme / requests
-------------------------------------------------------
categories | location / page title       file count
           | search                     upload / create
           | filters or current scope       sort / ask
           | file/folder name | state | date | read more
```

## Review and verification

The design intentionally keeps the existing blue accent and familiar labels.
It does not adopt the search engine's gold palette, marketing hero, external
Inter font, decorative statistics or animations. Existing CSS is refined in
knowledge-workspace.css; do not add another theme stylesheet.

Verify menu keyboard access, permission-dependent actions, unchanged selection
and document navigation, original/excerpt switching, failure messages, light
and dark modes, 375/768/1024/1440px layouts, and 200% browser zoom. Use only the
disposable local audit application for interaction checks.
