import datetime
import logging
from typing import Optional

from hello_ai.services.dashboard import DashboardService
from hello_ai.services.system_control import open_chrome, open_notepad


class CommandRouter:
    def __init__(self, dashboard: DashboardService, logger: Optional[logging.Logger] = None) -> None:
        self.dashboard = dashboard
        self.logger = logger or logging.getLogger(__name__)

    def route(self, command: str) -> str:
        normalized = command.lower().strip()
        if not normalized:
            return "I didn't catch that. Please say it again."

        if "open chrome" in normalized:
            return open_chrome()
        if "open notepad" in normalized:
            return open_notepad()
        if "open dashboard" in normalized or "dashboard" in normalized:
            self.dashboard.open()
            return "Opening the dashboard."
        if "time" in normalized:
            now = datetime.datetime.now().strftime("%I:%M %p")
            return f"The time is {now}."
        if "date" in normalized:
            today = datetime.datetime.now().strftime("%B %d, %Y")
            return f"Today's date is {today}."
        if "stop" in normalized or "exit" in normalized:
            return "Goodbye."

        return (
            "I'm still learning that command. You can say open chrome, open notepad, "
            "or open dashboard."
        )
