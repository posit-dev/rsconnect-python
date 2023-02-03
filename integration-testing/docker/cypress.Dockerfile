FROM cypress/included:9.7.0

RUN apt-get update -y && apt-get install -y --no-install-recommends \
    jq

RUN mkdir -p /libs-cypress && \
    curl -fsSL https://github.com/casey/just/releases/download/1.1.2/just-1.1.2-x86_64-unknown-linux-musl.tar.gz \
    | tar -C /libs-cypress -xz just

ENV PATH=$PATH:/libs-cypress
CMD tail -f /dev/null