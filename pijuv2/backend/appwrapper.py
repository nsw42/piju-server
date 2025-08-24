from typing import cast, TYPE_CHECKING

from flask import current_app


if TYPE_CHECKING:
    from .appfactory import PijuApp
else:
    class PijuApp:
        pass


class FlaskWrapper:
    @property
    def current_piju_app(self) -> PijuApp:
        return cast(PijuApp, current_app)


current_piju_app = FlaskWrapper().current_piju_app
