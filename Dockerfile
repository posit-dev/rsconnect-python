ARG BASE_IMAGE
FROM ${BASE_IMAGE}

WORKDIR /rsconnect
ENV WORKON_HOME=/.cache \
    PIPENV_CACHE_DIR=/.cache \
    PIPENV_DONT_LOAD_ENV=1 \
    PIPENV_SHELL=/bin/bash
COPY Pipfile Pipfile
COPY Pipfile.lock Pipfile.lock
COPY build-image build-image
RUN bash build-image && rm -vf build-image Pipfile*
