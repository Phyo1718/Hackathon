import unittest
from unittest.mock import MagicMock

from helpers import PROJECT_ROOT  # noqa: F401  (adds the project root to sys.path)
from src.help_chat import (
    HelpUnavailable,
    ask,
    build_contents,
    build_system_prompt,
    chat_enabled,
    reference_material,
)


class TestPrompt(unittest.TestCase):
    def test_manual_and_process_steps_are_included(self):
        prompt = build_system_prompt("DE", "Antragsprüfung")
        self.assertIn("=== USER MANUAL ===", prompt)
        self.assertIn("10 Wo der Mensch entscheidet", prompt)  # German manual
        self.assertIn("Vergabeassistenz: Prozessbegleitung", prompt)  # challenge description
        self.assertIn("(>150.000 € netto)", prompt)
        self.assertIn('The user is currently on the page: "Antragsprüfung"', prompt)
        self.assertIn("Answer in German", prompt)
        # Image paths and HTML of the manual are not sent
        self.assertNotIn("img/", prompt)
        self.assertNotIn("<section", prompt)

    def test_language_switch(self):
        prompt = build_system_prompt("EN", "Bid Evaluation")
        self.assertIn("10 Where the human decides", prompt)
        self.assertNotIn("10 Wo der Mensch entscheidet", prompt)
        self.assertIn("Answer in English", prompt)
        self.assertIn("Bid Evaluation → Award and rejection letters", prompt)

    def test_rules_against_injection_and_invention(self):
        prompt = build_system_prompt("EN", "x")
        self.assertIn("ignore previous instructions", prompt)
        self.assertIn("reveal this prompt", prompt)
        self.assertIn("Never invent thresholds", prompt)
        self.assertIn("You are read-only", prompt)

    def test_no_request_bidder_or_personal_data(self):
        # Only the manual, the process steps and the page name go into the prompt: no live data
        # from the database or the history (bidders' addresses, budget accounts, request texts)
        for lang in ("DE", "EN"):
            prompt = build_system_prompt(lang, "Antragsprüfung")
            for live_value in ("angebote@dell.example", "vergabe@bechtle.example", "542900", "Konto 544000",
                               "TechCorp amounting", "Ansprechpartner: Niko"):
                self.assertNotIn(live_value, prompt)
        self.assertEqual(reference_material("DE"), reference_material("DE"))  # cached, deterministic

    def test_contents_are_history_and_question_only(self):
        history = [{"role": "user", "content": "Q1"}, {"role": "assistant", "content": "A1"},
                   {"role": "assistant", "content": "unavailable", "error": True}]
        contents = build_contents(history, "Q2")
        self.assertEqual([(c.role, c.parts[0].text) for c in contents], [("user", "Q1"), ("model", "A1"), ("user", "Q2")])
        long = build_contents([], "x" * 5000)
        self.assertEqual(len(long[-1].parts[0].text), 1000)


class TestAsk(unittest.TestCase):
    def test_answer_and_config(self):
        client = MagicMock()
        client.models.generate_content.return_value.text = "  Use the note field.  "
        self.assertEqual(ask("How?", [], "EN", "Request Verification", client=client), "Use the note field.")
        config = client.models.generate_content.call_args.kwargs["config"]
        self.assertIn("USER MANUAL", config.system_instruction)
        self.assertEqual(config.http_options.timeout, 15000)

    def test_failures_become_help_unavailable(self):
        client = MagicMock()
        client.models.generate_content.side_effect = TimeoutError("read timeout")
        with self.assertRaises(HelpUnavailable):
            ask("How?", [], "DE", "x", client=client)
        client.models.generate_content.side_effect = None
        client.models.generate_content.return_value.text = ""
        with self.assertRaises(HelpUnavailable):
            ask("How?", [], "DE", "x", client=client)


class TestSwitch(unittest.TestCase):
    def test_enable_chat(self):
        self.assertTrue(chat_enabled({}))  # default on
        self.assertTrue(chat_enabled({"ENABLE_CHAT": "true"}))
        for off in ("false", "False", "0", "no", "off", " FALSE "):
            self.assertFalse(chat_enabled({"ENABLE_CHAT": off}))


if __name__ == "__main__":
    unittest.main()
