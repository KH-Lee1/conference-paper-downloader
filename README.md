# Conference Paper Downloader

Download public ICLR, ICML, and NeurIPS papers by research direction using a review-paper definition.

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

```powershell
python main.py --conference iclr --year 2025 --direction "..." --review-paper "..."
python main.py --conference iclr --year 2025 --direction "..." --version v2
```

Required arguments:

- `--conference`: `iclr`, `icml`, or `neurips`
- `--year`: `2025` or `2026`
- `--direction`: research direction phrase
- `--review-paper`: required for `v1`; absolute PDF path, or a file name/path relative to `review_papers/`

Optional arguments:

- `--version`: `v1` extracts JSON, derives a review definition, then downloads matches; `v2` extracts JSON only. Defaults to `v1`.
- `--output-dir`: defaults to `downloads`
- `--limit`: limits the number of fetched papers for testing
- `--force`: overwrites existing PDF files
- `--max-workers`: controls LLM and download concurrency

Outputs are written under:

```text
downloads/{conference}-{year}/{direction_slug}-{timestamp}/
```

`v1` runs contain `all_papers.json`, `selected_papers.json`, `run_status.json`, and `pdfs/`. The extracted definition is saved under:

```text
definitions/{direction_slug}/{review_slug}-{timestamp}.json
```

`v2` runs contain only the extracted metadata JSON (`all_papers.json`) plus `run_status.json`; no review definition extraction, LLM filtering, or PDF download is performed.

Metadata JSON fields are:

```text
conference, year, title, abstract, keywords, download_url
```

Downloaded PDFs are named as:

```text
{year} {conference} {paper title}.pdf
```

Example:

```text
2025 ICLR A Paper.pdf
```
