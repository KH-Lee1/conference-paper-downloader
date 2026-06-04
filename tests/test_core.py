import io
import json
import subprocess
import sys
import threading
import unittest
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from paper_downloader.definitions import (
    direction_slug,
    extract_definition_from_text,
    load_latest_definition,
    save_definition,
)
from paper_downloader.downloader import download_pdf, paper_pdf_name, sanitize_filename
from paper_downloader.fetchers import (
    _papers_from_virtual_data,
    _parse_neurips_abstract,
    _parse_neurips_index,
    _parse_pmlr_abstract,
    _parse_pmlr_index,
)
from paper_downloader.filters import normalize_text, select_by_llm
from paper_downloader.llm import OpenAICompatibleClient, parse_yes_no
from paper_downloader.models import Paper
from paper_downloader.runner import main as runner_main
from paper_downloader.runner import load_input_json_papers, process_exact_parallel, run


class UtilityTests(unittest.TestCase):
    def test_normalize_text_handles_case_spacing_and_hyphens(self):
        self.assertEqual(normalize_text("Large-Language  Models"), "large language models")

    def test_sanitize_filename_removes_windows_invalid_chars(self):
        self.assertEqual(sanitize_filename('A:B/C*D?'), "A B C D")

    def test_paper_pdf_name_uses_year_conference_and_title(self):
        paper = Paper("iclr", 2025, "A: Paper", "", [], "https://example.test/p.pdf")
        self.assertEqual(paper_pdf_name(paper), "2025 ICLR A Paper.pdf")

    def test_direction_slug_is_stable_for_definition_paths(self):
        self.assertEqual(direction_slug("Self-Evolving Agents"), "self-evolving-agents")

    def test_paper_json_keeps_keywords_metadata(self):
        paper = Paper("iclr", 2025, "A Paper", "Abstract", ["Agents"], "https://example.test/p.pdf")
        self.assertEqual(paper.to_json()["keywords"], ["Agents"])

    def test_paper_from_json_works_without_keywords(self):
        paper = Paper.from_json(
            {
                "conference": "iclr",
                "year": 2025,
                "title": "A Paper",
                "abstract": "Abstract",
                "download_url": "https://example.test/p.pdf",
            }
        )
        self.assertEqual(paper.keywords, [])


class FilterTests(unittest.TestCase):

    def test_select_by_llm_only_accepts_yes(self):
        class FakeClient:
            def matches(self, *, direction, title, abstract):
                return title == "match"

        papers = [
            Paper("iclr", 2025, "match", "", [], "https://example.test/1.pdf"),
            Paper("iclr", 2025, "skip", "", [], "https://example.test/2.pdf"),
        ]
        selected = select_by_llm(papers, "agents", FakeClient())
        self.assertEqual([paper.title for paper in selected], ["match"])


class DownloaderTests(unittest.TestCase):
    def test_download_pdf_writes_existing_and_missing_url_without_status(self):
        class FakeHttpClient:
            def get_bytes(self, url, headers=None):
                return b"%PDF-1.7\n"

        with TemporaryDirectory() as tmp:
            pdf_dir = Path(tmp)
            paper = Paper("iclr", 2025, "A: Paper", "", [], "https://example.test/p.pdf")
            target = download_pdf(
                paper,
                pdf_dir=pdf_dir,
                force=False,
                http_client=FakeHttpClient(),
            )
            self.assertEqual(target, pdf_dir / "2025 ICLR A Paper.pdf")
            self.assertTrue(target.exists())
            existing = download_pdf(
                paper,
                pdf_dir=pdf_dir,
                force=False,
                http_client=FakeHttpClient(),
            )
            self.assertEqual(existing, target)
            missing = Paper("iclr", 2025, "Missing URL", "", [], "")
            missing_target = download_pdf(
                missing,
                pdf_dir=pdf_dir,
                force=False,
                http_client=FakeHttpClient(),
            )
            self.assertIsNone(missing_target)


