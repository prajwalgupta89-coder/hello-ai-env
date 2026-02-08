import contextlib
import datetime
import json
import logging
import os
import queue
import signal
import socket
import sqlite3
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pyttsx3
import speech_recognition as sr

try:
    import requests
except ImportError:  # Optional dependency for online services
    requests = None


@dataclass
class AppConfig:
    wake_word: str = "hey hello ai"
    language_primary: str = "en-IN"
    language_secondary: str = "hi-IN"
    energy_threshold: int = 300
    pause_threshold: float = 0.8
    listen_timeout: float = 5.0
    phrase_time_limit: float = 7.0
    tts_rate: int = 175
    tts_volume: float = 1.0
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 5000
    dashboard_url: str = "http://127.0.0.1:5000"
    memory_path: str = "hello_ai_memory.sqlite3"
    allowed_paths: List[str] = field(default_factory=lambda: [os.path.expanduser("~")])
    openai_api_key: Optional[str] = field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    elevenlabs_api_key: Optional[str] = field(default_factory=lambda: os.getenv("ELEVENLABS_API_KEY"))
    enable_openai: bool = True
    enable_dashboard: bool = True


def setup_logging() -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    return logging.getLogger("hello_ai")


class MemoryStore:
    def __init__(self, db_path: str, logger: logging.Logger) -> None:
        self.db_path = db_path
        self.logger = logger
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    summary TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def remember(self, key: str, value: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO memories (key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, datetime.datetime.utcnow().isoformat()),
            )
            conn.commit()

    def forget(self, key: str) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute("DELETE FROM memories WHERE key = ?", (key,))
            conn.commit()
            return cursor.rowcount > 0

    def recall(self, key: str) -> Optional[str]:
        with self._lock, self._connect() as conn:
            cursor = conn.execute("SELECT value FROM memories WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row[0] if row else None

    def list_memories(self) -> Dict[str, str]:
        with self._lock, self._connect() as conn:
            cursor = conn.execute("SELECT key, value FROM memories ORDER BY updated_at DESC")
            return {row[0]: row[1] for row in cursor.fetchall()}

    def add_conversation_summary(self, summary: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO conversations (id, created_at, summary) VALUES (?, ?, ?)",
                (str(uuid.uuid4()), datetime.datetime.utcnow().isoformat(), summary),
            )
            conn.commit()


class SpeechListener:
    def __init__(self, config: AppConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = config.energy_threshold
        self.recognizer.pause_threshold = config.pause_threshold
        self.microphone = sr.Microphone()

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

    def _recognize_audio(self, audio: sr.AudioData) -> Optional[str]:
        for language in (self.config.language_primary, self.config.language_secondary):
            try:
                text = self.recognizer.recognize_google(audio, language=language)
                return text
            except sr.UnknownValueError:
                continue
            except sr.RequestError as exc:
                self.logger.warning("Speech recognition error: %s", exc)
                return None
        return None

    def wait_for_wake_word(self, wake_word: str) -> bool:
        transcript = self.listen_once()
        if not transcript:
            return False
        normalized = transcript.lower().strip()
        return wake_word in normalized


class TextToSpeechEngine:
    def __init__(self, config: AppConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
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
            if self._try_elevenlabs(text):
                continue
            self._speak_offline(text)

    def _try_elevenlabs(self, text: str) -> bool:
        if not self.config.elevenlabs_api_key or not requests:
            return False
        if not is_internet_available():
            return False
        try:
            response = requests.post(
                "https://api.elevenlabs.io/v1/text-to-speech/EXAVITQu4vr4xnSDxMaL",
                headers={
                    "xi-api-key": self.config.elevenlabs_api_key,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
                data=json.dumps({"text": text, "voice_settings": {"stability": 0.5, "similarity_boost": 0.8}}),
                timeout=10,
            )
            if response.status_code != 200:
                self.logger.warning("ElevenLabs error: %s", response.text)
                return False
            filename = f"tts_{uuid.uuid4().hex}.mp3"
            with open(filename, "wb") as audio_file:
                audio_file.write(response.content)
            os.startfile(filename)
            return True
        except Exception as exc:
            self.logger.warning("ElevenLabs TTS failed: %s", exc)
            return False

    def _speak_offline(self, text: str) -> None:
        try:
            self._engine.say(text)
            self._engine.runAndWait()
        except Exception as exc:
            self.logger.error("Offline TTS failed: %s", exc)


class DashboardController:
    def __init__(self, config: AppConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self._thread: Optional[threading.Thread] = None
        self._app = None

        if config.enable_dashboard:
            with contextlib.suppress(Exception):
                from flask import Flask

                self._app = Flask("hello_ai")

                @self._app.route("/")
                def home() -> str:
                    return "Hello AI dashboard running."

    def start(self) -> None:
        if not self._app:
            self.logger.warning("Dashboard unavailable: Flask not installed.")
            return
        if self._thread and self._thread.is_alive():
            return

        def _run() -> None:
            self._app.run(host=self.config.dashboard_host, port=self.config.dashboard_port)

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def open(self) -> None:
        self.start()
        with contextlib.suppress(Exception):
            import webbrowser

            webbrowser.open(self.config.dashboard_url)
        self.logger.info("Dashboard opened at %s", self.config.dashboard_url)


def is_internet_available() -> bool:
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=1)
        return True
    except OSError:
        return False


class SystemController:
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    def open_app(self, app_name: str) -> str:
        name = app_name.lower()
        if "chrome" in name:
            return self._open_chrome()
        if "notepad" in name:
            return self._open_notepad()
        if "whatsapp" in name:
            return self._open_whatsapp()
        if "control panel" in name or "control" in name:
            return self._open_control_panel()
        if "settings" in name:
            return self._open_settings()
        return "I don't know that app yet."

    def _open_chrome(self) -> str:
        chrome_paths = [
            os.path.expandvars(r"%ProgramFiles%\\Google\\Chrome\\Application\\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\\Google\\Chrome\\Application\\chrome.exe"),
        ]
        for path in chrome_paths:
            if os.path.exists(path):
                os.startfile(path)
                return "Opening Google Chrome."
        return "Chrome is not installed."

    def _open_notepad(self) -> str:
        os.startfile("notepad.exe")
        return "Opening Notepad."

    def _open_whatsapp(self) -> str:
        with contextlib.suppress(Exception):
            os.startfile("shell:AppsFolder\\5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App")
            return "Opening WhatsApp."
        return "WhatsApp is not available."

    def _open_control_panel(self) -> str:
        os.startfile("control.exe")
        return "Opening Control Panel."

    def _open_settings(self) -> str:
        os.startfile("ms-settings:")
        return "Opening Settings."

    def safe_list_directory(self, path: str, allowed_paths: List[str]) -> Tuple[bool, str]:
        if not self._is_allowed_path(path, allowed_paths):
            return False, "Access denied for that path."
        try:
            items = os.listdir(path)
            return True, ", ".join(items[:50]) or "Folder is empty."
        except Exception as exc:
            self.logger.warning("List directory failed: %s", exc)
            return False, "Could not list that folder."

    def _is_allowed_path(self, path: str, allowed_paths: List[str]) -> bool:
        normalized = os.path.abspath(path)
        for allowed in allowed_paths:
            if normalized.startswith(os.path.abspath(allowed)):
                return True
        return False


class IntentParser:
    def __init__(self) -> None:
        self.intent_map = {
            "open_app": ["open", "kholo", "khoolo"],
            "dashboard": ["dashboard", "dashbord", "logs dikhao", "dashboard kholo"],
            "time": ["time", "samay", "kitna time", "time kya hai"],
            "date": ["date", "tarikh", "aaj ki date"],
            "remember": ["yaad rakhna", "remember"],
            "forget": ["bhool jao", "forget"],
            "list_memory": ["yaad kya hai", "memories"],
            "status": ["status", "haal", "report"],
            "exit": ["exit", "stop", "band", "goodbye"],
        }

    def parse(self, text: str) -> Tuple[str, str]:
        normalized = text.lower().strip()
        for intent, triggers in self.intent_map.items():
            if any(trigger in normalized for trigger in triggers):
                return intent, normalized
        return "chat", normalized


class OptionalOpenAIClient:
    def __init__(self, api_key: Optional[str], logger: logging.Logger) -> None:
        self.api_key = api_key
        self.logger = logger

    def is_available(self) -> bool:
        return bool(self.api_key and requests and is_internet_available())

    def chat(self, prompt: str) -> Optional[str]:
        if not self.is_available():
            return None
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                data=json.dumps(
                    {
                        "model": "gpt-4o-mini",
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.4,
                    }
                ),
                timeout=15,
            )
            if response.status_code != 200:
                self.logger.warning("OpenAI error: %s", response.text)
                return None
            payload = response.json()
            return payload["choices"][0]["message"]["content"]
        except Exception as exc:
            self.logger.warning("OpenAI request failed: %s", exc)
            return None


class AIBrain:
    def __init__(self, config: Optional[AppConfig] = None) -> None:
        self.config = config or AppConfig()
        self.logger = setup_logging()
        self.listener = SpeechListener(self.config, self.logger)
        self.tts = TextToSpeechEngine(self.config, self.logger)
        self.memory = MemoryStore(self.config.memory_path, self.logger)
        self.dashboard = DashboardController(self.config, self.logger)
        self.system = SystemController(self.logger)
        self.intent_parser = IntentParser()
        self.openai_client = OptionalOpenAIClient(self.config.openai_api_key, self.logger)
        self._stop_event = threading.Event()

    def start(self) -> None:
        self.logger.info("Hello AI brain starting.")
        self.tts.start()
        self._register_shutdown_signals()
        self._greet_on_startup()
        self._main_loop()

    def _register_shutdown_signals(self) -> None:
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

    def _handle_shutdown(self, *_: object) -> None:
        self.logger.info("Shutting down Hello AI.")
        self._stop_event.set()
        self.tts.stop()

    def _greet_on_startup(self) -> None:
        self.tts.speak("Hello Sir, aaj aapke kya tasks hain?")

    def _main_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                if not self.listener.wait_for_wake_word(self.config.wake_word):
                    continue
                self._handle_interaction()
            except Exception as exc:
                self.logger.error("Crash recovered: %s", exc)
                self.logger.debug(traceback.format_exc())
                self.tts.speak("Mujhe thodi dikkat hui, phir se boliye.")
                time.sleep(0.5)

    def _handle_interaction(self) -> None:
        self.tts.speak("Yes, how can I help you?")
        command = self.listener.listen_once()
        if not command:
            self.tts.speak("I didn't hear a command. Please try again.")
            return
        response = self._process_command(command)
        self.tts.speak(response)
        self.memory.add_conversation_summary(f"User: {command} | AI: {response}")
        if response.lower().startswith("goodbye"):
            self._stop_event.set()

    def _process_command(self, command: str) -> str:
        intent, normalized = self.intent_parser.parse(command)
        if intent == "open_app":
            return self.system.open_app(normalized)
        if intent == "dashboard":
            self.dashboard.open()
            return "Dashboard khol raha hoon."
        if intent == "time":
            now = datetime.datetime.now().strftime("%I:%M %p")
            return f"Abhi time hai {now}."
        if intent == "date":
            today = datetime.datetime.now().strftime("%B %d, %Y")
            return f"Aaj ki date hai {today}."
        if intent == "remember":
            return self._handle_remember(normalized)
        if intent == "forget":
            return self._handle_forget(normalized)
        if intent == "list_memory":
            memories = self.memory.list_memories()
            if not memories:
                return "Abhi koi yaad stored nahi hai."
            memory_list = "; ".join(f"{key}: {value}" for key, value in memories.items())
            return f"Aapke yaadein: {memory_list}"
        if intent == "status":
            return self._status_report()
        if intent == "exit":
            return "Goodbye."
        response = self._openai_or_offline_response(command)
        return response or "Main samajh nahi paaya. Kripya dobara boliye."

    def _handle_remember(self, text: str) -> str:
        parts = text.split("yaad rakhna", 1)
        content = parts[1].strip() if len(parts) > 1 else ""
        if not content:
            return "Kya yaad rakhna hai? Aap detail bataye."
        key = content.split()[0]
        self.memory.remember(key, content)
        return f"Yaad rakh liya: {content}"

    def _handle_forget(self, text: str) -> str:
        parts = text.split("bhool jao", 1)
        key = parts[1].strip().split()[0] if len(parts) > 1 else ""
        if not key:
            return "Kya bhoolna hai? Key bataye."
        if self.memory.forget(key):
            return f"Bhool gaya {key}."
        return f"{key} ke baare mein koi yaad nahi hai."

    def _status_report(self) -> str:
        online_status = "online" if is_internet_available() else "offline"
        memory_count = len(self.memory.list_memories())
        return f"Status: {online_status}. Stored memories: {memory_count}."

    def _openai_or_offline_response(self, prompt: str) -> Optional[str]:
        if self.config.enable_openai and self.openai_client.is_available():
            response = self.openai_client.chat(prompt)
            if response:
                return response
        return self._offline_smalltalk(prompt)

    def _offline_smalltalk(self, prompt: str) -> str:
        normalized = prompt.lower()
        if "hello" in normalized or "hi" in normalized:
            return "Hello! Main yahan hoon."
        if "thanks" in normalized or "shukriya" in normalized:
            return "Aapka swagat hai."
        return "Main offline mode mein hoon. Kripya specific command boliye."


def main() -> None:
    brain = AIBrain()
    brain.start()


if __name__ == "__main__":
    main()
