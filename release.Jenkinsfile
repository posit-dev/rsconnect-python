// The pipeline in this file syncs documentation from the project's s3 bucket to
// docs.rstudio.com where documentation is publicly visible. This pipeline
// should be manually triggered on Jenkins when a release is cut.
pipeline {
    agent { node('docker') }
    parameters {
        string(name: 'RELEASE_VERSION', description: 'The release version (maj.min.patch.build) to promote.')
        booleanParam(name: 'DOCS_RELEASE', description: 'When checked, push artifacts to S3')
        booleanParam(name: 'PYPI_RELEASE', description: 'When checked, push the wheel and sdist to PyPI')
    }
    stages {
        stage('Check Parameters') {
            when {
                expression { return params.RELEASE_VERSION == "" }
            }
            steps {
                error "You need to specify a release version to promote."
            }
        }
        stage('Promote Docs (Dry Run)') {
            when {
                allOf {
                    expression { return !params.DOCS_RELEASE }
                    expression { return params.RELEASE_VERSION != "" }
                }
            }
            steps {
                sh "aws s3 sync s3://rstudio-rsconnect-jupyter/rsconnect-python-preview/ s3://docs.rstudio.com/rsconnect-python/ --dryrun"
            }
        }
        stage('Promote Docs') {
            when {
                allOf {
                    expression { return params.DOCS_RELEASE }
                    expression { return params.RELEASE_VERSION != "" }
                }
            }
            steps {
                sh "aws s3 sync s3://rstudio-rsconnect-jupyter/rsconnect-python-preview/ s3://docs.rstudio.com/rsconnect-python/"
            }
        }
        stage('Release to PyPI (dry run)') {
            when {
                allOf {
                    expression { return !params.PYPI_RELEASE }
                    expression { return params.RELEASE_VERSION != "" }
                }
            }
            environment {
                PYPI_CREDS = credentials('pypi')
            }
            steps {
                sh "aws s3 cp s3://rstudio-rsconnect-jupyter/rsconnect_python-${RELEASE_VERSION}-py2.py3-none-any.whl ."
                sh "aws s3 cp s3://rstudio-rsconnect-jupyter/rsconnect_python-${RELEASE_VERSION}.tar.gz ."
                sh "pip install --user --upgrade twine==1.15 setuptools wheel"
                sh """python -m twine upload \
                    --repository-url https://test.pypi.org/legacy/ \
                    -u ${PYPI_CREDS_USR} \
                    -p ${PYPI_CREDS_PSW} \
                    rsconnect_python-${RELEASE_VERSION}-py2.py3-none-any.whl \
                    rsconnect_python-${RELEASE_VERSION}.tar.gz \
                """
            }
        }
        stage('Release to PyPI') {
            when {
                allOf {
                    expression { return params.PYPI_RELEASE }
                    expression { return params.RELEASE_VERSION != "" }
                }
            }
            environment {
                PYPI_CREDS = credentials('pypi')
            }
            steps {
                sh "aws s3 cp s3://rstudio-rsconnect-jupyter/rsconnect_python-${RELEASE_VERSION}-py2.py3-none-any.whl ."
                sh "aws s3 cp s3://rstudio-rsconnect-jupyter/rsconnect_python-${RELEASE_VERSION}.tar.gz ."
                sh "pip install --user --upgrade twine==1.15 setuptools wheel"
                sh """python -m twine upload \
                    -u ${PYPI_CREDS_USR} \
                    -p ${PYPI_CREDS_PSW} \
                    rsconnect_python-${RELEASE_VERSION}-py2.py3-none-any.whl \
                    rsconnect_python-${RELEASE_VERSION}.tar.gz \
                """
            }
        }
    }
}
