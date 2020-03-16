FROM python:3.8.2-alpine3.11
MAINTAINER RStudio Connect <rsconnect@rstudio.com>

# Needed with Python3 mkdocs.
# https://click.palletsprojects.com/en/7.x/python3/
ENV LC_ALL C.UTF-8
ENV LANG C.UTF-8

RUN pip3 install \
        mkdocs==1.0.4 \
        mkdocs-material==4.5.1 \
        mkdocs-macros-plugin==0.2.4 \
        mkdocs-exclude==1.0.2 \
        markdown==3.1.1 \
        markdown-include==0.5.1 \
        pymdown-extensions==6.2 \
        Pygments==2.5.2
