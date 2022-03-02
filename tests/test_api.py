from unittest import TestCase

from rsconnect.api import RSConnectException, RSConnect


class TestAPI(TestCase):
    def test_output_task_log(self):
        lines = ["line 1", "line 2", "line 3"]
        task_status = {
            "status": lines,
            "last_status": 3,
            "finished": True,
            "code": 0,
        }
        output = []

        self.assertEqual(RSConnect.output_task_log(task_status, 0, output.append), 3)
        self.assertEqual(lines, output)

        task_status["last_status"] = 4
        task_status["status"] = ["line 4"]
        self.assertEqual(RSConnect.output_task_log(task_status, 3, output.append), 4)

        self.assertEqual(len(output), 4)
        self.assertEqual(output[3], "line 4")
