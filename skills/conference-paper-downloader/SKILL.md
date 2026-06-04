---
name: conference-paper-downloader
description: Standalone Codex skill for collecting conference or journal paper metadata, extracting screening criteria from a review PDF, selecting papers for a research direction, downloading PDFs, and optionally classifying downloaded papers. Use when the user wants papers from ICLR, ICML, NeurIPS, a newly added fetcher, or a custom JSON venue source.
---

# Conference Paper Downloader

Use this skill to collect, screen, download, and optionally classify research papers. The skill is self-contained: use the bundled Python project under `scripts/conference-paper-downloader`; do not require the user to clone the outer GitHub repository unless they explicitly want to modify the upstream project.

## Resolve Paths

- `SKILL_ROOT`: the directory containing this `SKILL.md`.
- `TOOL_ROOT`: `SKILL_ROOT/scripts/conference-paper-downloader`.
- Run commands from `TOOL_ROOT` unless the user points to a separate project checkout.
- Put review PDFs under `TOOL_ROOT/review_papers/`, or pass an absolute PDF path.
- Outputs are written under `TOOL_ROOT/downloads/` and `TOOL_ROOT/definitions/` by default.

Before first use, install bundled dependencies:

```powershell
python -m pip install -r "<TOOL_ROOT>\requirements.txt"
```

## Built-In CLI Workflow

Use this when the user has an OpenAI-compatible API key and wants the bundled code to handle definition extraction, LLM screening, and downloads.

Set API variables first:

```powershell
$env:OPENAI_API_KEY = "..."
$env:OPENAI_BASE_URL = "https://api.openai.com/v1"
$env:OPENAI_MODEL = "gpt-4o-mini"
```

Run a built-in source:

```powershell
python main.py --conference iclr --year 2025 --direction "<direction>" --review-paper "<review.pdf>"
```

Run metadata-only extraction:

```powershell
python main.py --conference iclr --year 2025 --direction "<direction>" --version v2
```

Run a custom JSON source:

```powershell
python main.py --input-json "<papers.json>" --venue "<venue>" --year <year> --direction "<direction>" --review-paper "<review.pdf>"
```

The custom JSON list uses:

```text
conference, year, title, abstract, keywords, download_url
```

`conference`, `year`, and `keywords` may be omitted.

## Agent Screening Workflow

Use this by default when the user wants Codex to judge papers itself, or when no API key is available.

1. Ask the user to provide one review PDF for the target direction and place it in `TOOL_ROOT/review_papers/` if needed.
2. Get paper metadata with `--version v2`, or reuse an existing `all_papers.json`.
3. Read the review PDF and extract a concise definition for the requested direction, including inclusion criteria, exclusion criteria, and borderline cases.
4. Save the definition under `TOOL_ROOT/definitions/{direction_slug}/{review_slug}-{timestamp}.json`.
5. Screen papers from `all_papers.json` using only the extracted definition, paper title, and abstract. Keep `keywords` as metadata, not deciding evidence.
6. Save these files in the run directory:

```text
selected_papers_agent.json
agent_selection_notes.json
```

7. Download selected PDFs with the bundled downloader:

```powershell
python download_from_json.py --selected-json "<run_dir>\selected_papers_agent.json" --pdf-dir "<run_dir>\pdfs"
```

PDF names follow:

```text
{year} {conference} {paper title}.pdf
```

For each selected paper, record a short reason grounded in the definition. Mark uncertain papers as `borderline` in `agent_selection_notes.json` instead of hiding uncertainty.

## Unsupported Venue Workflow

When the user wants another conference or journal, prefer adding a reusable fetcher to the bundled tool. Use official public sources first: proceedings pages, publisher pages, OpenReview, ACL Anthology, CVF, PMLR, arXiv export, or the venue's own API.

Recommended fetcher path:

1. Add a fetcher in `TOOL_ROOT/paper_downloader/fetchers.py` that returns `Paper` objects.
2. Extract at least `title`, `abstract`, and `download_url`; include `keywords` when available.
3. Prefer structured APIs or existing JSON. If only HTML exists, parse carefully and resolve relative PDF links to absolute URLs.
4. Update `fetch_papers`, CLI choices, source validation, and display naming as needed for the venue and year.
5. Add small parser/unit tests if working in a repository checkout; otherwise run a small `--limit` smoke test.
6. Use the normal built-in command with the new source.

Fast one-off path:

1. Gather official metadata into a JSON list with `title`, `abstract`, and `download_url`.
2. Save it under `TOOL_ROOT/custom_sources/{venue_slug}-{year}.json` or another user-approved path.
3. Normalize it through:

```powershell
python main.py --input-json "<papers.json>" --venue "<venue>" --year <year> --direction "<direction>" --version v2
```

4. Continue with the agent screening workflow or the API workflow.

## Paper Classification

After PDFs are downloaded, ask whether the user wants the downloaded papers classified. If yes, ask the user for a classification method before classifying.

Supported classification methods:

- User-defined taxonomy: user provides category names and the criteria for each category.
- Category names only: user provides category names; infer concise criteria, show them to the user, then classify.
- Review-derived taxonomy: extract method types, problem types, application areas, evaluation types, or another taxonomy from the review paper.
- Agent-proposed taxonomy: create concise categories from the selected papers when the user asks you to decide.

Suggested user format:

```text
Classify papers into:
1. Theory / Definition: papers mainly about concepts, definitions, or theoretical framing
2. Method / Algorithm: papers mainly proposing a new method, model, training process, or inference process
3. Benchmark / Evaluation: papers mainly about datasets, benchmarks, metrics, or evaluation protocols
4. Application / System: papers mainly about deployed systems, tools, or concrete applications

Use one primary category per paper. Mark uncertain papers as Borderline.
```

Save classification outputs in the run directory:

```text
paper_classification.json
paper_classification_notes.json
```

Use fields:

```text
title, pdf_path, category, confidence, reason, evidence, borderline
```

Default to one primary category per paper. Use multiple labels only when the user explicitly asks. Prefer title, abstract, extracted definition, and relevant PDF passages as evidence; do not classify from filename alone.

## Constraints

- Do not call the bundled OpenAI-compatible client during agent screening unless the user asks for the CLI/API workflow.
- Do not overwrite user-selected JSON, definition, note, or classification files unless the user asks.
- Preserve metadata fields: `conference`, `year`, `title`, `abstract`, `keywords`, `download_url`.
- For unsupported venues, prefer adding a reusable fetcher; use custom JSON when the user wants a quick one-off source.
