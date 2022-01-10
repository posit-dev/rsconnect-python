MKDOCS_IMAGE ?= rstudio/rsconnect:mkdocs
VERSION ?= NOTSET

DOCKER_RUN_AS =
ifeq (Linux,$(shell uname))
	DOCKER_RUN_AS = -u $(shell id -u):$(shell id -g)
endif

BUILD_RUNNER = \
	docker run --rm --name mkdocs \
		$(DOCKER_RUN_AS) \
		-e PYTHONPATH=/rsconnect_python \
		-e VERSION=$(VERSION) \
		-v $(CURDIR)/../:/rsconnect_python \
		-w /rsconnect_python/docs \
		$(MKDOCS_IMAGE)

.PHONY: all
all: clean image build

.PHONY: clean
clean:
	rm -rf docs/site

.PHONY: image
image:
	docker build -t $(MKDOCS_IMAGE) .

.PHONY: build
build: docs/index.md docs/changelog.md
	$(BUILD_RUNNER) mkdocs build

docs/index.md: $(CURDIR)/../README.md
	python3 patch_admonitions.py

docs/changelog.md: $(CURDIR)/../CHANGELOG.md
	cp -v $^ $@
