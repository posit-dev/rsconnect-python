VERSION := $(shell cat rsconnect/version.txt).$(shell printenv BUILD_NUMBER || echo 9999)
HOSTNAME := $(shell hostname)

RUNNER = docker run \
  -it --rm \
  -v $(PWD):/rsconnect \
  -w /rsconnect \
  rsconnect-python:$* \
  bash -c

PYTEST_COMMAND := pipenv run \
  pytest -vv \
  --cov=rsconnect \
  --cov-report=term \
  --cov-report=html \
  ./

ifneq ($(JOB_NAME),)
  RUNNER = bash -c
endif
ifneq ($(LOCAL),)
  RUNNER = bash -c
endif

TEST_ENV =

ifneq ($(CONNECT_SERVER),)
  TEST_ENV += CONNECT_SERVER=$(CONNECT_SERVER)
endif
ifneq ($(CONNECT_API_KEY),)
  TEST_ENV += CONNECT_API_KEY=$(CONNECT_API_KEY)
endif

# NOTE: See the `dist` target for why this exists.
SOURCE_DATE_EPOCH := $(shell date +%s)
export SOURCE_DATE_EPOCH

.PHONY: all-tests
all-tests: all-images test-2.7 test-3.5 test-3.6 test-3.7 test-3.8

.PHONY: all-images
all-images: image-2.7 image-3.5 image-3.6 image-3.7 image-3.8

image-%:
	docker build -t rsconnect-python:$* --build-arg BASE_IMAGE=python:$* .

shell-%:
	$(RUNNER) 'pipenv shell'

test-%:
	$(RUNNER) '$(TEST_ENV) $(PYTEST_COMMAND)'

mock-test-%: clean-stores
	@$(MAKE) -C mock_connect image up
	@sleep 1
	CONNECT_SERVER=http://$(HOSTNAME):3939 CONNECT_API_KEY=0123456789abcdef0123456789abcdef $(MAKE) test-$*
	@$(MAKE) -C mock_connect down

fmt-%:
	$(RUNNER) 'pipenv run black .'

lint-%:
	$(RUNNER) 'pipenv run black --check --diff .'
	$(RUNNER) 'pipenv run flake8 rsconnect/'

.PHONY: clean clean-stores
clean:
	@rm -rf build dist rsconnect_python.egg-info

clean-stores:
	@find . -name "rsconnect-python" | xargs rm -rf

.PHONY: shell
shell: LOCAL = 1
shell: shell-3.8

.PHONY: test
test: LOCAL = 1
test: test-3.8

.PHONY: lint
lint: LOCAL = 1
lint: lint-3.8

.PHONY: fmt
fmt: LOCAL = 1
fmt: fmt-3.8

.PHONY: docs
docs:
	$(MAKE) -C docs

# NOTE: Wheels won't get built if _any_ file it tries to touch has a timestamp
# before 1980 (system files) so the $(SOURCE_DATE_EPOCH) current timestamp is
# exported as a point of reference instead.
.PHONY: dist
dist:
	python setup.py sdist bdist_wheel && \
		rm -vf dist/*.egg
