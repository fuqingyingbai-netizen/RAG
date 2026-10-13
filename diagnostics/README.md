# Research workflow diagnostics

This folder contains standalone diagnostics for the real research workflow.

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
