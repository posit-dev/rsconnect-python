from unittest import TestCase

from rsconnect.api import RSConnectException, RSConnect


class TestAPI(TestCase):
    def test_output_task_log(self):
        lines = ["line 1", "line 2", "line 3"]
        task_status = {
            "status": lines,
            "last_status": "last",
            "finished": True,
            "code": 12,
        }
        output = []

        with self.assertRaises(RSConnectException):
            RSConnect.output_task_log(task_status, "last", output.append)

        task_status["code"] = 0

        self.assertEqual(len(output), 0)
        self.assertEqual(RSConnect.output_task_log(task_status, "0", output.append), "last")
        self.assertEqual(lines, output)
