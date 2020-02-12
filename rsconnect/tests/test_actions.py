from unittest import TestCase

from rsconnect.actions import default_title


class TestActions(TestCase):
    def test_default_title(self):
        self.assertEqual(default_title('testing.txt'), 'testing')
        self.assertEqual(default_title('this.is.a.test.ext'), 'this.is.a.test')
        self.assertEqual(default_title('1.ext'), '001')
        self.assertEqual(default_title('%s.ext' % ('n' * 2048)), 'n' * 1024)
