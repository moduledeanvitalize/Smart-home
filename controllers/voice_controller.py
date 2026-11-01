import io
import os
import re
import time
import wave
import winsound
from collections import deque
from typing import Callable, Optional, Tuple

from dotenv import load_dotenv
import numpy as np
import onnxruntime as ort
from piper import PiperVoice
import sounddevice as sd
import speech_recognition as sr

# Загрузка переменных окружения
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
load_dotenv(ENV_PATH, override=True)

# Конфигурация ассистента
ASSISTANT_NAME: str = os.getenv("ASSISTANT_NAME", "ишак").strip().lower()
VOICE_FEEDBACK: bool = os.getenv("VOICE_FEEDBACK", "true").lower() in ("true", "1", "yes")
VOICE_LANGUAGE: str = os.getenv("VOICE_LANGUAGE", "ru-RU")

# Пути к нейросетевым моделям
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
VAD_MODEL_PATH = os.path.join(BASE_DIR, "models", "silero_vad.onnx")
PIPER_MODEL_PATH = os.path.join(BASE_DIR, "models", "piper", "ru_RU-ruslan-medium.onnx")
PIPER_CONFIG_PATH = PIPER_MODEL_PATH + ".json"


# ==========================================
# 1. ЛОКАЛЬНЫЙ СИНТЕЗ РЕЧИ (PIPER В ОЗУ)
# ==========================================
class MemoryPiperTTS:

  def __init__(
      self,
      model_path: str = PIPER_MODEL_PATH,
      config_path: str = PIPER_CONFIG_PATH,
  ):
    if not os.path.exists(model_path):
      raise FileNotFoundError(f"Файл модели Piper не найден: {model_path}")
    print("[*] Загрузка локального голоса (Piper: Руслан)...")
    self.voice = PiperVoice.load(model_path, config_path=config_path)
    self.sample_rate = self.voice.config.sample_rate

  def speak(self, text: str):
    clean_text = text.strip()
    if not clean_text:
      return

    # Собираем сырые сэмплы инференса сразу в память
    audio_chunks = []
    for chunk in self.voice.synthesize(clean_text):
      audio_chunks.append(chunk.audio_int16_bytes)

    if not audio_chunks:
      return

    raw_data = b"".join(audio_chunks)
    audio_np = np.frombuffer(raw_data, dtype=np.int16)

    # Мгновенный вывод в динамики
    sd.play(audio_np, samplerate=self.sample_rate)
    sd.wait()

tts_engine = MemoryPiperTTS()


def play_chime():
    """Сигнал детекции имени."""
    try:
        winsound.Beep(1200, 60)
        winsound.Beep(1800, 80)
    except Exception:
        pass


def play_done_chime():
    """Сигнал завершения/ошибки."""
    try:
        winsound.Beep(1600, 50)
    except Exception:
        pass


def speak(text: str, **kwargs) -> None:
    """Универсальная функция голосового вывода."""
    if not VOICE_FEEDBACK or not text:
        return
    try:
        tts_engine.speak(text)
    except Exception as e:
        print(f"[!] Ошибка синтеза Piper: {e}")
        play_done_chime()


# ==========================================
# 2. ДЕТЕКТОР РЕЧИ (SILERO VAD v5)
# ==========================================
class SileroVAD:
    def __init__(self, model_path: str = VAD_MODEL_PATH):
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Файл Silero VAD не найден: {model_path}")

        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        self.session = ort.InferenceSession(model_path, sess_options=opts)
        self.sample_rate = 16000
        self.context_size = 64
        self.reset_states()

    def reset_states(self):
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, self.context_size), dtype=np.float32)

    def is_speech(self, audio_chunk: np.ndarray, threshold: float = 0.42) -> Tuple[bool, float]:
        if audio_chunk.dtype == np.int16:
            audio_data = audio_chunk.astype(np.float32) / 32768.0
        else:
            audio_data = audio_chunk.astype(np.float32)

        if audio_data.ndim == 1:
            audio_data = np.expand_dims(audio_data, axis=0)

        # Контекстное окно 64 сэмпла для Silero v5 (512 + 64 = 576)
        full_input = np.concatenate([self._context, audio_data], axis=1)
        self._context = full_input[:, -self.context_size:]

        inputs = {
            "input": full_input,
            "state": self._state,
            "sr": np.array(self.sample_rate, dtype=np.int64),
        }

        outputs = self.session.run(None, inputs)

        prob = 0.0
        for item in outputs:
            if item.size > 1:
                self._state = item
            else:
                prob = float(np.squeeze(item))

        return prob >= threshold, prob


# ==========================================
# 3. ИЗВЛЕЧЕНИЕ ИМЕНИ И КОМАНДЫ
# ==========================================
def extract_command(text: str, name: str = ASSISTANT_NAME) -> Tuple[bool, str]:
    if not text or not name:
        return False, ""

    clean_text = text.strip()
    clean_name = name.strip().lower()

    if clean_name == "ишак":
        pattern = re.compile(r"\b(?:и\s*ша[ккг]|еша[ккг]|иша[ккг])[а-яa-z]*\b", re.IGNORECASE)
    else:
        stem = clean_name[:-1] if clean_name.endswith(("а", "я", "о", "е", "ы", "и", "у")) and len(clean_name) > 3 else clean_name
        pattern = re.compile(rf"\b{re.escape(stem)}[а-яa-z]*\b", re.IGNORECASE)

    if not pattern.search(clean_text):
        return False, ""

    command = pattern.sub("", clean_text)
    command = re.sub(r"^[,\s:!-]+|[,\s:!-]+$", "", command)
    command = re.sub(r"^(?:эй|слушай|привет|пожалуйста)\s+", "", command, flags=re.IGNORECASE)
    return True, re.sub(r"\s+", " ", command).strip()


