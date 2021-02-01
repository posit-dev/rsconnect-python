ARG BASE_IMAGE
FROM ${BASE_IMAGE}

WORKDIR /rsconnect
COPY scripts/build-image build-image
COPY requirements.txt requirements.txt
RUN bash build-image && rm -vf build-image
