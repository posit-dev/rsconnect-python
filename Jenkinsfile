#!groovy

def gitClean() {
  // inspired by: https://issues.jenkins-ci.org/browse/JENKINS-31924
  // https://issues.jenkins-ci.org/browse/JENKINS-32540
  // The sequence of reset --hard and clean -fdx first
  // in the root and then using submodule foreach
  // is based on how the Jenkins Git SCM clean before checkout
  // feature works.
  sh 'git reset --hard'
  sh 'git clean -ffdx'
}

// Build the name:tag for a docker image where the tag is the checksum
// computed from a specified file.
def imageName(name, filenames) {
  // If this is extended to support multiple files, be wary of:
  // https://issues.jenkins-ci.org/browse/JENKINS-26481
  // closures don't really work.

  // Suck in the contents of the file and then hash the result.
  def contents = "";
  for (int i=0; i<filenames.size(); i++) {
    print "reading ${filenames[i]}"
    def content = readFile(filenames[i])
    print "read ${filenames[i]}"
    contents = contents + content
  }

  print "hashing ${name}"
  def tag = java.security.MessageDigest.getInstance("MD5").digest(contents.bytes).encodeHex().toString()
  print "hashed ${name}"
  def result = "${name}:${tag}"
  print "computed image name ${result}"
  return result
}

isUserBranch = true
if (env.BRANCH_NAME == 'master') {
  isUserBranch = false
} else if (env.BRANCH_NAME ==~ /^\d+\.\d+\.\d+$/) {
  isUserBranch = false
}

messagePrefix = "<${env.JOB_URL}|rsconnect-python pipeline> build <${env.BUILD_URL}|${env.BUILD_DISPLAY_NAME}>"

slackChannelPass = "#rsconnect-bots"
slackChannelFail = "#rsconnect"
if (isUserBranch) {
  slackChannelFail = "#rsconnect-bots"
}

nodename = 'docker'
if (isUserBranch) {
  // poor man's throttling for user branches.
  nodename = 'connect-branches'
}

def buildImage(pyVersion) {
  return pullBuildPush(
    image_name: 'jenkins/rsconnect-python',
    image_tag: "python${pyVersion}",
    build_args: "--build-arg BASE_IMAGE=python:${pyVersion}",
    push: !isUserBranch
  )
}

def buildAndTest(pyVersion) {
  img = buildImage(pyVersion)

  img.inside("-v ${env.WORKSPACE}:/rsconnect") {
    sh "make lint-${pyVersion}"
    sh "HOME=`mktemp -d` make test-${pyVersion}"
  }
  return img
}

def publishArtifacts() {
    // Promote master builds to S3
    cmd = "aws s3 sync dist s3://rstudio-rsconnect-jupyter/"

    if (isUserBranch) {
        print "S3 sync DRY RUN for user branch ${env.BRANCH_NAME}"
        sh (cmd + ' --dryrun')
    } else {
        print "S3 sync for ${env.BRANCH_NAME}"
        sh cmd
    }
}

try {
  node(nodename) {
    timestamps {
      checkout scm
      gitClean()

      // If we want to link to the commit, we need to drop down to shell. This
      // means that we need to be inside a `node` and after checking-out code.
      // https://issues.jenkins-ci.org/browse/JENKINS-26100 suggests this workaround.
      gitSHA = sh(returnStdout: true, script: 'git rev-parse HEAD').trim()
      shortSHA = gitSHA.take(6)

      // Update our Slack message metadata with commit info once we can obtain it.
      messagePrefix = messagePrefix + " of <https://github.com/rstudio/rsconnect-python/commit/${gitSHA}|${shortSHA}>"

      // Looking up the author also demands being in a `node`.
      gitAuthor = sh(returnStdout: true, script: 'git --no-pager show -s --format="%aN" HEAD').trim()

      stage('Build') {
        img = buildImage("3.6")

        img.inside("-v ${env.WORKSPACE}:/rsconnect") {
          print "building python wheel package"
          sh 'HOME=`mktemp -d` pip install --user --upgrade twine setuptools wheel && make dist'
          archiveArtifacts artifacts: 'dist/*.whl,dist/*.tar.gz'
        }
      }
      stage('Test') {
        parallel(
          'python2.7': {
            buildAndTest("2.7")
          },
          'python3.5': {
            buildAndTest("3.5")
          },
          'python3.6': {
            buildAndTest("3.6")
          },
          'python3.7': {
            buildAndTest("3.7")
          },
          'python3.8': {
            buildAndTest("3.8")
          }
        )
      }
      stage('Documentation') {
        sh 'make docs'
        archiveArtifacts artifacts: 'dist/*.pdf,dist/*.html'
      }
      stage('S3 upload') {
        publishArtifacts()
      }
    }
  }

  // Slack message includes username information.
  message = "${messagePrefix} by ${gitAuthor} passed"
  slackSend channel: slackChannelPass, color: 'good', message: message
} catch(err) {
  // Slack message includes username information. When master/release fails,
  // CC the whole connect team.
  slackNameFail = gitAuthor
  if (!isUserBranch) {
    slackNameFail = "${gitAuthor} (cc @rsconnect_python)"
  }

  message = "${messagePrefix} by ${slackNameFail} failed: ${err}"
  slackSend channel: slackChannelFail, color: 'bad', message: message
  throw err
}
