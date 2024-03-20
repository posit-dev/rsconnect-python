from textwrap import dedent
from rsconnect.utils_package import (
    _remove_leading_zeros,  # pyright: ignore[reportPrivateUsage]
    compare_package_versions,
    compare_semvers,
    parse_requirements_txt,
    replace_requirement,
)


def test_remove_leading_zeros():
    assert _remove_leading_zeros("2024.01.02") == "2024.1.2"
    assert _remove_leading_zeros("2024.001.020") == "2024.1.20"

    # Shouldn't remove leading zero from prerelease ("dev") or build ("020-abcd")
    # strings.
    assert _remove_leading_zeros("2020.01.0-dev+020-abcd") == "2020.1.0-dev+020-abcd"


def test_compare_semvers():
    # Different combinations of leading zeros
    assert compare_semvers("2023.01.0", "2023.02.0") == -1
    assert compare_semvers("2023.1.0", "2023.02.0") == -1
    assert compare_semvers("2023.01.0", "2023.2.0") == -1

    assert compare_semvers("2023.01.0", "2023.01.0") == 0
    assert compare_semvers("2023.1.0", "2023.01.00") == 0
    assert compare_semvers("2023.01.0", "2023.1.0") == 0

    assert compare_semvers("2023.01.3", "2023.1.3") == 0
    assert compare_semvers("2023.01.03", "2023.1.03") == 0
    assert compare_semvers("2023.01.3", "2023.01.3") == 0

    assert compare_semvers("2023.02.0", "2023.01.0") == 1
    assert compare_semvers("2023.2.0", "2023.01.0") == 1
    assert compare_semvers("2023.02.0", "2023.1.0") == 1

    assert compare_semvers("2023.01.0", "2023.1.01") == -1
    assert compare_semvers("2024.01.0", "2023.2.03") == 1


def test_compare_package_versions():
    assert compare_package_versions("3.01.0", "3.02") == -1
    assert compare_package_versions("3.1.0", "3.02.0") == -1
    assert compare_package_versions("0.01.0", "0.2.0") == -1
    assert compare_package_versions("0.01.5", "0.2.0") == -1

    assert compare_package_versions("3.01.0", "3.1") == 0
    assert compare_package_versions("3.1.0", "3.01.0") == 0
    assert compare_package_versions("0.01.0", "0.1.0") == 0
    assert compare_package_versions("0.01", "0.1.0") == 0
    assert compare_package_versions("0.01.0.0", "0.1") == 0

    assert compare_package_versions("3.02", "3.01.0") == 1
    assert compare_package_versions("3.02.0", "3.1.0") == 1
    assert compare_package_versions("0.2.0", "0.01.0") == 1
    assert compare_package_versions("0.2.0", "0.01.5") == 1


def test_parse_requirements():
    res = parse_requirements_txt(
        dedent(
            """
        pkga==1.0
        pkgb>=2.0  # Comment
        pkgc>1.0,<=3.0
        pkgd >1.0, <=3.0
        pkge >1.0,<=3.0 ; python_version<'3.8'
        pkgf; python_version<'3.8'
        pkgg

        # Comment line
          # Another comment line
        pkg-h1 # Comment
        """
        )
    )
    assert res == [
        ("pkga", [("==", "1.0")]),
        ("pkgb", [(">=", "2.0")]),
        ("pkgc", [(">", "1.0"), ("<=", "3.0")]),
        ("pkgd", [(">", "1.0"), ("<=", "3.0")]),
        ("pkge", [(">", "1.0"), ("<=", "3.0")]),
        ("pkgf", []),
        ("pkgg", []),
        ("pkg-h1", []),
    ]

    # Malformed version specs should be ignored
    res = parse_requirements_txt(
        dedent(
            """
        pkga==1.0
        pkgb!!2.0
        pkgc>2.0,[=3.0
        """
        )
    )
    assert res == [
        ("pkga", [("==", "1.0")]),
        ("pkgb", []),
        ("pkgc", [(">", "2.0")]),
    ]


def test_replace_requirement():
    x = replace_requirement(
        "starlette",
        "REPLACED",
        dedent(
            """
            abcd
            starlette
            starlette==1.0
            starlette-foo
            starlette0
            starlette
            """
        ),
    )
    assert x == dedent(
        """
        abcd
        REPLACED
        REPLACED
        starlette-foo
        starlette0
        REPLACED
        """
    )
