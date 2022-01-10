#
# Makefile for our mock Connect server.
#
# The targets here provide all the support for running a mock version of Connect.
#
MOCK_IMAGE?="rstudio/connect:mock"
MOCK_HOST?="mock-connect"
PRE_FETCH_FILE?="data.json"
LOG_FILE?="mock_connect.log"

# Build the image in which the mock server will run.
image:
	docker build -t ${MOCK_IMAGE} .

# Bring the mock Connect server up.  Note that it is run as a daemon.
up:
	@echo "Starting ${MOCK_HOST} ..."
	@docker run --rm -d -t --init \
		--name ${MOCK_HOST} \
		--volume $(CURDIR):/rsconnect \
		--volume $(CURDIR)/../tests/testdata:/testdata \
		--env=FLASK_APP=/rsconnect/mock_connect/main.py \
		--env=PRE_FETCH_FILE=${PRE_FETCH_FILE} \
		--publish 3939:3939 \
		--workdir /rsconnect \
		${MOCK_IMAGE} \
		flask run --host=0.0.0.0 --port=3939 1>/dev/null
	@docker logs -f ${MOCK_HOST} > ${LOG_FILE} &

# Bring the mock Connect server down.
down:
	$(eval CONNECT_EXISTS=$(shell docker container inspect ${MOCK_HOST} > /dev/null 2>&1 && echo 0 || echo 1))
	@if [ "${CONNECT_EXISTS}" = "0" ] ; then \
	    echo "Stopping ${MOCK_HOST} ..."; \
	    docker stop ${MOCK_HOST} 1>/dev/null; \
	fi;

# Clean up after ourselves.
clean:
	@rm -f ${LOG_FILE}

# Start the mock Connect docker image but just dump into a shell.
sh:
	@docker run --name mock_connect --rm -it \
		-v $(CURDIR):/rsconnect -w /rsconnect \
		${MOCK_IMAGE} sh

# Nothing is real...
.PHONY: image up down clean sh
