#!/usr/bin/env python
import os

from setuptools import find_packages, setup

# Allow overriding the package name via $PACKAGE_NAME
PACKAGE_NAME = os.environ.get("PACKAGE_NAME", "rsconnect_python")

# Pull in your README as the long description
with open("README.md", encoding="utf-8") as f:
    long_description = f.read()

setup(
    # -- identity --
    name=PACKAGE_NAME,
    use_scm_version={"write_to": "rsconnect/version.py"},
    setup_requires=["setuptools_scm[toml]>=3.4"],

    # -- metadata --
    description="Python integration with Posit Connect",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Michael Marchetti",
    author_email="mike@posit.co",
    license_file="LICENSE.md",
    url="http://github.com/posit-dev/rsconnect-python",
    project_urls={
        "Repository": "http://github.com/posit-dev/rsconnect-python",
        "Documentation": "https://docs.posit.co/rsconnect-python",
    },
    python_requires=">=3.8",

    # -- packages & typing stub --
    packages=find_packages(include=["rsconnect", "rsconnect.*"]),
    include_package_data=True,
    package_data={"rsconnect": ["py.typed"]},

    # -- runtime dependencies --
    install_requires=[
        "typing-extensions>=4.8.0",
        "pip>=10.0.0",
        "semver>=2.0.0,<4.0.0",
        "pyjwt>=2.4.0",
        "click>=8.0.0",
        "toml>=0.10; python_version < '3.11'",
    ],

    # -- extras --
    extras_require={
        "test": [
            "black==24.3.0",
            "coverage",
            "flake8-pyproject",
            "flake8",
            "httpretty",
            "ipykernel",
            "nbconvert",
            "pyright",
            "pytest-cov",
            "pytest",
            "setuptools>=61",
            "setuptools_scm[toml]>=3.4",
            "twine",
            "types-Flask",
        ],
        "snowflake": ["snowflake-cli"],
    },

    # -- console script entrypoint --
    entry_points={
        "console_scripts": [
            "rsconnect=rsconnect.main:cli",
        ],
    },

    # -- wheel config --
    options={
        "bdist_wheel": {"universal": True},
    },

    # -- classifiers (optional but recommended) --
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],

    zip_safe=False,
)
