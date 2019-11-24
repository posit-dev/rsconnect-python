
all-tests: all-images test-2.7 test-3.5 test-3.6 test-3.7 test-3.8

all-images: image-2.7 image-3.5 image-3.6 image-3.7 image-3.8

image-%:
	docker build -t rsconnect-python:$* --build-arg BASE_IMAGE=python:$* .

test-%:
	docker run -it --rm \
		-v $(PWD):/rsconnect \
		-w /rsconnect \
		rsconnect-python:$* \
		bash -c 'python setup.py install && python -m unittest discover'

lint-%:
	docker run -it --rm \
		-v $(PWD):/rsconnect \
		-w /rsconnect \
		rsconnect-python:$* \
		pyflakes ./rsconnect/

shell-%:
	docker run -it --rm \
		-v $(PWD):/rsconnect \
		-w /rsconnect \
		rsconnect-python:$* \
		bash -c 'python setup.py install && bash'
