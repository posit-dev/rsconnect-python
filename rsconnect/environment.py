import typing
import dataclasses

from .subprocesses.environment import EnvironmentData, MakeEnvironmentData as _MakeEnvironmentData


class Environment:
    """A project environment,

    The data is loaded from a rsconnect.utils.environment json response
    """

    def __init__(self, data: EnvironmentData, python_version_requirement: typing.Optional[str] = None):
        self._data = data
        self._data_fields = dataclasses.fields(self.data)

        # Fields that are not loaded from the environment subprocess
        self.python_version_requirement

    def __getattr__(self, name: str) -> typing.Any:
        # We directly proxy the attributes of the EnvironmentData object
        # so that schema changes can be handled in EnvironmentData exclusively.
        return self._data[name]

    def __setattr__(self, name, value):
        if name in self._data_fields:
            # proxy the attribute to the underlying EnvironmentData object
            self._data._replace(name=value)
        else:
            super().__setattr__(name, value)

    @classmethod
    def from_json(cls, json_data: dict) -> "Environment":
        """Create an Environment instance from the JSON representation of EnvironmentData."""
        return cls(_MakeEnvironmentData(**json_data))
