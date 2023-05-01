from tempfile import NamedTemporaryFile
from unittest import TestCase

from rsconnect.certificates import read_certificate_file


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
        with self.assertRaises(RuntimeError):
            read_certificate_file("tests/testdata/certificates/localhost.csr")

    def test_parse_certificate_file_invalid(self):
        with NamedTemporaryFile() as tmpfile:
            with self.assertRaises(RuntimeError):
                read_certificate_file(tmpfile.name)