# ==========================================
# 4. ГОЛОСОВОЙ СЛУШАТЕЛЬ (VOICE LISTENER)
# ==========================================
class VoiceListener:
    def __init__(
        self,
        assistant_name: str = ASSISTANT_NAME,
        sample_rate: int = 16000,
        chunk_size: int = 512,
        silence_chunks_needed: int = 25,
        max_duration: float = 15.0,
        min_speech_duration: float = 0.35,
    ):
        self.assistant_name = assistant_name.strip().lower()
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.silence_chunks_needed = silence_chunks_needed
        self.max_duration = max_duration
        self.min_speech_duration = min_speech_duration

        self.vad = SileroVAD()
        self.recognizer = sr.Recognizer()
        self.is_running = False

    def listen_phrase(self) -> Optional[str]:
        pre_buffer: deque = deque(maxlen=10)
        recording_chunks = []
        is_speaking = False
        silence_counter = 0
        start_time = 0.0

        self.vad.reset_states()

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=self.chunk_size,
        ) as stream:
            while self.is_running:
                audio_chunk, _ = stream.read(self.chunk_size)
                audio_flat = audio_chunk.flatten()

                speech_now, prob = self.vad.is_speech(audio_flat, threshold=0.42)

                if not is_speaking:
                    pre_buffer.append(audio_chunk.copy())
                    if speech_now:
                        is_speaking = True
                        start_time = time.time()
                        silence_counter = 0
                        recording_chunks.extend(list(pre_buffer))
                        recording_chunks.append(audio_chunk.copy())
                        print("[*] Запись...", end="", flush=True)
                else:
                    recording_chunks.append(audio_chunk.copy())

                    if not speech_now:
                        silence_counter += 1
                    else:
                        silence_counter = max(0, silence_counter - 1)

                    if silence_counter >= self.silence_chunks_needed:
                        print(" [пауза, отправка]")
                        break

                    if (time.time() - start_time) > self.max_duration:
                        print(" [таймаут]")
                        break

        if not recording_chunks:
            return None

        audio_array = np.concatenate(recording_chunks, axis=0)
        duration = len(audio_array) / self.sample_rate
        if duration < self.min_speech_duration:
            return None

        # Программное усиление тихого звука с дивана
        max_val = float(np.max(np.abs(audio_array)))
        if 500 <= max_val < 18000:
            scale = min(3.5, 20000.0 / max_val)
            audio_array = np.clip(audio_array.astype(np.float32) * scale, -32768, 32767).astype(np.int16)

        raw_bytes = audio_array.tobytes()
        audio_data = sr.AudioData(raw_bytes, self.sample_rate, 2)

        try:
            text = self.recognizer.recognize_google(audio_data, language=VOICE_LANGUAGE)
            return text.strip()
        except sr.UnknownValueError:
            print(" [!] Слова не распознаны.")
            return None
        except Exception as e:
            print(f" [!] Ошибка STT: {e}")
            return None

    def run(self, handler_callback: Callable[[str], str]) -> None:
        self.is_running = True

        print("\n" + "=" * 55)
        print(" [ГОЛОСОВОЙ РЕЖИМ: Silero VAD v5 + Piper TTS (Руслан)]")
        print(f" Имя ассистента: '{self.assistant_name}'")
        print(f" Скажите: '{self.assistant_name.capitalize()}, включи свет'")
        print(" Остановка: Ctrl + C")
        print("=" * 55 + "\n")

        play_chime()

        waiting_direct_command = False
        direct_command_timeout = 0.0

        while self.is_running:
            try:
                recognized_text = self.listen_phrase()
                if not recognized_text:
                    if waiting_direct_command and time.time() > direct_command_timeout:
                        waiting_direct_command = False
                    continue

                print(f'[Распознано]: "{recognized_text}"')

                if waiting_direct_command and (time.time() <= direct_command_timeout):
                    triggered, command = extract_command(recognized_text, self.assistant_name)
                    if not triggered:
                        command = recognized_text
                    waiting_direct_command = False
                    triggered = True
                else:
                    triggered, command = extract_command(recognized_text, self.assistant_name)

                if not triggered:
                    print(f"[-] Проигнорировано (нет имени '{self.assistant_name}')\n")
                    continue

                print(f"[★] Активация!")
                play_chime()

                if not command:
                    print("[*] Ожидание команды...")
                    speak("Слушаю")
                    waiting_direct_command = True
                    direct_command_timeout = time.time() + 5.0
                    continue

                print(f'[*] Команда: "{command}"')
                reply = handler_callback(command)
                print(f"[{self.assistant_name.capitalize()}]: {reply}\n")
                speak(reply)

            except KeyboardInterrupt:
                print("\nОстановка голосового режима...")
                self.is_running = False
                break
            except Exception as e:
                print(f"[!] Ошибка: {e}")
                time.sleep(0.3)


if __name__ == "__main__":
    from agent import chat

    listener = VoiceListener(assistant_name=ASSISTANT_NAME)
    listener.run(chat)