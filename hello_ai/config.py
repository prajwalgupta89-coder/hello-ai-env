from dataclasses import dataclass


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
    dashboard_open_url: str = "http://127.0.0.1:5000"
    enable_optional_llm: bool = False
