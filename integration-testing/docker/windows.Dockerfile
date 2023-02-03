FROM winamd64/python:3
WORKDIR /usr/src/app

RUN pip install -r requirements.txt

RUN cd rsconnect-python && \
	pip install pipenv && \
	make deps dist && \
	pip install ./dist/rsconnect_python-*.whl
