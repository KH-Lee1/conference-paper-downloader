---
name: conference-paper-downloader
description: Download conference or journal papers for a research direction using a review paper as the source of screening criteria. Use when the user wants an agent to collect built-in ICLR, ICML, or NeurIPS metadata, prepare custom JSON metadata for another venue, infer a direction definition from a review PDF, judge papers by title and abstract, and download selected PDFs without relying on the project's OpenAI API workflow.
---

# Conference Paper Downloader

Use this skill to screen and download conference papers for any research direction using a review paper as the grounding source.

## Workflow

1. Confirm the project root: use the directory that contains `main.py`.
2. Ask the user to place one review PDF for the target direction under `review_papers/` if it is not already there.
3. Get paper metadata for a built-in source:

```powershell
python main.py --conference <iclr|icml|neurips> --year <2025|2026> --direction "<direction>" --version v2
```

Use an existing `all_papers.json` if the user points to one.

For a conference or journal that is not built in, ask the user which path to use:

- Recommended: add a dedicated fetcher to the project, update tests, then use the normal built-in-source flow.
- Fast temporary option: gather metadata from the official source into a JSON list, then run the project with `--input-json` and `--venue`.

## Unsupported Venue Workflow

When the user wants another conference or journal, use the official public source first: proceedings pages, publisher pages, OpenReview, ACL Anthology, CVF, PMLR, arXiv search/export, or the venue's own API.

For the recommended dedicated fetcher path:

1. Add a new fetcher in `paper_downloader/fetchers.py` that returns `Paper` objects.
2. Use official public sources first: proceedings pages, publisher pages, OpenReview, ACL Anthology, CVF, PMLR, arXiv search/export, or the venue's own API.
3. Extract at least `title`, `abstract`, and `download_url` for each paper. Include `keywords` when available.
4. Prefer structured APIs or existing JSON over HTML scraping. If only HTML exists, parse pages carefully and resolve relative PDF links to absolute URLs.
5. Add the source to the CLI choices and source validation.
6. Add parser/unit tests with small HTML or JSON fixtures.
7. Run `python -m unittest discover -s tests`.
8. Use the normal built-in-source command:

```powershell
python main.py --conference <source> --year <year> --direction "<direction>" --version v2
```

For the fast temporary JSON path:

1. Find the official accepted-paper/proceedings page or API for the requested venue and year.
2. Extract at least `title`, `abstract`, and `download_url` for each paper. Include `keywords` when available.
3. Prefer structured APIs or existing JSON over HTML scraping. If only HTML exists, parse pages carefully and resolve relative PDF links to absolute URLs.
4. Save the result as a JSON list, for example `custom_sources/{venue_slug}-{year}.json`.
5. Validate that the file is a JSON list and that each useful record has a title plus either an abstract or enough metadata for screening.
6. Normalize through the project with:

```powershell
python main.py --input-json "custom_sources/<venue_slug>-<year>.json" --venue "<venue>" --year <year> --direction "<direction>" --version v2
```

7. Continue the agent screening workflow from the generated `all_papers.json`.

The custom JSON list must use this schema, with `conference`, `year`, and `keywords` optional:

```text
conference, year, title, abstract, keywords, download_url
```

Then normalize it through the project:

```powershell
python main.py --input-json "<papers.json>" --venue "<venue>" --year <year> --direction "<direction>" --version v2
```

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
- For unsupported venues, prefer adding a reusable built-in fetcher unless the user explicitly wants a quick one-off JSON workflow.
