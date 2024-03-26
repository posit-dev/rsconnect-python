ARG PY_VERSION=${PY_VERSION}
FROM python:${PY_VERSION}
COPY ./requirements.txt .
EXPOSE 9999
VOLUME ../../:/rsconnect-python/

WORKDIR /rsconnect-python/integration-testing
ARG QUARTO_VERSION

RUN apt-get update && \
      apt-get -y install sudo

RUN mkdir -p /libs-client && \
    curl -fsSL https://github.com/casey/just/releases/download/1.1.2/just-1.1.2-x86_64-unknown-linux-musl.tar.gz \
    | tar -C /libs-client -xz just

ENV PATH=$PATH:/libs-client

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

CMD cd ../ && \
    rm -rf ~/.jupyter/ && \
    pip install . && \
    jupyter-nbextension enable --sys-prefix --py rsconnect_jupyter && \
    jupyter-serverextension enable --sys-prefix --py rsconnect_jupyter && \
    jupyter-notebook \
        -y --ip='0.0.0.0' --port=9999 --no-browser --NotebookApp.token='' --allow-root
