import logging
from typing import Optional

import speech_recognition as sr

from hello_ai.config import AppConfig


class SpeechListener:
    def __init__(self, config: AppConfig, logger: Optional[logging.Logger] = None) -> None:
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = config.energy_threshold
        self.recognizer.pause_threshold = config.pause_threshold
        self.microphone = sr.Microphone()

    def _recognize_audio(self, audio: sr.AudioData) -> Optional[str]:
        for language in (self.config.language_primary, self.config.language_secondary):
            try:
                return self.recognizer.recognize_google(audio, language=language)
            except sr.UnknownValueError:
                continue
            except sr.RequestError as exc:
                self.logger.warning("Speech recognition error: %s", exc)
                return None
        return None

    def listen_once(self) -> Optional[str]:
        with self.microphone as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
            try:
                audio = self.recognizer.listen(
                    source,
                    timeout=self.config.listen_timeout,
                    phrase_time_limit=self.config.phrase_time_limit,
                )
            except sr.WaitTimeoutError:
                return None
        return self._recognize_audio(audio)

    def wait_for_wake_word(self, wake_word: str) -> bool:
        transcript = self.listen_once()
        if not transcript:
            return False
        normalized = transcript.lower().strip()
        return wake_word in normalized
