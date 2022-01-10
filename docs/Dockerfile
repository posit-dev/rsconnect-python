FROM python:3.8-slim
MAINTAINER RStudio Connect <rsconnect@rstudio.com>

# Needed with Python3 mkdocs.
# https://click.palletsprojects.com/en/7.x/python3/
ENV LC_ALL C.UTF-8
ENV LANG C.UTF-8

COPY requirements.txt requirements.txt
RUN pip3 install -r requirements.txt && \
    rm -f requirements.txt
