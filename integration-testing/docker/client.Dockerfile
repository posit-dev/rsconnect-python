FROM python:3.9
COPY ./requirements.txt .
EXPOSE 9999


RUN ls -la

# RUN cd /rsconnect-python && \
# 	pip install pipenv && \
# 	make deps dist && \
# 	pip install ./dist/rsconnect_python-*.whl
