"""Unit tests for the origin's fail-closed response boundary."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
SERVER_PATH = HERE.parent / "src" / "server.py"
spec = importlib.util.spec_from_file_location("workchain_x402_origin", SERVER_PATH)
origin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(origin)


class OriginContractTests(unittest.TestCase):
    def test_verified_context_requires_completed_verified_steps(self):
        context = {
            "status": "completed",
            "steps": {
                "normalization": {
                    "status": "completed",
                    "verification": {"verified": True, "failures": []},
                }
            },
        }
        self.assertEqual(origin.verification_summary(context), (True, []))

    def test_missing_verification_fails_closed(self):
        context = {"status": "completed", "steps": {"normalization": {"status": "completed"}}}
        verified, failures = origin.verification_summary(context)
        self.assertFalse(verified)
        self.assertEqual(failures[0]["reason"], "step_not_verified")

    def test_artifact_list_comes_only_from_registered_outputs(self):
        with tempfile.TemporaryDirectory(prefix="workchain-origin-test-") as tmp:
            root = Path(tmp)
            output = root / "output"
            output.mkdir()
            registered = output / "tone_normalized.wav"
            registered.write_bytes(b"audio")
            unregistered = output / "secret.txt"
            unregistered.write_text("not exposed")
            context = {
                "steps": {
                    "normalization": {
                        "outputs": {"primary_output": {"path": str(registered), "type": "file"}}
                    }
                }
            }
            records = origin.artifact_records("00000000-0000-0000-0000-000000000000", output, context)
            self.assertEqual([record["path"] for record in records], ["tone_normalized.wav"])
            self.assertNotIn("secret.txt", json.dumps(records))


if __name__ == "__main__":
    unittest.main()
