# Conference Paper Downloader

Download papers by research direction using a review-paper definition. Built-in fetchers support ICLR, ICML, and NeurIPS; custom JSON input supports other conferences and journals.

## Setup

Install dependencies first:

```powershell
pip install -r requirements.txt
```

Configure an OpenAI-compatible chat completions API before running the default download workflow:

```powershell
$env:OPENAI_API_KEY = "..."
$env:OPENAI_BASE_URL = "..."
$env:OPENAI_MODEL = "..."
```

Place a review PDF for the target research direction under `review_papers/`. The default workflow extracts the direction definition from this review, then uses that definition with each paper title and abstract to decide whether to download the PDF.

## Usage

Built-in sources:

```powershell
python main.py --conference iclr --year 2025 --direction "..." --review-paper "review.pdf"
python main.py --conference iclr --year 2025 --direction "..." --version v2
```

Custom conference or journal JSON:

```powershell
python main.py --input-json "papers.json" --venue "ACL" --year 2025 --direction "..." --review-paper "..."
python main.py --input-json "papers.json" --venue "Nature Machine Intelligence" --year 2024 --direction "..." --version v2
```

Required arguments:

- Use exactly one source argument:
  - `--conference`: built-in source, one of `iclr`, `icml`, or `neurips`
  - `--input-json`: custom paper metadata JSON list
- `--venue`: required with `--input-json`; source name such as `ACL`, `CVPR`, or a journal name
- `--year`: paper year; built-in sources currently support `2025` and `2026`
- `--direction`: research direction phrase
- `--review-paper`: required for `v1`; absolute PDF path, or a file name/path relative to `review_papers/`

Optional arguments:

- `--version`: `v1` extracts JSON, derives a review definition, then downloads matches; `v2` extracts JSON only. Defaults to `v1`.
- `--output-dir`: defaults to `downloads`
- `--limit`: limits the number of fetched or loaded papers for testing
- `--force`: overwrites existing PDF files
- `--max-workers`: controls LLM and download concurrency

Outputs are written under:

```text
downloads/{source_slug}-{year}/{direction_slug}-{timestamp}/
```

`v1` runs contain `all_papers.json`, `selected_papers.json`, `run_status.json`, and `pdfs/`. The extracted definition is saved under:

```text
definitions/{direction_slug}/{review_slug}-{timestamp}.json
```

`v2` runs contain only the extracted metadata JSON (`all_papers.json`) plus `run_status.json`; no review definition extraction, LLM filtering, or PDF download is performed.

## Custom JSON

Use custom JSON for any source that can be converted into title, abstract, and PDF URL records, such as ACL, CVPR, Nature/Science journals, or arXiv lists.

The input file must be a JSON list. Supported fields are:

```text
conference, year, title, abstract, keywords, download_url
```

`conference`, `year`, and `keywords` may be omitted. Missing `conference` and `year` are filled from `--venue` and `--year`; missing `keywords` becomes an empty list.

Minimal example:

```json
[
  {
    "title": "Example Paper",
    "abstract": "This paper studies ...",
    "download_url": "https://example.org/example.pdf"
  }
]
```

Downloaded PDFs are named as:

```text
{year} {conference} {paper title}.pdf
```

Example:

```text
2025 ICLR A Paper.pdf
```
