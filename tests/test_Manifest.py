import json
import os

from rsconnect.bundle import Manifest

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
