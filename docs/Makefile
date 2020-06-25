MKDOCS_IMAGE ?= rstudio/rsconnect:mkdocs
VERSION ?= NOTSET

DOCKER_RUN_AS =
ifeq (Linux,$(shell uname))
	DOCKER_RUN_AS = -u $(shell id -u):$(shell id -g)
endif

BUILD_RUNNER = \
	docker run --rm --name mkdocs \
		$(DOCKER_RUN_AS) \
		-e VERSION=$(VERSION) \
		-v $(CURDIR):/mkdocs \
		-w /mkdocs \
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
build: docs/index.md
	$(BUILD_RUNNER) mkdocs build
	@rm docs/index.md

docs/index.md: $(CURDIR)/../README.md
	python patch_admonitions.py
