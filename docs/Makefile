# Our make file for the docs.
MKDOCS_IMAGE?="rstudio/rsconnect:mkdocs"

## Specify that Docker runs with the calling user's uid/gid to avoid file
## permission issues on Linux dev hosts.
DOCKER_RUN_AS=
ifeq (Linux,$(shell uname))
	DOCKER_RUN_AS=-u $(shell id -u):$(shell id -g)
endif

BUILD_RUNNER=docker run --rm --name mkdocs \
	${DOCKER_RUN_AS} \
	-v $(CURDIR):/mkdocs \
	-w /mkdocs \
	${MKDOCS_IMAGE}

# Do everything,
all: clean image build

# Destroy the site, if it exists.
clean:
	@rm -rf docs/site

# Build the image in which mkdocs will run.
image:
	docker build -t ${MKDOCS_IMAGE} .

# Build the actual documentation.
build:
	python patch_admonitions.py
	${BUILD_RUNNER} mkdocs build
	@rm docs/index.md

.PHONY: clean image build
