try:
    from .version import version as VERSION  # noqa
except ImportError:
    VERSION = "NOTSET"  # noqa
