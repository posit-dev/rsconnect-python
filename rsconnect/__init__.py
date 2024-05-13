try:
    from .version import version as VERSION  # pyright: ignore[reportUnusedImport]
except ImportError:
    VERSION = "NOTSET"  # pyright: ignore[reportConstantRedefinition]
