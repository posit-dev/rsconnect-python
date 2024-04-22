import json
import os

import pytest

from rsconnect.bundle import Manifest
from rsconnect.exception import RSConnectException

cur_dir = os.path.dirname(__file__)
html_manifest_json_file = os.path.join(cur_dir, "testdata", "Manifest", "html_manifest.json")


def test_Manifest_from_json():
    html_manifest_dict = {
        "version": 1,
        "metadata": {"appmode": "static", "primary_html": "index.html", "entrypoint": "index.html"},
        "files": {
            "index.html": {"checksum": "c14bd63e50295f94b761ffe9d41e3742"},
            "test1.txt": {"checksum": "3e7705498e8be60520841409ebc69bc1"},
            "test_folder1/testfoldertext1.txt": {"checksum": "0a576fd324b6985bac6aa934131d2f5c"},
        },
    }
    manifest_json_str = json.dumps(html_manifest_dict, indent=2)
    m = Manifest.from_json(manifest_json_str)
    assert m.json == manifest_json_str


def test_Manifest_from_json_file():
    m = Manifest.from_json_file(html_manifest_json_file)
    with open(html_manifest_json_file) as json_file:
        json_dict = json.load(json_file)
        assert m.json == json.dumps(json_dict, indent=2)


def test_Manifest_properties():
    html_manifest_dict = {
        "version": 1,
        "metadata": {"appmode": "static", "primary_html": "index.html", "entrypoint": "index.html"},
        "files": {
            "index.html": {"checksum": "c14bd63e50295f94b761ffe9d41e3742"},
            "test1.txt": {"checksum": "3e7705498e8be60520841409ebc69bc1"},
            "test_folder1/testfoldertext1.txt": {"checksum": "0a576fd324b6985bac6aa934131d2f5c"},
        },
    }
    manifest_json_str = json.dumps(html_manifest_dict, indent=2)
    m = Manifest.from_json(manifest_json_str)
    assert m.primary_html == html_manifest_dict["metadata"]["primary_html"]
    assert m.entrypoint == html_manifest_dict["metadata"]["entrypoint"]

    m.discard_file("test_folder1/testfoldertext1.txt")
    assert list(m.data["files"].keys()) == ["index.html", "test1.txt"]


def test_Manifest_flattened_copy():
    start = {
        "version": 1,
        "metadata": {
            "appmode": "static",
            "primary_html": "tests/testdata/html_tests/single_file_index/index.html",
            "entrypoint": "tests/testdata/html_tests/single_file_index/index.html",
        },
        "files": {
            "tests/testdata/html_tests/single_file_index/index.html": {"checksum": "c14bd63e50295f94b761ffe9d41e3742"},
            "tests/testdata/html_tests/single_file_index/test1.txt": {"checksum": "3e7705498e8be60520841409ebc69bc1"},
            "tests/testdata/html_tests/single_file_index/test_folder1/testfoldertext1.txt": {
                "checksum": "0a576fd324b6985bac6aa934131d2f5c"
            },
        },
    }
    start_json_str = json.dumps(start, indent=2)
    m = Manifest.from_json(start_json_str)
    assert m.data == start
    m.entrypoint = "tests/testdata/html_tests/single_file_index/index.html"
    m.deploy_dir = "tests/testdata/html_tests/single_file_index"
    html_manifest_dict = {
        "version": 1,
        "metadata": {"appmode": "static", "primary_html": "index.html", "entrypoint": "index.html"},
        "files": {
            "index.html": {"checksum": "c14bd63e50295f94b761ffe9d41e3742"},
            "test1.txt": {"checksum": "3e7705498e8be60520841409ebc69bc1"},
            "test_folder1/testfoldertext1.txt": {"checksum": "0a576fd324b6985bac6aa934131d2f5c"},
        },
    }
    assert m.flattened_copy.data == html_manifest_dict


def test_Manifest_empty_init():
    init = {
        "version": 1,
        "metadata": {},
        "files": {},
    }
    m = Manifest()
    m.data == init


def test_Manifest_empty_exceptions():
    m = Manifest()
    with pytest.raises(RSConnectException) as _:
        m.check_and_get_entrypoint()
