import logging
import threading
import webbrowser
from typing import Optional

from flask import Flask

from hello_ai.config import AppConfig


class DashboardService:
    def __init__(self, config: AppConfig, logger: Optional[logging.Logger] = None) -> None:
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self._thread: Optional[threading.Thread] = None
        self._app = Flask("hello_ai")

        @self._app.route("/")
        def home() -> str:
            return "Hello AI dashboard running."

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        def _run() -> None:
            self._app.run(host=self.config.dashboard_host, port=self.config.dashboard_port)

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def open(self) -> None:
        self.start()
        webbrowser.open(self.config.dashboard_open_url)
        self.logger.info("Dashboard opened at %s", self.config.dashboard_open_url)
