class RSConnectException(Exception):
    def __init__(self, message, cause=None):
        super(RSConnectException, self).__init__(message)
        self.message = message
        self.cause = cause
