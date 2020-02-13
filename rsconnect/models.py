"""
This file defines some support data models.
"""


class AppMode(object):
    def __init__(self, ordinal, symbol, text, ext=None):
        self._ordinal = ordinal
        self._symbol = symbol
        self._text = text
        self._ext = ext

    def ordinal(self):
        return self._ordinal

    def name(self):
        return self._symbol

    def desc(self):
        return self._text

    def extension(self):
        return self._ext

    def __str__(self):
        return self.name()

    def __repr__(self):
        return self.desc()


class AppModes(object):
    UNKNOWN = AppMode(0, 'unknown', '<unknown>')
    SHINY = AppMode(1, 'shiny', 'Shiny App', '.R')
    RMD = AppMode(3, 'rmd-static', 'R Markdown', '.Rmd')
    SHINY_RMD = AppMode(2, 'rmd-shiny', 'Shiny App (Rmd)')
    STATIC = AppMode(4, 'static', 'Static HTML', '.html')
    API = AppMode(5, 'api', 'API')
    TENSORFLOW = AppMode(6, 'tensorflow-saved-model', 'TensorFlow Model')
    JUPYTER_NOTEBOOK = AppMode(7, 'jupyter-static', 'Jupyter Notebook', '.ipynb')

    _modes = [UNKNOWN, SHINY, RMD, SHINY_RMD, STATIC, API, TENSORFLOW, JUPYTER_NOTEBOOK]

    @classmethod
    def get_by_ordinal(cls, ordinal, return_unknown=False):
        return cls._find_by(lambda mode: mode.ordinal() == ordinal, 'with ordinal %d' % ordinal, return_unknown)

    @classmethod
    def get_by_name(cls, name, return_unknown=False):
        return cls._find_by(lambda mode: mode.name() == name, 'named %s' % name, return_unknown)

    @classmethod
    def get_by_extension(cls, extension, return_unknown=False):
        return cls._find_by(lambda mode: mode.extension() == extension, 'with extension: %s' % extension,
                            return_unknown)

    @classmethod
    def _find_by(cls, predicate, message, return_unknown):
        for mode in cls._modes:
            if predicate(mode):
                return mode
        if return_unknown:
            return cls.UNKNOWN
        raise ValueError('No app mode %s' % message)
