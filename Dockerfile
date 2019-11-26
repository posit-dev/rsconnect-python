ARG BASE_IMAGE
FROM ${BASE_IMAGE}

# base requirements
RUN python -m pip install six click pyflakes

# extended requirements to enable static notebook deployments
RUN python -m pip install nbconvert jupyter_client ipykernel
