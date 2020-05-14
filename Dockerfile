ARG BASE_IMAGE
FROM ${BASE_IMAGE}

WORKDIR /rsconnect
ENV WORKON_HOME=/.cache \
    PIPENV_DONT_LOAD_ENV=1 \
    PIPENV_SHELL=/bin/bash
COPY Pipfile Pipfile
COPY Pipfile.lock Pipfile.lock
RUN python -m pip install --upgrade pip pipenv && \
    pipenv install --dev
