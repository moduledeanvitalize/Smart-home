from email.mime import text
import os
import re
import time
import winsound
from collections import deque
from typing import Callable, Optional, Tuple

from dotenv import load_dotenv
import numpy as np
import onnxruntime as ort
from piper import PiperVoice # type: ignore
import sounddevice as sd
import speech_recognition as sr
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume

# Регистрируем пути к CUDA/cuDNN DLL для Windows до вызова Whisper
try:
  import nvidia.cublas.lib
  import nvidia.cudnn.lib

  cublas_p = nvidia.cublas.lib.__path__[0]
  cudnn_p = nvidia.cudnn.lib.__path__[0]
  for p in (cublas_p, cudnn_p):
    if os.path.exists(p):
      os.add_dll_directory(p)
      os.environ["PATH"] = p + os.pathsep + os.environ["PATH"]
except Exception:
  # Если пакеты лежат глубже в site-packages
  try:
    import site

    for sp in site.getsitepackages():
      for sub in ("nvidia/cublas/bin", "nvidia/cudnn/bin"):
        full = os.path.join(sp, sub.replace("/", os.sep))
        if os.path.exists(full):
          os.add_dll_directory(full)
          os.environ["PATH"] = full + os.pathsep + os.environ["PATH"]
  except Exception:
    pass

from faster_whisper import WhisperModel

# Загрузка переменных окружения
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
load_dotenv(ENV_PATH, override=True)

# Загрузка модели faster-whisper
print("[*] Загрузка локального STT (faster-whisper small CUDA)...")
stt_model = WhisperModel("small", device="cuda", compute_type="float16")
print("[+] Модель faster-whisper загружена.")

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

    # 1. Убираем только имя
    command = pattern.sub("", clean_text).strip()

    # 2. Срезаем вводные слова-паразиты, если они шли сразу за именем
    command = re.sub(r"^(?:эй|слушай|привет|пожалуйста)\b[,\s:]*", "", command, flags=re.IGNORECASE)

    # 3. Срезаем ТОЛЬКО ведущие стыковочные знаки (запятая, двоеточие, тире перед началом команды)
    command = re.sub(r"^[,\s:!—-]+", "", command)

    # 4. Проверяем: есть ли в строке реальные слова (буквы или цифры)?
    # Если остались только знаки препинания (вроде "." или "?") — команды НЕТ.
    if not re.search(r"[a-zA-Zа-яА-Я0-9]", command):
        return True, ""

    # Возвращаем команду со всеми вопросительными и восклицательными знаками на конце
    return True, command.strip()

#
# 4. Уменьшение громкости
#
# Список имен процессов, которые считаем музыкой/медиа
TARGET_MUSIC_PROCESSES = [
    "yandexmusic.exe",  # Приложение Яндекс Музыка
    "spotify.exe",  # Spotify
    "chrome.exe",  # Браузеры (если слушаешь через веб)
    "msedge.exe",
    "firefox.exe",
    "yandex.exe",
    "Яндекс Музыка.exe",  # Яндекс Музыка (русская версия)
]

class AudioDucker:
    def __init__(self, target_processes: list = None):
        self.target_processes = [p.lower() for p in (target_processes or TARGET_MUSIC_PROCESSES)]
        self._music_sessions = None
        # Словарь вида {интерфейс_громкости: старая_громкость}
        self._saved_volumes = {}

    def _get_music_processes(self):
        """Ищет процессы, которые считаем музыкой/медиа."""
        sessions = AudioUtilities.GetAllSessions()
        music_sessions = []
        for session in sessions:
            if session.Process and session.Process.name().lower() in self.target_processes:
                music_sessions.append(session)
        return music_sessions

    def duck(self, target_level: float = 0.15):
        """Запоминает громкость, уменьшает до 15% музыку"""
        try:
            if self._music_sessions is None:
                self._music_sessions = self._get_music_processes()
            
            for session in self._music_sessions:
                volume_interface = session._ctl.QueryInterface(ISimpleAudioVolume)
                current_volume = volume_interface.GetMasterVolume()
                self._saved_volumes[volume_interface] = current_volume
                volume_interface.SetMasterVolume(target_level, None)

        except Exception as e:
            print(f"[!] Ошибка Ducking (down): {e}")

    def restore(self):
        """Возвращает исходный уровень громкости"""
        try:
            for volume_interface, saved_volume in self._saved_volumes.items():
                volume_interface.SetMasterVolume(saved_volume, None)
            self._saved_volumes.clear()
            self._music_sessions = None
                
        except Exception as e:
            print(f"мать ебал, не работает изменение звука(up) {e}")

ducker = AudioDucker()

