import logging
import queue
import threading
from typing import Optional

import pyttsx3

from hello_ai.config import AppConfig


class SpeechEngine:
    def __init__(self, config: AppConfig, logger: Optional[logging.Logger] = None) -> None:
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._engine = pyttsx3.init()
        self._engine.setProperty("rate", config.tts_rate)
        self._engine.setProperty("volume", config.tts_volume)

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._queue.put("")
        if self._thread.is_alive():
            self._thread.join(timeout=2)

    def speak(self, text: str) -> None:
        if not text:
            return
        self._queue.put(text)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                text = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if not text:
                continue
            try:
                self._engine.say(text)
                self._engine.runAndWait()
            except RuntimeError as exc:
                self.logger.warning("TTS runtime error: %s", exc)
