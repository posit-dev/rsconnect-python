FROM rstudio/rstudio-connect:jammy
ARG QUARTO_VERSION
ENV QUARTO_VERSION=${QUARTO_VERSION}
RUN echo "QUARTO_VERSION is ${QUARTO_VERSION}"
RUN curl -fsSLO https://github.com/quarto-dev/quarto-cli/releases/download/v${QUARTO_VERSION}/quarto-${QUARTO_VERSION}-linux-amd64.tar.gz && \
    mkdir /opt/quarto && tar xf quarto-${QUARTO_VERSION}-linux-amd64.tar.gz -C /opt/quarto --strip-components 1 && \
    ( echo ""; echo 'export PATH=$PATH:/opt/quarto/bin' ; echo "" ) >> ~/.profile && \
    source ~/.profile
