# Research workflow diagnostics

This folder contains standalone diagnostics for the real research workflow.

## Accept the complete company workflow against live providers

`accept_company_live.py` calls the normal `ResearchWorkflow.run_project` with
the configured search services, professional platforms, model factory, source
quality checks, cleaning, report repair, Word export and rendering. It neither
injects source fixtures nor substitutes an LLM client. The normal result counts,
search rounds, modules and delivery gates remain in force.

```powershell
.venv/Scripts/python.exe diagnostics/accept_company_live.py `
  --target "目标企业完整名称" --industry "所属行业" `
  --env-file path/to/credentials.env --as-of 2026-10-24 `
  --output path/to/fresh-run --soffice path/to/soffice.exe
```

The database, research object store, report knowledge outbox, BM25 state and
renderer working directory are isolated under the output directory. Legacy
vector indexing is disabled; no knowledge ingestion worker is started. These
write-isolation settings are recorded separately from the original research
and model settings. The credential file is read without modification.

The run retains events, model inputs and outputs, code hashes, intermediate
artifacts, exported documents and source snapshots before the normal transient
body retention policy runs. `acceptance.json` distinguishes workflow completion
from the actual final delivery contract. A non-deliverable report exits with
status 1. The automatic result does not substitute for inspecting every rendered
Word page; manual inspection remains explicitly pending in the result.

Use a new directory for a new attempt. `--resume` resumes an interrupted local
project using the application's own source/artifact reuse rules, preserving
model receipts and each run's input manifest. It does not restore source bodies
which the normal retention policy has already removed. Diagnostic files contain
research originals and model prompts; keep them in an appropriate local folder.
To stop at a safe application checkpoint, create `pause.requested` in the output
folder (or the path given by `--pause-file`). The normal cooperative pause saves
the project; remove that request file before resuming. A paused run is never a
delivery pass.

The production company workflow now journals the completed original-material,
information-routing and editorial phases to its own research object store. These
checkpoints are not reports or delivery passes. Resume requires the same project,
target, full original-source fingerprint, date and research scope; each component
then revalidates its own current proofs. A failed or incomplete component remains
failed. The journal publishes an immutable payload hash before its latest pointer;
a changed or corrupt checkpoint cannot authorize reuse. Direct writer replays do
not write these checkpoints unless a workflow explicitly supplies its store.
Each independently accepted editorial batch is also journaled immediately;
later unfinished batches cannot erase its actual source-bound audit. Resuming
loads these as candidates and reruns the writer's current proposal/audit checks.
Completion progress follows finished jobs, while final prose keeps its original
chapter/aspect/job order. Neither a journal entry nor its `accepted` flag grants
report delivery approval.

## Replay company delivery quality on retained originals

`replay_company_delivery.py` runs the production company writer, semantic
editor, independent review, automatic text repair and final content contract.
It does not collect new sources, touch the database, export Word or publish.
Use native snapshots containing `url`, `title`, `content` and `source_metadata`:

```powershell
.venv/Scripts/python.exe diagnostics/replay_company_delivery.py `
  --target "目标企业完整名称" --sources path/to/source-snapshots.json `
  --as-of 2026-10-23 --env-file path/to/credentials.env --output path/to/replay
```

The output retains exact model prompts/responses, original text, per-information
semantic spans, rewrite attempts, final report and a machine-readable verdict.
Credentials are never included. Repeating the command reuses exact prompt
receipts and still revalidates their proofs; it does not turn a previous failure
into a pass. `--usage`, `--report`, `--state` can replay the editorial stage on
an earlier complete information package without repeating collection.

Production reports also export Word, verify chapter/prose/citation retention,
render with LibreOffice and check the rendered PDF's text and geometry. A
missing renderer or failed check keeps `delivery_ready=false`. Configure
`LIBREOFFICE_SOFFICE_PATH` on a host without `soffice` on PATH. The company
branch never takes the old report-only shortcut.

Company editing uses streaming transport by default, while `invoke` still returns
the complete assembled response. A missing terminal `stop`, truncation, or broken
stream is a failed call and cannot become a successful semantic review. Set
`COMPANY_REPORT_EDITOR_STREAMING_ENABLED=false` only for a service without SSE
support; the same completion and content checks still apply.
The same setting applies to company report original-material extraction and
information routing, preserving their existing model, role, temperature and
retry settings. Other report types retain their own transport settings.

The contract requires target identity and actual-business evidence. Requests
can add `required_chapters` or `scoring_required`; explicit required scoring is
also recognized in `special_requirements`. Optional unavailable evidence is
reported with a concrete scope, question and verification action, while a
failed parser, unsupported assertion or calculation remains a blocking error.
Core missing evidence receives one targeted collection pass and regeneration.
The original-material reviewer receives the declared industry, focus questions
and requested scope without treating those declarations as verified facts.
Changing that scope invalidates its classification receipts and corpus cache.
This is an automated public-information report contract, not a claim to have
completed interviews, bank-statement verification or every possible source.

## Run the first-two-steps diagnostic

From the project root:

```powershell
RAG\.venv\Scripts\python.exe RAG\diagnostics\diagnose_research_first_steps.py --target "乐奇Rokid" --industry "AI智能眼镜" --max-results 5 --provider tavily --verbose
```

The script reuses production workflow methods:

- `collect_web_sources()`
- `evaluate_source_quality()`
- `clean_sources()`

It creates a temporary research project in the configured database, runs web collection,
quality evaluation, and cleaning, then writes a timestamped JSON and Markdown report to
`RAG/diagnostics/output/`.

Useful options:

```powershell
RAG\.venv\Scripts\python.exe RAG\diagnostics\diagnose_research_first_steps.py `
  --target "乐奇Rokid" `
  --industry "AI智能眼镜" `
  --modules "公司背景,融资情报,股东高管,诉讼/制裁,负面新闻,行业市场" `
  --max-results 5 `
  --provider tavily `
  --search-query "Rokid 融资" `
  --focus-question "Rokid 是否存在上市、融资、司法或监管风险信号？"
```

Set `--keep-project` if you want to preserve the temporary project and sources in the
database for manual inspection. Without it, the diagnostic project is deleted after the
report is written.

By default, the script disables LLM refinement inside `clean_sources()` so the diagnostic
finishes faster and isolates retrieval/fast-cleaning behavior. Add `--llm-cleaning` when
you want to test the full cleaning path.