class RunnerTests(unittest.TestCase):
    def test_v2_extracts_json_only(self):
        papers = [Paper("iclr", 2025, "Only JSON", "Abstract", [], "https://example.test/p.pdf")]
        with TemporaryDirectory() as tmp, patch("paper_downloader.runner.fetch_papers", return_value=papers):
            args = Namespace(
                conference="iclr",
                input_json=None,
                venue=None,
                year=2025,
                direction="agents",
                version="v2",
                review_paper=None,
                output_dir=Path(tmp),
                limit=1,
                force=False,
                max_workers=1,
                timeout=5,
            )
            run_dir = run(args)
            self.assertTrue((run_dir / "all_papers.json").exists())
            self.assertFalse((run_dir / "selected_papers.json").exists())
            self.assertFalse((run_dir / "pdfs").exists())
            all_papers = json.loads((run_dir / "all_papers.json").read_text(encoding="utf-8"))
            self.assertNotIn("pdf_status", all_papers[0])
            self.assertIn("keywords", all_papers[0])
            status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["version"], "v2")
            self.assertEqual(status["conference"], "iclr")
            self.assertEqual(status["venue"], "iclr")
            self.assertIsNone(status["input_json"])
            self.assertEqual(status["stage"], "json_only")
            self.assertEqual(status["total_papers"], 1)
            self.assertEqual(status["selected_papers"], 0)
            self.assertIsNone(status["review_paper"])
            self.assertIsNone(status["definition_file"])
            self.assertFalse(status["definition_used"])
            self.assertNotIn("all_pdf_status", status)
            self.assertNotIn("selected_pdf_status", status)

    def test_method_argument_is_removed(self):
        with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit) as context:
            runner_main(
                [
                    "--conference",
                    "iclr",
                    "--year",
                    "2025",
                    "--direction",
                    "agents",
                    "--method",
                    "exact",
                    "--review-paper",
                    "review.pdf",
                ]
            )
            self.assertEqual(context.exception.code, 2)

    def test_source_argument_is_required(self):
        with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit) as context:
            runner_main(
                [
                    "--year",
                    "2025",
                    "--direction",
                    "agents",
                    "--version",
                    "v2",
                ]
            )
        self.assertEqual(context.exception.code, 2)

    def test_conference_and_input_json_are_mutually_exclusive(self):
        with TemporaryDirectory() as tmp, patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit) as context:
            input_json = Path(tmp) / "papers.json"
            input_json.write_text("[]", encoding="utf-8")
            runner_main(
                [
                    "--conference",
                    "iclr",
                    "--input-json",
                    str(input_json),
                    "--venue",
                    "ACL",
                    "--year",
                    "2025",
                    "--direction",
                    "agents",
                    "--version",
                    "v2",
                ]
            )
        self.assertEqual(context.exception.code, 2)

    def test_input_json_requires_venue(self):
        with TemporaryDirectory() as tmp, patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit) as context:
            input_json = Path(tmp) / "papers.json"
            input_json.write_text("[]", encoding="utf-8")
            runner_main(
                [
                    "--input-json",
                    str(input_json),
                    "--year",
                    "2025",
                    "--direction",
                    "agents",
                    "--version",
                    "v2",
                ]
            )
        self.assertEqual(context.exception.code, 2)

    def test_builtin_conference_years_are_limited(self):
        with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit) as context:
            runner_main(
                [
                    "--conference",
                    "iclr",
                    "--year",
                    "2024",
                    "--direction",
                    "agents",
                    "--version",
                    "v2",
                ]
            )
        self.assertEqual(context.exception.code, 2)

    def test_v3_version_is_removed(self):
        with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit) as context:
            runner_main(
                [
                    "--conference",
                    "iclr",
                    "--year",
                    "2025",
                    "--direction",
                    "agents",
                    "--review-paper",
                    "review.pdf",
                    "--version",
                    "v3",
                ]
            )
        self.assertEqual(context.exception.code, 2)

    def test_v1_requires_review_paper(self):
        with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit) as context:
            runner_main(
                [
                    "--conference",
                    "iclr",
                    "--year",
                    "2025",
                    "--direction",
                    "agents",
                ]
            )
        self.assertEqual(context.exception.code, 2)

    def test_v1_extracts_definition_then_processes_papers(self):
        papers = [Paper("iclr", 2025, "Defined Match", "Abstract", ["agent"], "https://example.test/p.pdf")]
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            definition_file = tmp_path / "definitions" / "agents" / "review-20250101.json"
            definition_file.parent.mkdir(parents=True)
            definition_file.write_text(
                json.dumps(
                    {
                        "direction": "agents",
                        "review_paper": "review.pdf",
                        "definition": "Agents that improve through feedback.",
                        "model": "fake-model",
                        "created_at": "20250101",
                    }
                ),
                encoding="utf-8",
            )

            fake_client = object()
            captured = {}

            def fake_extract_definition_from_review(**kwargs):
                captured["extract_kwargs"] = kwargs
                return definition_file

            def fake_process_exact_parallel(args, run_dir, papers_arg, *, llm_client, definition):
                captured["definition"] = definition
                captured["llm_client"] = llm_client
                return papers_arg

            args = Namespace(
                conference="iclr",
                input_json=None,
                venue=None,
                year=2025,
                direction="agents",
                version="v1",
                review_paper="review.pdf",
                output_dir=tmp_path / "runs",
                limit=1,
                force=False,
                max_workers=1,
                timeout=5,
            )
            with (
                patch("paper_downloader.runner.fetch_papers", return_value=papers),
                patch("paper_downloader.runner.OpenAICompatibleClient", return_value=fake_client),
                patch("paper_downloader.runner.extract_definition_from_review", side_effect=fake_extract_definition_from_review),
                patch("paper_downloader.runner.process_exact_parallel", side_effect=fake_process_exact_parallel),
            ):
                run_dir = run(args)

            self.assertEqual(captured["definition"], "Agents that improve through feedback.")
            self.assertIs(captured["llm_client"], fake_client)
            self.assertEqual(captured["extract_kwargs"]["review_paper"], "review.pdf")
            status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["review_paper"], "review.pdf")
            self.assertEqual(status["definition_file"], str(definition_file))
            self.assertTrue(status["definition_used"])

    def test_v2_input_json_standardizes_custom_source(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_json = tmp_path / "papers.json"
            input_json.write_text(
                json.dumps(
                    [
                        {
                            "title": "Custom Paper",
                            "abstract": "A custom abstract.",
                            "download_url": "https://example.test/custom.pdf",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            args = Namespace(
                conference=None,
                input_json=input_json,
                venue="ACL",
                year=2024,
                direction="agents",
                version="v2",
                review_paper=None,
                output_dir=tmp_path / "runs",
                limit=None,
                force=False,
                max_workers=1,
                timeout=5,
            )
            run_dir = run(args)

            self.assertEqual(run_dir.parent.name, "acl-2024")
            all_papers = json.loads((run_dir / "all_papers.json").read_text(encoding="utf-8"))
            self.assertEqual(all_papers[0]["conference"], "acl")
            self.assertEqual(all_papers[0]["year"], 2024)
            self.assertEqual(all_papers[0]["keywords"], [])
            status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
            self.assertIsNone(status["conference"])
            self.assertEqual(status["venue"], "ACL")
            self.assertEqual(status["input_json"], str(input_json))

    def test_load_input_json_papers_fills_missing_fields_and_applies_limit(self):
        with TemporaryDirectory() as tmp:
            input_json = Path(tmp) / "papers.json"
            input_json.write_text(
                json.dumps(
                    [
                        {
                            "title": "First",
                            "abstract": "Abstract",
                            "download_url": "https://example.test/1.pdf",
                        },
                        {
                            "conference": "custom",
                            "year": "2023",
                            "title": "Second",
                            "abstract": "Abstract",
                            "keywords": ["x"],
                            "download_url": "https://example.test/2.pdf",
                        },
                    ]
                ),
                encoding="utf-8",
            )
            papers = load_input_json_papers(input_json, venue="ACL", year=2024, limit=1)
            self.assertEqual(len(papers), 1)
            self.assertEqual(papers[0].conference, "acl")
            self.assertEqual(papers[0].year, 2024)
            self.assertEqual(papers[0].keywords, [])

    def test_v1_input_json_uses_same_definition_pipeline(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_json = tmp_path / "papers.json"
            input_json.write_text(
                json.dumps(
                    [
                        {
                            "title": "Defined Custom Match",
                            "abstract": "Abstract",
                            "download_url": "https://example.test/p.pdf",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            definition_file = tmp_path / "definitions" / "agents" / "review-20250101.json"
            definition_file.parent.mkdir(parents=True)
            definition_file.write_text(
                json.dumps(
                    {
                        "direction": "agents",
                        "review_paper": "review.pdf",
                        "definition": "Agents that improve through feedback.",
                        "model": "fake-model",
                        "created_at": "20250101",
                    }
                ),
                encoding="utf-8",
            )

            captured = {}

            def fake_process_exact_parallel(args, run_dir, papers_arg, *, llm_client, definition):
                captured["papers"] = papers_arg
                captured["definition"] = definition
                return papers_arg

            args = Namespace(
                conference=None,
                input_json=input_json,
                venue="ACL",
                year=2024,
                direction="agents",
                version="v1",
                review_paper="review.pdf",
                output_dir=tmp_path / "runs",
                limit=None,
                force=False,
                max_workers=1,
                timeout=5,
            )
            with (
                patch("paper_downloader.runner.OpenAICompatibleClient", return_value=object()),
                patch("paper_downloader.runner.extract_definition_from_review", return_value=definition_file),
                patch("paper_downloader.runner.process_exact_parallel", side_effect=fake_process_exact_parallel),
            ):
                run(args)

            self.assertEqual(captured["definition"], "Agents that improve through feedback.")
            self.assertEqual(captured["papers"][0].title, "Defined Custom Match")
            self.assertEqual(captured["papers"][0].conference, "acl")

    def test_exact_pipeline_downloads_yes_before_all_llm_finishes_and_preserves_order(self):
        events = []
        download_started = threading.Event()

        class FakeLlmClient:
            def matches(self, *, direction, title, abstract):
                if title == "Slow Yes":
                    events.append("llm slow start")
                    self.assert_download_starts_before_slow_finishes()
                    events.append("llm slow done")
                    return True
                events.append("llm fast done")
                return True

            def assert_download_starts_before_slow_finishes(self):
                self_download_started = download_started.wait(timeout=2)
                if not self_download_started:
                    raise AssertionError("download did not start while slow LLM task was running")

        def fake_download(paper, *, pdf_dir, force, http_client):
            events.append(f"download {paper.title}")
            download_started.set()
            return "downloaded"

        papers = [
            Paper("iclr", 2025, "Slow Yes", "Abstract", [], "https://example.test/slow.pdf"),
            Paper("iclr", 2025, "Fast Yes", "Abstract", [], "https://example.test/fast.pdf"),
        ]
        with TemporaryDirectory() as tmp:
            args = Namespace(
                direction="agents",
                force=False,
                max_workers=2,
                timeout=5,
            )
            selected = process_exact_parallel(
                args,
                Path(tmp),
                papers,
                llm_client=FakeLlmClient(),
                download_func=fake_download,
            )

        self.assertEqual([paper.title for paper in selected], ["Slow Yes", "Fast Yes"])
        self.assertLess(events.index("download Fast Yes"), events.index("llm slow done"))
        self.assertFalse(any(hasattr(paper, "pdf_status") for paper in selected))

    def test_exact_pipeline_passes_review_definition_to_llm(self):
        seen = {}

        class FakeLlmClient:
            def matches(self, *, direction, title, abstract, definition):
                seen["direction"] = direction
                seen["title"] = title
                seen["abstract"] = abstract
                seen["definition"] = definition
                return True

        def fake_download(paper, *, pdf_dir, force, http_client):
            return "downloaded"

        papers = [Paper("iclr", 2025, "Defined Match", "Abstract", [], "https://example.test/p.pdf")]
        with TemporaryDirectory() as tmp:
            args = Namespace(
                direction="self-evolving agents",
                force=False,
                max_workers=1,
                timeout=5,
            )
            selected = process_exact_parallel(
                args,
                Path(tmp),
                papers,
                llm_client=FakeLlmClient(),
                definition="Agents that improve themselves through feedback.",
                download_func=fake_download,
            )

        self.assertEqual([paper.title for paper in selected], ["Defined Match"])
        self.assertEqual(seen["definition"], "Agents that improve themselves through feedback.")


class LlmTests(unittest.TestCase):
    def test_parse_yes_no_requires_clean_full_answer(self):
        self.assertIs(parse_yes_no("maybe yes"), None)
        self.assertTrue(parse_yes_no(" yes "))
        self.assertFalse(parse_yes_no("NO"))

    def test_openai_compatible_client_requests_yes_no_only(self):
        class FakeHttpClient:
            def __init__(self):
                self.payload = None
                self.headers = None
                self.url = None

            def post_json(self, url, payload, headers=None):
                self.url = url
                self.payload = payload
                self.headers = headers
                return {"choices": [{"message": {"content": "yes"}}]}

        fake_http = FakeHttpClient()
        client = OpenAICompatibleClient(
            api_key="test-key",
            base_url="https://llm.example/v1",
            model="test-model",
            http_client=fake_http,
        )
        self.assertTrue(client.matches(direction="agents", title="Agent Paper", abstract="About agents."))
        self.assertEqual(fake_http.url, "https://llm.example/v1/chat/completions")
        self.assertEqual(fake_http.payload["model"], "test-model")
        user_prompt = fake_http.payload["messages"][1]["content"]
        self.assertIn("Reply exactly yes or no", user_prompt)
        self.assertEqual(fake_http.headers["Authorization"], "Bearer test-key")

    def test_openai_compatible_client_includes_review_definition(self):
        class FakeHttpClient:
            def __init__(self):
                self.payload = None

            def post_json(self, url, payload, headers=None):
                self.payload = payload
                return {"choices": [{"message": {"content": "yes"}}]}

        fake_http = FakeHttpClient()
        client = OpenAICompatibleClient(
            api_key="test-key",
            base_url="https://llm.example/v1",
            model="test-model",
            http_client=fake_http,
        )
        self.assertTrue(
            client.matches(
                direction="agents",
                title="Agent Paper",
                abstract="About agents.",
                definition="Agents that improve through feedback.",
            )
        )
        user_prompt = fake_http.payload["messages"][1]["content"]
        self.assertIn("Definition extracted from the review paper", user_prompt)
        self.assertIn("Agents that improve through feedback.", user_prompt)


class DefinitionTests(unittest.TestCase):
    def test_extract_definition_rejects_empty_review_text(self):
        class FakeClient:
            def complete_prompt(self, **kwargs):
                return "unused"

        with self.assertRaises(ValueError):
            extract_definition_from_text(direction="agents", review_text="  \n ", llm_client=FakeClient())

    def test_extract_definition_prompt_contains_direction_and_review_text(self):
        class FakeClient:
            def __init__(self):
                self.user_prompt = None

            def complete_prompt(self, *, system_prompt, user_prompt, max_tokens, temperature):
                self.user_prompt = user_prompt
                return "Agents that improve themselves through feedback."

        fake = FakeClient()
        definition = extract_definition_from_text(
            direction="self-evolving agents",
            review_text="The survey defines self-evolving agents as agents that adapt from feedback.",
            llm_client=fake,
        )
        self.assertEqual(definition, "Agents that improve themselves through feedback.")
        self.assertIn("self-evolving agents", fake.user_prompt)
        self.assertIn("The survey defines self-evolving agents", fake.user_prompt)

    def test_save_and_load_latest_definition_json(self):
        with TemporaryDirectory() as tmp:
            output_root = Path(tmp) / "definitions"
            review_paper = Path(tmp) / "26 TMLR Self-Evolving Agents.pdf"
            first = save_definition(
                direction="self-evolving agents",
                review_paper=review_paper,
                definition="old definition",
                model="test-model",
                output_root=output_root,
                created_at="20250101-000000",
            )
            second = save_definition(
                direction="self-evolving agents",
                review_paper=review_paper,
                definition="new definition",
                model="test-model",
                output_root=output_root,
                created_at="20250102-000000",
            )

            self.assertEqual(first.parent.name, "self-evolving-agents")
            loaded_path, definition = load_latest_definition("self-evolving agents", definitions_root=output_root)
            self.assertEqual(loaded_path, second)
            self.assertEqual(definition, "new definition")
            data = json.loads(second.read_text(encoding="utf-8"))
            self.assertEqual(data["direction"], "self-evolving agents")
            self.assertEqual(data["definition"], "new definition")


class ParserTests(unittest.TestCase):
    def test_parse_pmlr_index_and_abstract(self):
        index_html = """
        <div class="paper">
          <p class="title">Sample Paper</p>
          <p class="links">
            [<a href="sample.html">abs</a>]
            [<a href="https://raw.example/sample.pdf">Download PDF</a>]
          </p>
        </div>
        """
        entries = _parse_pmlr_index(index_html, "https://proceedings.mlr.press/v267/")
        self.assertEqual(entries[0]["title"], "Sample Paper")
        self.assertEqual(entries[0]["abstract_url"], "https://proceedings.mlr.press/v267/sample.html")
        self.assertEqual(entries[0]["download_url"], "https://raw.example/sample.pdf")

        abstract = _parse_pmlr_abstract('<div id="abstract">Abstract This is the abstract.</div>')
        self.assertEqual(abstract, "This is the abstract.")

    def test_parse_neurips_index_and_abstract(self):
        index_html = """
        <a title="paper title" href="/paper_files/paper/2025/hash/abc-Abstract-Conference.html">Title A</a>
        """
        entries = _parse_neurips_index(index_html, "https://proceedings.neurips.cc")
        self.assertEqual(entries[0]["title"], "Title A")
        self.assertIn("abc-Abstract-Conference.html", entries[0]["abstract_url"])

        abstract_html = """
        <a href="abc-Paper-Conference.pdf">Paper</a>
        <h4>Abstract</h4><p>NeurIPS abstract text.</p>
        """
        detail = _parse_neurips_abstract(
            abstract_html,
            "https://proceedings.neurips.cc/paper_files/paper/2025/hash/abc-Abstract-Conference.html",
        )
        self.assertEqual(detail["abstract"], "NeurIPS abstract text.")
        self.assertTrue(detail["download_url"].endswith("abc-Paper-Conference.pdf"))

    def test_virtual_data_to_papers(self):
        papers_data = {
            "results": [
                {
                    "id": 1,
                    "name": "Virtual Paper",
                    "topic": "Deep Learning->Large Language Models",
                    "keywords": [],
                    "paper_url": "https://openreview.net/forum?id=abc123",
                    "paper_pdf_url": None,
                }
            ]
        }
        papers = _papers_from_virtual_data(
            "icml",
            2026,
            papers_data,
            {"1": "Virtual abstract"},
            base_url="https://icml.cc",
        )
        self.assertEqual(papers[0].abstract, "Virtual abstract")
        self.assertEqual(papers[0].download_url, "https://openreview.net/pdf?id=abc123")
        self.assertIn("Deep Learning->Large Language Models", papers[0].keywords)


class SkillBundleTests(unittest.TestCase):
    def test_standalone_skill_scripts_show_help(self):
        root = Path(__file__).resolve().parents[1]
        tool_root = root / "skills" / "conference-paper-downloader" / "scripts" / "conference-paper-downloader"

        main_result = subprocess.run(
            [sys.executable, str(tool_root / "main.py"), "--help"],
            cwd=tool_root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(main_result.returncode, 0, main_result.stderr)
        self.assertIn("--input-json", main_result.stdout)

        download_result = subprocess.run(
            [sys.executable, str(tool_root / "download_from_json.py"), "--help"],
            cwd=tool_root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(download_result.returncode, 0, download_result.stderr)
        self.assertIn("--selected-json", download_result.stdout)


if __name__ == "__main__":
    unittest.main()
