import unittest
from unittest.mock import patch

import multi_agent as ma
import blog_summarizer as summarizer


class DialogueParsingTests(unittest.TestCase):
    def test_parse_sections_kind_number_content(self):
        sections = ma._parse_sections(
            "INTRO: Hello.\nQUESTION 1: First?\nQUESTION 2: Second?\n"
            "ANSWER 1: Sure.\nANSWER 2: Yep.\nOUTRO: Bye."
        )
        self.assertEqual([s[0] for s in sections],
                         ["INTRO", "QUESTION", "QUESTION", "ANSWER", "ANSWER", "OUTRO"])
        self.assertEqual(sections[1][1], "1")
        self.assertEqual(" ".join(sections[4][2]), "Yep.")

    def test_split_dialogue_interleaves_host_and_expert(self):
        host = "INTRO: Welcome.\nQUESTION 1: Why?\nQUESTION 2: How?\nOUTRO: Thanks."
        expert = "ANSWER 1: Because.\nANSWER 2: Carefully."
        dialogue = ma._split_dialogue(host + "\n" + expert)
        self.assertEqual([speaker for speaker, _ in dialogue],
                         ["HOST", "HOST", "EXPERT", "HOST", "EXPERT", "HOST"])
        self.assertEqual(dialogue[0], ("HOST", "Welcome."))
        self.assertEqual(dialogue[2], ("EXPERT", "Because."))

    def test_split_dialogue_multiline_sections(self):
        host = "INTRO: Welcome to\n    the show.\nQUESTION 1: First question."
        dialogue = ma._split_dialogue(host)
        self.assertEqual(dialogue[0][1], "Welcome to the show.")

    def test_split_dialogue_fallback_without_questions(self):
        text = "HOST: A few remarks.\nEXPERT: A long answer here.\nHOST: Sign off."
        dialogue = ma._split_dialogue(text)
        self.assertEqual(len(dialogue), 3)
        self.assertEqual(dialogue[0], ("HOST", "A few remarks."))
        self.assertEqual(dialogue[1], ("EXPERT", "A long answer here."))

    def test_format_script_labels_speakers(self):
        dialogue = [("HOST", "Hello"), ("EXPERT", "Hi")]
        script = ma.format_script(dialogue)
        self.assertEqual(script, "HOST: Hello\n\nEXPERT: Hi")

    def test_trim_dialogue_enforces_turn_caps(self):
        dialogue = [
            ("HOST", "word " * 80),
            ("EXPERT", "word " * 150),
            ("HOST", "short"),
        ]
        trimmed = ma.trim_dialogue(dialogue)
        self.assertLessEqual(len(trimmed[0][1]), ma.MAX_HOST_TURN_CHARS)
        self.assertTrue(trimmed[0][1].endswith("…"))
        self.assertLessEqual(len(trimmed[1][1]), ma.MAX_EXPERT_TURN_CHARS)
        self.assertEqual(trimmed[2], ("HOST", "short"))

    def test_trim_turn_keeps_short_text(self):
        self.assertEqual(ma._trim_turn("Hello world", 100), "Hello world")

    def test_normalize_model_strips_prefixes(self):
        self.assertEqual(ma._normalize_model("  gemini/models/gemini-1  "), "gemini-1")

    def test_missing_keys_raise(self):
        with patch.dict(ma.os.environ, {"FIRECRAWL_API_KEY": "", "GEMINI_API_KEY": ""}):
            with self.assertRaisesRegex(ValueError, "FIRECRAWL_API_KEY"):
                ma._require_keys()


class AgentReplyTests(unittest.TestCase):
    def test_gemini_ignores_thinking_parts(self):
        result = {"candidates": [{"finishReason": "STOP", "content": {"parts": [
            {"text": "Internal", "thought": True}, {"text": "Spoken output"},
        ]}}]}
        with patch.object(ma, "_post_json", return_value=result) as post:
            reply = ma._generate_agent_reply("system", "user", "test-model", "test")
        self.assertEqual(reply, "Spoken output")
        self.assertEqual(post.call_args.args[1]["systemInstruction"]["parts"][0]["text"], "system")

    def test_incomplete_output_is_rejected(self):
        result = {"candidates": [{"finishReason": "MAX_TOKENS"}]}
        with patch.object(ma, "_post_json", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "did not complete"):
                ma._generate_agent_reply("system", "user", "test-model", "test")


class BuildConversationTests(unittest.TestCase):
    def setUp(self):
        summarizer._summary_cache.clear()
        self.environment = patch.dict(
            ma.os.environ,
            {"FIRECRAWL_API_KEY": "test-firecrawl",
             "GEMINI_API_KEY": "test-gemini",
             "GEMINI_MODEL": "gemini/test-model"},
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.addCleanup(summarizer._summary_cache.clear)

    def test_full_pipeline_runs_three_agents(self):
        host = "INTRO: Welcome.\nQUESTION 1: Explain it?\nOUTRO: Thanks."
        expert = "ANSWER 1: It works like this."
        with patch.object(ma, "_scrape_article", return_value="Article") as scrape, \
             patch.object(ma, "_generate_agent_reply",
                          side_effect=["Notes", host, expert]) as generate:
            script_text, dialogue = ma.build_conversation(
                "https://example.com/article#top", timings={}
            )
        scrape.assert_called_once_with("https://example.com/article", "test-firecrawl")
        self.assertEqual(generate.call_count, 3)
        self.assertEqual(dialogue[0], ("HOST", "Welcome."))
        self.assertEqual(dialogue[1], ("HOST", "Explain it?"))
        self.assertEqual(dialogue[2], ("EXPERT", "It works like this."))
        self.assertIn("HOST: Welcome.", script_text)

    def test_second_call_uses_cache(self):
        host = "INTRO: Welcome.\nQUESTION 1: Go?\nOUTRO: Bye."
        expert = "ANSWER 1: Yes."
        with patch.object(ma, "_scrape_article", return_value="Article"), \
             patch.object(ma, "_generate_agent_reply", side_effect=["Notes", host, expert]):
            first = ma.build_conversation("https://example.com")
            with patch.object(ma, "_generate_agent_reply") as generate:
                second = ma.build_conversation("https://example.com")
        generate.assert_not_called()
        self.assertEqual(first, second)

    def test_invalid_url_does_not_scrape(self):
        with patch.object(ma, "_scrape_article") as scrape:
            with self.assertRaises(ValueError):
                ma.build_conversation("not-a-url")
            scrape.assert_not_called()

    def test_failed_agent_output_is_not_cached(self):
        host = "INTRO: x"
        with patch.object(ma, "_scrape_article", return_value="Article"), \
             patch.object(ma, "_generate_agent_reply", side_effect=["Notes", host, RuntimeError("boom")]):
            with self.assertRaises(RuntimeError):
                ma.build_conversation("https://example.com")
        self.assertFalse(summarizer._summary_cache)


if __name__ == "__main__":
    unittest.main()