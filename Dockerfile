ARG BASE_IMAGE
FROM ${BASE_IMAGE}

RUN python -m pip install --upgrade pip
RUN python -m pip install \
	# base requirements
	six click  \
	# extended requirements to render notebooks to static HTML
	nbconvert jupyter_client ipykernel \
	# dev dependencies
	pyflakes pytest pytest-cov
