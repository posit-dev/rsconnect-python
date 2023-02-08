FROM python:3.9
COPY ./requirements.txt .
EXPOSE 9999
VOLUME ../../:/rsconnect-python 
WORKDIR /rsconnect-python/integration-testing

RUN apt-get update && \
      apt-get -y install sudo

RUN mkdir -p /libs-client && \
    curl -fsSL https://github.com/casey/just/releases/download/1.1.2/just-1.1.2-x86_64-unknown-linux-musl.tar.gz \
    | tar -C /libs-client -xz just

ENV PATH=$PATH:/libs-client

RUN python -m venv ./client-python/ && \
    . ./client-python/bin/activate && \
    pip install rsconnect-jupyter && \
    pip install pipenv && \
    jupyter-nbextension install --sys-prefix --py rsconnect_jupyter

ENTRYPOINT . ./client-python/bin/activate ; \
    cd ../ ; \
    make deps dist ; \
    pip install ./dist/rsconnect_python-*.whl ; \
    jupyter-nbextension enable --sys-prefix --py rsconnect_jupyter ; \
    jupyter-serverextension enable --sys-prefix --py rsconnect_jupyter ; \
    jupyter-notebook \
        -y --ip='0.0.0.0' --port=9999 --no-browser --NotebookApp.token='' --allow-root ; \
    tail -f /dev/null