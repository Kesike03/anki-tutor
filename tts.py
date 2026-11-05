"""Local, dependency-free text-to-speech using QtTextToSpeech."""

from __future__ import annotations

import re

from aqt.qt import QObject, pyqtSignal


MAX_TTS_CHARS = 12000


def prepare_text(text: str, skip_code: bool = True, skip_math: bool = True) -> str:
    """Turn Markdown/HTML-rich assistant text into speakable plain text."""
    value = str(text or "")
    if skip_code:
        value = re.sub(r"```.*?```", " ", value, flags=re.DOTALL)
        value = re.sub(r"~~~.*?~~~", " ", value, flags=re.DOTALL)
    else:
        value = re.sub(r"^\s*```[^\n]*$", "", value, flags=re.MULTILINE)
        value = re.sub(r"^\s*~~~[^\n]*$", "", value, flags=re.MULTILINE)
    value = re.sub(r"`([^`]*)`", r"\1", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"\1", value)
    value = re.sub(r"__([^_]+)__", r"\1", value)
    value = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", value)
    value = re.sub(r"(?<!_)_([^_]+)_(?!_)", r"\1", value)
    value = re.sub(r"~~([^~]+)~~", r"\1", value)
    value = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    if skip_math:
        value = re.sub(
            r"\\\[.*?\\\]|\\\(.*?\\\)|\$\$.*?\$\$|\$[^$]+\$",
            " formula ",
            value,
            flags=re.DOTALL,
        )
    else:
        value = re.sub(r"\\\[|\\\]|\\\(|\\\)", " ", value)
        value = value.replace("$$", " ").replace("$", " ")
    value = re.sub(r"^\s{0,3}#{1,6}\s*", "", value, flags=re.MULTILINE)
    value = re.sub(r"^\s{0,3}>\s?", "", value, flags=re.MULTILINE)
    value = re.sub(r"^\s{0,3}[-*+]\s+", "", value, flags=re.MULTILINE)
    value = re.sub(r"https?://\S+", " ", value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = value.replace("|", " ")
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) > MAX_TTS_CHARS:
        value = value[:MAX_TTS_CHARS].rstrip() + " ..."
    return value


class TTSController(QObject):
    """One reusable Qt speech engine for the whole tutor panel."""

    state_changed = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.available = False
        self._engine = None
        self._state = None
        self._speaking = False
        self._current_id: int | None = None
        self._skip_code = True
        self._skip_math = True
        try:
            from PyQt6.QtTextToSpeech import QTextToSpeech
        except Exception:
            return
        self._state = QTextToSpeech.State
        engines = []
        try:
            engines = list(QTextToSpeech.availableEngines())
        except Exception:
            pass
        order = [name for name in ("winrt", "sapi") if name in engines]
        order += [name for name in engines if name not in order and name != "mock"]
        for name in order or [None]:
            try:
                candidate = QTextToSpeech(name, self) if name else QTextToSpeech(self)
                voices = candidate.availableVoices()
            except Exception:
                continue
            if not voices:
                candidate.deleteLater()
                continue
            self._engine = candidate
            self.available = True
            break
        if self._engine is None:
            return
        self._engine.stateChanged.connect(self._on_state)
        if hasattr(self._engine, "errorOccurred"):
            self._engine.errorOccurred.connect(self._on_error)

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    @property
    def current_message_id(self) -> int | None:
        return self._current_id

    def voices(self) -> list[tuple[str, str]]:
        if not self.available:
            return []
        result = []
        try:
            for voice in self._engine.availableVoices():
                try:
                    locale = voice.locale().name()
                except Exception:
                    locale = ""
                result.append((voice.name(), locale))
        except Exception:
            return []
        return result

    def configure(
        self, voice: str = "", rate: float = 0.0, volume: float = 0.8,
        skip_code: bool = True, skip_math: bool = True,
    ) -> None:
        self._skip_code = bool(skip_code)
        self._skip_math = bool(skip_math)
        if not self.available:
            return
        try:
            self._engine.setRate(max(-1.0, min(1.0, float(rate))))
            self._engine.setVolume(max(0.0, min(1.0, float(volume))))
        except (TypeError, ValueError, RuntimeError):
            pass
        if voice:
            try:
                for candidate in self._engine.availableVoices():
                    if candidate.name() == voice:
                        self._engine.setVoice(candidate)
                        break
            except Exception:
                pass

    def speak(self, text: str, message_id: int | None = None) -> bool:
        if not self.available:
            return False
        value = prepare_text(text, self._skip_code, self._skip_math)
        if not value:
            return False
        self.stop()
        self._current_id = message_id
        try:
            self._engine.say(value)
            return True
        except Exception as error:
            self._current_id = None
            self._speaking = False
            self.error.emit(str(error))
            return False

    def stop(self) -> None:
        if self._engine is not None:
            try:
                self._engine.stop()
            except Exception:
                pass
        self._speaking = False
        self._current_id = None
        self.state_changed.emit("stopped")

    def _on_state(self, state) -> None:
        name = getattr(state, "name", str(state)).lower()
        if name == "speaking":
            self._speaking = True
        elif name in ("ready", "error"):
            self._speaking = False
            self._current_id = None
        self.state_changed.emit(name)

    def _on_error(self, *args) -> None:
        message = str(args[-1]) if args else "Text-to-speech failed"
        self._speaking = False
        self._current_id = None
        self.state_changed.emit("error")
        self.error.emit(message)
