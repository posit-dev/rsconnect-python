from setuptools import setup

# Dependencies here so Snyk can see them
# https://github.com/snyk/snyk-python-plugin/issues/147
setup(
    install_requires=[
        "six>=1.14.0",
        "click>=7.0.0",
        "pip>=10.0.0",
        "semver>=2.0.0,<3.0.0",
        "pyjwt>=2.4.0",
    ],
    setup_requires=[
        "setuptools>=61",
        "setuptools_scm>=3.4",
        "toml",
        "wheel",
    ],
)
