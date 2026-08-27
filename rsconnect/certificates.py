from __future__ import annotations

from pathlib import Path

from .exception import RSConnectException

BINARY_ENCODED_FILETYPES = [".cer", ".der"]
TEXT_ENCODED_FILETYPES = [".ca-bundle", ".crt", ".key", ".pem"]


def read_certificate_file(location: str) -> str | bytes:
    """Reads a certificate file from disk.

    The file type (suffix) is used to determine the file encoding.
    Assumption are made based on standard SSL practices.

    Files ending in '.cer' and '.der' are assumed DER (Distinguished
    Encoding Rules) files encoded in binary format.

    Files ending in '.ca-bundle', '.crt', '.key', and '.pem' are PEM
    (Privacy Enhanced Mail) files encoded in plain-text format.
    """

    path = Path(location)

    # is_file() is inside the try because it raises OSError itself when the path's
    # metadata cannot be read, e.g. through a permission-denied directory.
    try:
        if not path.is_file():
            raise RSConnectException("The certificate file %s could not be read: no such file." % location)

        suffix = path.suffix
        if suffix in BINARY_ENCODED_FILETYPES:
            with open(path, "rb") as bFile:
                return bFile.read()

        if suffix in TEXT_ENCODED_FILETYPES:
            with open(path, "r") as tFile:
                return tFile.read()
    except OSError as exc:
        raise RSConnectException("The certificate file %s could not be read: %s" % (location, exc)) from exc

    types = BINARY_ENCODED_FILETYPES + TEXT_ENCODED_FILETYPES
    types = sorted(types)
    types = [f"'{_}'" for _ in types]
    human_readable_string = ", ".join(types[:-1]) + ", or " + types[-1]
    raise RSConnectException(
        f"The certificate file type is not recognized. Expected {human_readable_string}. Found '{suffix}'."
    )