# ==========================================
# 5. ГОЛОСОВОЙ СЛУШАТЕЛЬ (VOICE LISTENER)
# ==========================================
class VoiceListener:
    def __init__(
        self,
        assistant_name: str = ASSISTANT_NAME,
        sample_rate: int = 16000,
        chunk_size: int = 512,
        silence_chunks_needed: int = 25,
        max_duration: float = 50.0,
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

    def listen_phrase(self, timeout: Optional[float] = None) -> Optional[str]:
        pre_buffer: deque = deque(maxlen=10)
        recording_chunks = []
        is_speaking = False
        silence_counter = 0
        start_time = 0.0
        wait_start = time.time()

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
                if timeout is not None and (time.time() - wait_start) > timeout:
                    print(" [таймаут ожидания]")
                    break

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
        

        # Перевод int16 [-32768, 32767] -> float32 [-1.0, 1.0] для Whisper
        audio_float = audio_array.flatten().astype(np.float32) / 32768.0

        try:
            segments, _ = stt_model.transcribe(
                audio_float,
                #language="ru", #test
                beam_size=1,
                best_of=1,
                temperature=0.0,
                condition_on_previous_text=False,
                vad_filter=False,  # у нас уже работает Silero VAD
                # 2. ПОРОГ ТИШИНЫ (отсекает шорохи и тихие звуки от выдумывания фраз):
                no_speech_threshold=0.6,
                log_prob_threshold=-1.0,
                compression_ratio_threshold=2.4,
                initial_prompt=(
                    "Ишак. "
                    "Dota, CS, Steam, YouTube, Discord, Shadowraze, рейз, койл, zxc, лаг, пинг, фпс, хп, мана, ульта, ультимейт, ульт, чмо. "
                    "Telegram, Spotify, Gran Turismo, Skyline, Сидни Кросби, ЦСКА."
                ),
            )
            text = " ".join([s.text for s in segments]).strip()
            return text if text else None
        except Exception as e:
            print(f" [!] Ошибка Whisper STT: {e}")
            return None

        

    def run(self, handler_callback: Callable[[str], str]) -> None:
        self.is_running = True

        print("\n" + "=" * 55)
        print(" [ГОЛОСОВОЙ РЕЖИМ АКТИВЕН]")
        print(f" Имя ассистента: '{self.assistant_name}'")
        print(" Скажи 'Ишак' -> звук стихнет -> отдавай команду.")
        print(" Остановка: Ctrl + C")
        print("=" * 55 + "\n")

        play_chime()
        waiting_direct_command = False

        while self.is_running:
            try:
                # ----------------------------------------------------
                # ШАГ 1: Захват звука с нужным режимом
                # ----------------------------------------------------
                if waiting_direct_command:
                    recognized_text = self.listen_phrase(timeout=5.0)
                else:
                    recognized_text = self.listen_phrase()

                # ----------------------------------------------------
                # ШАГ 2: Обработка тишины (сработал таймаут 5 сек)
                # ----------------------------------------------------
                if not recognized_text:
                    if waiting_direct_command:
                        print("[-] Не дождался команды. Возвращаю громкость.\n")
                        waiting_direct_command = False
                        ducker.restore()
                    continue

                print(f'[Распознано]: "{recognized_text}"')

                # ----------------------------------------------------
                # ШАГ 3: Если мы УЖЕ ждали команду (фаза 2)
                # ----------------------------------------------------
                if waiting_direct_command:
                    waiting_direct_command = False
                    
                    # Проверяем, не повторил ли ты имя случайно
                    triggered, command = extract_command(recognized_text, self.assistant_name)
                    if not triggered:
                        command = recognized_text  # берем всю фразу целиком

                    if command:
                        print(f'[*] Команда: "{command}"')
                        reply = handler_callback(command)
                        print(f"[{self.assistant_name.capitalize()}]: {reply}\n")
                        speak(reply)

                    # Ответ озвучен — возвращаем звук
                    ducker.restore()
                    continue

                # ----------------------------------------------------
                # ШАГ 4: Обычный режим — ждем оклик (фаза 1)
                # ----------------------------------------------------
                triggered, command = extract_command(recognized_text, self.assistant_name)

                if not triggered:
                    print(f"[-] Проигнорировано (нет имени '{self.assistant_name}')\n")
                    continue

                print(f"[★] Активация!")
                
                # МГНОВЕННО глушим музыку
                ducker.duck(0.15)
                play_chime()  # или speak("Шо?")

                # Сценарий А: Сказано только имя ("Ишак")
                if not command:
                    print("[*] Оклик принят. Жду саму команду...")
                    waiting_direct_command = True
                    # continue отправляет цикл на новый круг — прямо в ШАГ 1 с timeout=5.0,
                    # при этом ducker.restore() НЕ вызывается, музыка остается на 15%!
                    continue

                # Сценарий Б: Слитная команда ("Ишак, включи свет в спальне")
                print(f'[*] Слитная команда: "{command}"')
                reply = handler_callback(command)
                print(f"[{self.assistant_name.capitalize()}]: {reply}\n")
                speak(reply)
                ducker.restore()

            except KeyboardInterrupt:
                ducker.restore()
                print("\nОстановка голосового режима...")
                self.is_running = False
                break
            except Exception as e:
                ducker.restore()
                print(f"[!] Ошибка: {e}")
                time.sleep(0.3)


if __name__ == "__main__":
    from agent import chat

    listener = VoiceListener(assistant_name=ASSISTANT_NAME)
    listener.run(chat)
