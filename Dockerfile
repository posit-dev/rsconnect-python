ARG BASE_IMAGE
FROM ${BASE_IMAGE}

WORKDIR /rsconnect
COPY scripts/build-image build-image
RUN bash build-image && rm -vf build-image
