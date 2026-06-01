---
name: conference-paper-downloader
description: Download conference papers for a research direction using a review paper as the source of screening criteria. Use when the user wants an agent to collect ICLR, ICML, or NeurIPS paper metadata, infer a direction definition from a review PDF, judge papers by title and abstract, and download selected PDFs without relying on the project's OpenAI API workflow.
---

# Conference Paper Downloader

Use this skill to screen and download conference papers for any research direction using a review paper as the grounding source.

## Workflow

1. Confirm the project root: use the directory that contains `main.py`.
2. Ask the user to place one review PDF for the target direction under `review_papers/` if it is not already there.
3. Get paper metadata:

```powershell
python main.py --conference <iclr|icml|neurips> --year <2025|2026> --direction "<direction>" --version v2
```

Use an existing `all_papers.json` if the user points to one.

4. Read the review PDF and extract a concise screening definition for the requested direction. Save it under:

```text
definitions/{direction_slug}/{review_slug}-{timestamp}.json
```

Include the direction, review path, definition, and creation time.

5. Screen papers from `all_papers.json` using only the extracted definition, paper title, and abstract. Use `keywords` only as metadata, not as the deciding evidence.
6. Save selected papers and notes in the run directory:

```text
selected_papers_agent.json
agent_selection_notes.json
```

7. Download selected PDFs to `pdfs/` using the project's downloader module so filenames follow:

```text
{year} {conference} {paper title}.pdf
```

## Selection Notes

For each selected paper, record a short reason grounded in the extracted definition. Mark uncertain papers as `borderline` in `agent_selection_notes.json` instead of silently dropping the uncertainty.

## Constraints

- Do not call the project's OpenAI-compatible LLM client for the screening step unless the user explicitly asks for the CLI/API workflow.
- Do not overwrite existing user-selected JSON files unless the user asks.
- Preserve the metadata schema: `conference`, `year`, `title`, `abstract`, `keywords`, `download_url`.
