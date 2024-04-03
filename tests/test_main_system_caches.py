import json
import unittest
from os import system

from click.testing import CliRunner

from rsconnect.main import cli


CONNECT_SERVER = "http://localhost:3939"
CONNECT_KEYS_JSON = "vetiver-testing/rsconnect_api_keys.json"

ADD_CACHE_COMMAND = "docker compose exec -u rstudio-connect -T rsconnect mkdir -p /data/python-environments/pip/1.2.3"
RM_CACHE_COMMAND = "docker compose exec -u rstudio-connect -T rsconnect rm -Rf /data/python-environments/pip/1.2.3"
# The following returns int(0) if dir exists, else int(256).
CACHE_EXISTS_COMMAND = "docker compose exec -u rstudio-connect -T rsconnect [ -d /data/python-environments/pip/1.2.3 ]"
SERVICE_RUNNING_COMMAND = "docker compose ps --services --filter 'status=running' | grep rsconnect"


def rsconnect_service_running():
    exit_code = system(SERVICE_RUNNING_COMMAND)
    if exit_code == 0:
        return True
    else:
        return False


def cache_dir_exists():
    exit_code = system(CACHE_EXISTS_COMMAND)
    if exit_code == 0:
        return True
    else:
        return False


def get_key(name):
    with open(CONNECT_KEYS_JSON) as f:
        api_key = json.load(f)[name]
        return api_key


def apply_common_args(args: list, server=None, key=None, insecure=True):
    if server:
        args.extend(["-s", server])
    if key:
        args.extend(["-k", key])
    if insecure:
        args.extend(["--insecure"])


class TestSystemCachesList(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        system(ADD_CACHE_COMMAND)
        if not rsconnect_service_running():
            raise unittest.SkipTest("rsconnect docker service is not available")
        return super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        system(RM_CACHE_COMMAND)
        return super().tearDownClass

    # Admins can list caches
    def test_system_caches_list_admin(self):
        api_key = get_key("admin")
        runner = CliRunner()

        args = ["system", "caches", "list"]
        apply_common_args(args, server=CONNECT_SERVER, key=api_key)

        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0)

        expected = {"caches": [{"language": "Python", "version": "1.2.3", "image_name": "Local"}]}
        result_dict = json.loads(result.output)
        self.assertDictEqual(result_dict, expected)

    # Publishers cannot list caches
    def test_system_caches_list_publisher(self):
        api_key = get_key("susan")
        runner = CliRunner()

        args = ["system", "caches", "list"]
        apply_common_args(args, server=CONNECT_SERVER, key=api_key)

        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 1)

        self.assertRegex(result.output, "You don't have permission to perform this operation.")


class TestSystemCachesDelete(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        system(ADD_CACHE_COMMAND)
        if not rsconnect_service_running():
            raise unittest.SkipTest("rsconnect docker service is not available")
        return super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        system(RM_CACHE_COMMAND)
        return super().tearDownClass

    # Publishers cannot delete caches
    def test_system_caches_delete_publisher(self):
        api_key = get_key("susan")
        runner = CliRunner()

        args = ["system", "caches", "delete", "--language", "Python", "--version", "1.2.3", "--image-name", "Local"]
        apply_common_args(args, server=CONNECT_SERVER, key=api_key)

        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 1)

        self.assertRegex(result.output, "You don't have permission to perform this operation.")

    # Admins can delete caches that exist
    def test_system_caches_delete_admin(self):
        api_key = get_key("admin")
        runner = CliRunner()

        args = ["system", "caches", "delete", "--language", "Python", "--version", "1.2.3", "--image-name", "Local"]
        apply_common_args(args, server=CONNECT_SERVER, key=api_key)

        self.assertTrue(cache_dir_exists())
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0)
        self.assertFalse(cache_dir_exists())

        # TODO: Unsure how to test log messages received from Connect.

    # Admins cannot delete caches that do not exist
    def test_system_caches_delete_admin_nonexistent(self):
        api_key = get_key("admin")
        runner = CliRunner()

        args = ["system", "caches", "delete", "--language", "Python", "--version", "0.1.2", "--image-name", "Local"]
        apply_common_args(args, server=CONNECT_SERVER, key=api_key)

        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 1)

        self.assertRegex(result.output, "Cache does not exist")
