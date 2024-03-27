ARG PY_VERSION=${PY_VERSION}
FROM python:${PY_VERSION}
COPY ./requirements.txt .
EXPOSE 9999
VOLUME ../../:/rsconnect-python/

WORKDIR /rsconnect-python/integration-testing
ARG QUARTO_VERSION

RUN apt-get update -y && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ca-certificates \
    git \
    sudo \
    vim \
    jq \
    wget

RUN mkdir -p /libs-client && \
    curl -fsSL https://github.com/casey/just/releases/download/1.1.2/just-1.1.2-x86_64-unknown-linux-musl.tar.gz \
    | tar -C /libs-client -xz just

ENV PATH=$PATH:/libs-client

RUN git clone --depth=1 https://github.com/bats-core/bats-core.git /libs/bats-core \
    && cd /libs/bats-core \
    && ./install.sh /libs/bats-core/installation \
    && git clone --depth=1 https://github.com/bats-core/bats-support.git /libs/bats-support \
    && git clone --depth=1 https://github.com/bats-core/bats-file.git /libs/bats-file \
    && git clone --depth=1 https://github.com/bats-core/bats-assert.git /libs/bats-assert

RUN curl -fsSL -o miniconda.sh https://repo.anaconda.com/miniconda/Miniconda3-py38_4.10.3-Linux-x86_64.sh \
    && chmod 755 miniconda.sh \
    && ./miniconda.sh -b -p /opt/miniconda \
    && rm -rf miniconda.sh

RUN pip install rsconnect-jupyter --pre && \
    pip install pipenv && \
    jupyter-nbextension install --sys-prefix --py rsconnect_jupyter

RUN curl -fsSLO https://github.com/quarto-dev/quarto-cli/releases/download/v${QUARTO_VERSION}/quarto-${QUARTO_VERSION}-linux-amd64.tar.gz && \
    mkdir /opt/quarto && tar xf quarto-${QUARTO_VERSION}-linux-amd64.tar.gz -C /opt/quarto --strip-components 1 && \
    ( echo ""; echo 'export PATH=$PATH:/opt/quarto/bin' ; echo "" ) >> ~/.profile && \
    . ~/.profile