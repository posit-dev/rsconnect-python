from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest import TestCase, mock

from rsconnect.certificates import read_certificate_file
from rsconnect.exception import RSConnectException


class ParseCertificateFileTestCase(TestCase):
    def test_parse_certificate_file_ca_bundle(self):
        res = read_certificate_file("tests/testdata/certificates/localhost.ca-bundle")
        self.assertTrue(res)

    def test_parse_certificate_file_cer(self):
        res = read_certificate_file("tests/testdata/certificates/localhost.cer")
        self.assertTrue(res)

    def test_parse_certificate_file_crt(self):
        res = read_certificate_file("tests/testdata/certificates/localhost.crt")
        self.assertTrue(res)

    def test_parse_certificate_file_der(self):
        res = read_certificate_file("tests/testdata/certificates/localhost.der")
        self.assertTrue(res)

    def test_parse_certificate_file_key(self):
        res = read_certificate_file("tests/testdata/certificates/localhost.key")
        self.assertTrue(res)

    def test_parse_certificate_file_pem(self):
        res = read_certificate_file("tests/testdata/certificates/localhost.pem")
        self.assertTrue(res)

    def test_parse_certificate_file_csr(self):
        with self.assertRaises(RSConnectException) as context:
            read_certificate_file("tests/testdata/certificates/localhost.csr")
        self.assertIn("not recognized", str(context.exception))

    def test_parse_certificate_file_invalid(self):
        with NamedTemporaryFile() as tmpfile:
            with self.assertRaises(RSConnectException) as context:
                read_certificate_file(tmpfile.name)
        self.assertIn("not recognized", str(context.exception))

    def test_parse_certificate_file_missing(self):
        # A path that does not exist reports unreadability, not its suffix:
        # the file type of a missing file is beside the point.
        with self.assertRaises(RSConnectException) as context:
            read_certificate_file("/nonexistent/ca")
        self.assertIn("could not be read", str(context.exception))

    def test_parse_certificate_file_unreadable_metadata(self):
        # is_file() itself raises OSError when the path's metadata cannot be
        # read, e.g. through a permission-denied directory; that too must
        # report as an operational error.
        with mock.patch.object(Path, "is_file", side_effect=PermissionError(13, "Permission denied")):
            with self.assertRaises(RSConnectException) as context:
                read_certificate_file("tests/testdata/certificates/localhost.pem")
        self.assertIn("could not be read", str(context.exception))
        self.assertIn("Permission denied", str(context.exception))
