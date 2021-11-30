from unittest import TestCase

from rsconnect.api import RSConnectException, RSConnect


class TestAPI(TestCase):
    def test_output_task_log(self):
        lines = ["line 1", "line 2", "line 3"]
        task_status = {
            "status": lines,
            "last_status": "last",
            "finished": True,
            "code": 0,
        }
        output = []

        self.assertEqual(RSConnect.output_task_log(task_status, "0", output.append), "last")
        self.assertEqual(lines, output)

        # failed tasks should emit a log message indicating it failed
        task_status["code"] = 12
        with self.assertRaises(RSConnectException):
            RSConnect.output_task_log(task_status, "last", output.append)

        self.assertEqual(len(output), 4)
        self.assertEqual(output[3], "Task failed. Task exited with status 12.")
