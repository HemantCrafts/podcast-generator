import io
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import blog_summarizer as summarizer


class SummaryTests(unittest.TestCase):
    def setUp(self):
        summarizer._summary_cache.clear()
        self.environment = patch.dict(
            summarizer.os.environ,
            {"FIRECRAWL_API_KEY": "test-firecrawl", "GEMINI_API_KEY": "test-gemini", "GEMINI_MODEL": "gemini/test-model"},
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.addCleanup(summarizer._summary_cache.clear)

    def test_direct_calls_and_cache_hit(self):
        timings = {}
        updates = []
        with patch.object(summarizer, "_scrape_article", return_value="Article") as scrape, \
             patch.object(summarizer, "_generate_summary", return_value="Summary") as generate:
            self.assertEqual(summarizer.summarize_blog("https://example.com/article#intro"), "Summary")
            self.assertEqual(summarizer.summarize_blog(
                "https://example.com/article", timings=timings,
                progress=lambda value, message: updates.append((value, message)),
            ), "Summary")
            scrape.assert_called_once()
            generate.assert_called_once_with("Article", "test-model", "test-gemini")
        self.assertTrue(timings["cache_hit"])
        self.assertEqual(timings["firecrawl"], 0)
        self.assertTrue(updates)

    def test_forced_refresh(self):
        with patch.object(summarizer, "_scrape_article", return_value="Article") as scrape, \
             patch.object(summarizer, "_generate_summary", side_effect=["Old", "New"]):
            summarizer.summarize_blog("https://example.com")
            self.assertEqual(summarizer.summarize_blog("https://example.com", use_cache=False), "New")
            self.assertEqual(scrape.call_count, 2)
            self.assertEqual(summarizer.summarize_blog("https://example.com"), "New")

    def test_expired_cache(self):
        with patch.object(summarizer, "monotonic", return_value=100):
            summarizer._store_cached(("url", "model"), "Summary")
        with patch.object(summarizer, "monotonic", return_value=100 + summarizer.CACHE_TTL_SECONDS):
            self.assertIsNone(summarizer._get_cached(("url", "model")))

    def test_cache_has_size_limit(self):
        for index in range(summarizer.CACHE_MAX_ENTRIES + 1):
            summarizer._store_cached((str(index), "model"), "Summary")
        self.assertEqual(len(summarizer._summary_cache), summarizer.CACHE_MAX_ENTRIES)
        self.assertIsNone(summarizer._get_cached(("0", "model")))

    def test_failed_summary_is_not_cached(self):
        with patch.object(summarizer, "_scrape_article", return_value="Article"), \
             patch.object(summarizer, "_generate_summary", side_effect=RuntimeError("Failed")):
            with self.assertRaises(RuntimeError):
                summarizer.summarize_blog("https://example.com")
        self.assertFalse(summarizer._summary_cache)

    def test_invalid_url_does_not_call_provider(self):
        with patch.object(summarizer, "_scrape_article") as scrape:
            with self.assertRaises(ValueError):
                summarizer.summarize_blog("not-a-url")
            scrape.assert_not_called()

    def test_model_change_misses_cache(self):
        with patch.object(summarizer, "_scrape_article", return_value="Article") as scrape, \
             patch.object(summarizer, "_generate_summary", return_value="Summary"):
            summarizer.summarize_blog("https://example.com")
            with patch.dict(summarizer.os.environ, {"GEMINI_MODEL": "other-model"}):
                summarizer.summarize_blog("https://example.com")
            self.assertEqual(scrape.call_count, 2)

    def test_scrape_requires_markdown(self):
        with patch.object(summarizer, "_post_json", return_value={"success": True, "data": {"metadata": {}}}):
            with self.assertRaisesRegex(RuntimeError, "no article text"):
                summarizer._scrape_article("https://example.com", "test")

    def test_single_gemini_request_uses_complete_article(self):
        result = {"candidates": [{"finishReason": "STOP", "content": {"parts": [
            {"text": "Internal", "thought": True}, {"text": "Spoken summary"},
        ]}}]}
        article = "Full article " * 1000
        with patch.object(summarizer, "_post_json", return_value=result) as post:
            self.assertEqual(summarizer._generate_summary(article, "test-model", "test"), "Spoken summary")
        post.assert_called_once()
        self.assertEqual(post.call_args.args[1]["contents"][0]["parts"][0]["text"], article)

    def test_incomplete_gemini_output_is_rejected(self):
        with patch.object(summarizer, "_post_json", return_value={"candidates": [{"finishReason": "MAX_TOKENS"}]}):
            with self.assertRaisesRegex(RuntimeError, "did not complete"):
                summarizer._generate_summary("Article", "test-model", "test")

    def test_http_failure_has_stage_and_status(self):
        error = HTTPError("https://example.com", 429, "Rate limited", {}, io.BytesIO(b"{}"))
        with patch.object(summarizer, "urlopen", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "Gemini returned HTTP 429"):
                summarizer._post_json("https://example.com", {}, {}, "Gemini", 90)

    def test_timeout_has_stage(self):
        with patch.object(summarizer, "urlopen", side_effect=TimeoutError):
            with self.assertRaisesRegex(RuntimeError, "Firecrawl connection failed or timed out"):
                summarizer._post_json("https://example.com", {}, {}, "Firecrawl", 60)


if __name__ == "__main__":
    unittest.main()
