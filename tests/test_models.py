from unittest import TestCase

from rsconnect.models import AppMode, AppModes, GlobMatcher


class TestModels(TestCase):
    def test_app_mode_class(self):
        mode = AppMode(1, "test", "Testing")

        self.assertEqual(mode.ordinal(), 1)
        self.assertEqual(mode.name(), "test")
        self.assertEqual(mode.desc(), "Testing")
        self.assertIsNone(mode.extension())
        self.assertEqual(mode.name(), str(mode))
        self.assertEqual(mode.desc(), repr(mode))

        mode = AppMode(2, "test-2", "Testing (again)", ".ipynb")

        self.assertEqual(mode.ordinal(), 2)
        self.assertEqual(mode.name(), "test-2")
        self.assertEqual(mode.desc(), "Testing (again)")
        self.assertEqual(mode.extension(), ".ipynb")

    def test_app_modes_constants(self):
        defined = list(filter(lambda n: n.isupper(), AppModes.__dict__.keys()))
        modes = list(AppModes._modes)
        ordinals = []
        names = []
        descriptions = []
        extensions = []

        self.assertEqual(len(defined), 12)
        self.assertEqual(len(modes), 12)

        # This makes sure all named mode constants appear in the modes list.
        for name in defined:
            named_mode = AppModes.__dict__.get(name)
            self.assertIn(named_mode, modes)

        # The stuff here makes sure that each mode defined in the modes list is unique.
        for mode in modes:
            self.assertNotIn(mode.ordinal(), ordinals)
            ordinals.append(mode.ordinal())
            self.assertNotIn(mode.name(), names)
            ordinals.append(mode.name())
            self.assertNotIn(mode.desc(), descriptions)
            ordinals.append(mode.desc())

            if mode.extension() is not None:
                self.assertNotIn(mode.extension(), extensions)
                ordinals.append(mode.extension())

    def test_get_by_ordinal(self):
        self.assertIs(AppModes.get_by_ordinal(1), AppModes.SHINY)
        self.assertIs(AppModes.get_by_ordinal(-1, True), AppModes.UNKNOWN)
        self.assertIs(AppModes.get_by_ordinal(None, True), AppModes.UNKNOWN)

        with self.assertRaises(ValueError):
            AppModes.get_by_ordinal(-1)

        with self.assertRaises(ValueError):
            AppModes.get_by_ordinal(None)

    def test_get_by_name(self):
        self.assertIs(AppModes.get_by_name("shiny"), AppModes.SHINY)
        self.assertIs(AppModes.get_by_name("bad-name", True), AppModes.UNKNOWN)
        self.assertIs(AppModes.get_by_name(None, True), AppModes.UNKNOWN)

        with self.assertRaises(ValueError):
            AppModes.get_by_name("bad-name")

        with self.assertRaises(ValueError):
            AppModes.get_by_name(None)

    def test_get_by_extension(self):
        self.assertIs(AppModes.get_by_extension(".R"), AppModes.SHINY)
        self.assertIs(AppModes.get_by_extension(".bad-ext", True), AppModes.UNKNOWN)
        self.assertIs(AppModes.get_by_extension(None, True), AppModes.UNKNOWN)

        with self.assertRaises(ValueError):
            AppModes.get_by_extension(".bad-ext")

        with self.assertRaises(ValueError):
            AppModes.get_by_extension(None)

    def test_glob_matcher(self):
        cases = [
            ("dir", "dir", True),
            ("dir", "file", False),
            ("dir", "dir/file", False),
            ("dir/*.txt", "file", False),
            ("dir/*.txt", "dir/file", False),
            ("dir/*.txt", "dir/file.txt", True),
            ("dir/*.txt", "dir/.txt", True),
            ("dir/**/*.txt", "dir/a.txt", True),
            ("dir/**/*.txt", "dir/sub/a.txt", True),
            ("dir/**/*.txt", "dir/sub/sub/a.txt", True),
            ("dir/**/*.txt", "dir/sub/sub/a.obj", False),
            ("dir/**/*", "dir/sub/sub/sub/a.txt", True),
            ("dir/**/*", "dir/sub/sub/a.bob", True),
            ("dir/**/*", "dir/sub/z.o", True),
            ("dir/**/*", "dir/abc", True),
        ]

        for case in cases:
            matcher = GlobMatcher(case[0])
            msg = "Pattern: %s, Path: %s, expected: %s, got: %s" % (
                case[0],
                case[1],
                case[2],
                not case[2],
            )
            self.assertEqual(matcher.matches(case[1]), case[2], msg)

        with self.assertRaises(ValueError):
            GlobMatcher("./blah/**/blah/**/*.txt")
