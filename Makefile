
VERSION=$(shell cat rsconnect/version.txt).$(shell printenv BUILD_NUMBER || echo 9999)

RUNNER=docker run -it --rm \
		-v $(PWD):/rsconnect \
		-w /rsconnect \
		rsconnect-python:$* \
		bash -c

ifneq (${JOB_NAME},)
	# Jenkins
	RUNNER=bash -c
endif

all-tests: all-images test-2.7 test-3.5 test-3.6 test-3.7 test-3.8

all-images: image-2.7 image-3.5 image-3.6 image-3.7 image-3.8

image-%:
	docker build -t rsconnect-python:$* --build-arg BASE_IMAGE=python:$* .

shell-%:
	$(RUNNER) 'python setup.py develop --user && bash'

test-%:
	$(RUNNER) 'python setup.py develop --user && python -m unittest discover'

coverage-%:
	$(RUNNER) 'python setup.py develop --user && pytest --cov=rsconnect --cov-report=html --no-cov-on-fail rsconnect/tests/'

lint-%:
	$(RUNNER) 'pyflakes ./rsconnect/'

.PHONY: docs
docs:
	docker run --rm \
		-v ${PWD}:/rsconnect-python \
		-w /rsconnect-python \
		-e VERSION="${VERSION}" \
		pandoc/latex:2.8.0.1 \
		docs/build-doc.sh

.PHONY: dist
dist:
# wheels don't get built if _any_ file it tries to touch has a timestamp < 1980
# (system files) so use the current timestamp as a point of reference instead
	SOURCE_DATE_EPOCH="$(shell date +%s)"; python setup.py sdist bdist_wheel; rm -f dist/*.egg
