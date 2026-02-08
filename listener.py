from typing import Callable, Optional

from hello_ai.config import AppConfig
from hello_ai.core.speech import SpeechListener
from hello_ai.utils.logging_config import setup_logging


def listen_for_wake_word(on_wake: Callable[[], None], config: Optional[AppConfig] = None) -> None:
    logger = setup_logging()
    settings = config or AppConfig()
    listener = SpeechListener(settings, logger)
    logger.info("Wake word listener active.")

    while True:
        if listener.wait_for_wake_word(settings.wake_word):
            on_wake()


def main() -> None:
    def _on_wake() -> None:
        print("Wake word detected.")

    listen_for_wake_word(_on_wake)


if __name__ == "__main__":
    main()
