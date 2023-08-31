VERSION := $(shell python setup.py --version)
HOSTNAME := $(shell hostname)
S3_PREFIX := s3://rstudio-connect-downloads/connect/rsconnect-python

BDIST_WHEEL := dist/rsconnect_python-$(VERSION)-py2.py3-none-any.whl

RUNNER = docker run \
  -it --rm \
  -v $(PWD):/rsconnect \
  -w /rsconnect \
  rsconnect-python:$* \
  bash -c

TEST_COMMAND ?= ./scripts/runtests
SHELL_COMMAND ?= bash

ifneq ($(GITHUB_RUN_ID),)
	RUNNER = bash -c
endif

TEST_ENV =

ifneq ($(CONNECT_SERVER),)
  TEST_ENV += CONNECT_SERVER=$(CONNECT_SERVER)
endif
ifneq ($(CONNECT_API_KEY),)
  TEST_ENV += CONNECT_API_KEY=$(CONNECT_API_KEY)
endif
ifneq ($(CONNECT_CONTENT_BUILD_DIR),)
	TEST_ENV += CONNECT_CONTENT_BUILD_DIR=$(CONNECT_CONTENT_BUILD_DIR)
endif

# NOTE: See the `dist` target for why this exists.
SOURCE_DATE_EPOCH := $(shell date +%s)
export SOURCE_DATE_EPOCH

.PHONY: all-tests
all-tests: all-images test-3.7 test-3.8 test-3.9 test-3.10

.PHONY: all-images
all-images: image-3.7 image-3.8 image-3.9 image-3.10

image-%:
	docker build -t rsconnect-python:$* --build-arg BASE_IMAGE=python:$*-slim .

shell-%:
	$(RUNNER) '$(SHELL_COMMAND)'

test-%:
	PYTHON_VERSION=$* $(RUNNER) '$(TEST_ENV) $(TEST_COMMAND)'

mock-test-%: clean-stores
	@$(MAKE) -C mock_connect image up
	@sleep 1
	trap "$(MAKE) -C mock_connect down" EXIT; \
	CONNECT_CONTENT_BUILD_DIR="rsconnect-build-test" \
	CONNECT_SERVER="http://$(HOSTNAME):3939" \
	CONNECT_API_KEY="0123456789abcdef0123456789abcdef" \
	$(MAKE) test-$*
	@$(MAKE) -C mock_connect down

fmt-%:
	$(RUNNER) 'black .'

.PHONY: .fmt-unsupported
.fmt-unsupported:
	@echo ERROR: This python version cannot run the fmting tools
	@exit 1

.PHONY: deps-prerelease
deps-prerelease:
	pip install --pre -r requirements.txt

deps-%:
	$(RUNNER) 'pip install --pre -r requirements.txt'

lint-%:
	$(RUNNER) 'black --check --diff rsconnect/'
	$(RUNNER) 'flake8 rsconnect/'
	$(RUNNER) 'flake8 tests/'
	$(RUNNER) 'mypy -p rsconnect'

.PHONY: .lint-unsupported
.lint-unsupported:
	@echo ERROR: This python version cannot run the linting tools
	@exit 1

.PHONY: clean
clean:
	$(RM) -r \
		./.coverage \
		./.mypy_cache \
		./.pytest_cache \
		./build \
		./dist \
		./htmlcov \
		./rsconnect_python.egg-info

.PHONY: clean-stores
clean-stores:
	@find . -name "rsconnect-python" | xargs rm -rf

.PHONY: shell
shell: RUNNER = bash -c
shell: shell-3.8

.PHONY: test
test: RUNNER = bash -c
test: test-3.8

.PHONY: lint
lint: RUNNER = bash -c
lint: lint-3.8

.PHONY: deps
deps: RUNNER = bash -c
deps: deps-3.8

.PHONY: fmt
fmt: RUNNER = bash -c
fmt: fmt-3.8

.PHONY: docs
docs:
	$(MAKE) -C docs VERSION=$(VERSION)

.PHONY: version
version:
	@echo $(VERSION)

# NOTE: Wheels won't get built if _any_ file it tries to touch has a timestamp
# before 1980 (system files) so the $(SOURCE_DATE_EPOCH) current timestamp is
# exported as a point of reference instead.
.PHONY: dist
dist:
	python setup.py bdist_wheel
	twine check $(BDIST_WHEEL)
	rm -vf dist/*.egg
	@echo "::set-output name=whl::$(BDIST_WHEEL)"
	@echo "::set-output name=whl_basename::$(notdir $(BDIST_WHEEL))"

.PHONY: sync-to-s3
sync-to-s3:
	aws s3 cp --acl bucket-owner-full-control \
		$(BDIST_WHEEL) \
		$(S3_PREFIX)/$(VERSION)/$(notdir $(BDIST_WHEEL))

.PHONY: sync-latest-to-s3
sync-latest-to-s3:
	aws s3 cp --acl bucket-owner-full-control \
		--cache-control max-age=0 \
		$(BDIST_WHEEL) \
		$(S3_PREFIX)/latest/rsconnect_python-latest-py2.py3-none-any.whl

.PHONY: sync-latest-docs-to-s3
sync-latest-docs-to-s3:
	aws s3 sync --acl bucket-owner-full-control \
		--cache-control max-age=0 \
		docs/site/ \
		$(S3_PREFIX)/latest/docs/

.PHONY: promote-docs-in-s3
promote-docs-in-s3:
	aws s3 sync --delete --acl bucket-owner-full-control \
		--cache-control max-age=300 \
		docs/site/ \
		s3://docs.rstudio.com/rsconnect-python/

RSC_API_KEYS=vetiver-testing/rsconnect_api_keys.json

dev:
	docker-compose up -d
	docker-compose exec -T rsconnect bash < vetiver-testing/setup-rsconnect/add-users.sh
	python vetiver-testing/setup-rsconnect/dump_api_keys.py $(RSC_API_KEYS)

dev-stop:
	docker-compose down
	rm -f $(RSC_API_KEYS)
