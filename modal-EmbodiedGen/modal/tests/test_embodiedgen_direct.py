import importlib.util
import unittest
from pathlib import Path
from unittest import mock

MODULE = Path(__file__).parents[1] / "runtime" / "embodiedgen_direct.py"
spec = importlib.util.spec_from_file_location("embodiedgen_direct_test", MODULE)
direct = importlib.util.module_from_spec(spec)
spec.loader.exec_module(direct)


class RunStageTest(unittest.TestCase):
    def test_success_records_running_state_and_timing(self):
        updates = []
        timings = {}

        def capture(job_id, **changes):
            updates.append((job_id, changes))
            return changes

        with mock.patch.object(direct, "_put_job", side_effect=capture):
            result = direct._run_stage("job-1", "segment", lambda: "ok", timings)

        self.assertEqual(result, "ok")
        self.assertEqual(updates[0], ("job-1", {"status": "running", "stage": "segment"}))
        self.assertIn("segment", timings)
        self.assertGreaterEqual(timings["segment"], 0)

    def test_failure_persists_error_and_reraises(self):
        updates = []
        timings = {}

        def capture(job_id, **changes):
            updates.append((job_id, changes))
            return changes

        def fail():
            raise RuntimeError("boom")

        with mock.patch.object(direct, "_put_job", side_effect=capture):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                direct._run_stage("job-2", "finalize", fail, timings)

        failed = updates[-1][1]
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["stage"], "finalize")
        self.assertEqual(failed["error_type"], "RuntimeError")
        self.assertEqual(failed["error"], "boom")
        self.assertEqual(failed["stage_seconds"], timings)


if __name__ == "__main__":
    unittest.main()
