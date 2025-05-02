MKDOCS_IMAGE ?= rstudio/rsconnect:mkdocs
VERSION ?= NOTSET

BUILD_RUNNER = \
	docker run --rm --name mkdocs \
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
	$(BUILD_RUNNER) /bin/sh -c "pip3 install /rsconnect_python && mkdocs build"

docs/index.md: $(CURDIR)/../README.md
	python3 patch_admonitions.py < $(CURDIR)/../README.md > docs/index.md

docs/changelog.md: $(CURDIR)/../CHANGELOG.md
	cp -v $^ $@
