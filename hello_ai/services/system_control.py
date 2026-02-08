import os
import subprocess
from typing import Optional


def open_chrome(url: Optional[str] = None) -> str:
    chrome_paths = [
        os.path.expandvars(r"%ProgramFiles%\\Google\\Chrome\\Application\\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\\Google\\Chrome\\Application\\chrome.exe"),
    ]
    for path in chrome_paths:
        if os.path.exists(path):
            args = [path]
            if url:
                args.append(url)
            subprocess.Popen(args)
            return "Opening Google Chrome."
    if url:
        os.startfile(url)
        return "Opening the website in your default browser."
    return "Chrome is not installed."


def open_notepad() -> str:
    subprocess.Popen(["notepad.exe"])
    return "Opening Notepad."


def open_file(path: str) -> str:
    os.startfile(path)
    return f"Opening {path}."
