ARG BASE_IMAGE
FROM ${BASE_IMAGE}

RUN python -m pip install six click nbformat
