import tempfile
import unittest
from pathlib import Path

from codex_generator import CodexGenerationError, format_codex_event, save_challenge, validate_spec
from ctf_generator import generate


class GeneratorTests(unittest.TestCase):
    def test_automatic_folder_name_uses_short_timestamp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = generate("web", "easy", Path(temp_dir))
            self.assertRegex(target.name, r"^web-easy-\d{12}$")

    def test_all_combinations_generate_expected_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for category in ("web", "pwn", "crypto"):
                for difficulty in ("easy", "medium", "hard"):
                    target = generate(category, difficulty, root, f"{category}-{difficulty}")
                    self.assertTrue((target / "README.md").is_file())
                    self.assertTrue((target / "public" / "README.md").is_file())
                    self.assertTrue((target / "private" / "flag.txt").is_file())
                    self.assertTrue((target / "private" / "solution.md").is_file())
                    self.assertTrue((target / "metadata.json").is_file())

    def test_existing_folder_is_not_overwritten_without_force(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            generate("crypto", "easy", root, "same-name")
            with self.assertRaises(FileExistsError):
                generate("crypto", "easy", root, "same-name")

    def test_codex_spec_is_validated_and_saved(self):
        spec = {
            "title": "Clockwork Cipher",
            "description": "Recover the hidden message.",
            "flag": "ASC{test_flag}",
            "solution": "Reverse the test transform.",
            "run_instructions": "Open public/challenge.txt.",
            "concepts": ["Known plaintext"],
            "files": [{"area": "public", "path": "challenge.txt", "content": "sample"}],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            target = save_challenge(
                spec, "crypto", "medium", Path(temp_dir), "abc123", "daybreak_blue", name="codex-test"
            )
            self.assertEqual((target / "private" / "flag.txt").read_text(encoding="utf-8").strip(), "ASC{test_flag}")
            self.assertEqual((target / "public" / "challenge.txt").read_text(encoding="utf-8"), "sample")

    def test_codex_spec_rejects_parent_path(self):
        spec = {
            "title": "Unsafe",
            "description": "Unsafe path test",
            "flag": "ASC{test}",
            "solution": "None",
            "run_instructions": "None",
            "concepts": [],
            "files": [{"area": "public", "path": "../escape.txt", "content": "bad"}],
        }
        with self.assertRaises(CodexGenerationError):
            validate_spec(spec)

    def test_codex_events_have_korean_progress_messages(self):
        self.assertEqual(format_codex_event({"type": "thread.started"}), "코덱스 작업을 시작했습니다.")
        self.assertIn(
            "난이도",
            format_codex_event({"type": "item.started", "item": {"type": "reasoning"}}),
        )


if __name__ == "__main__":
    unittest.main()
