import os
import re
import time
import queue
import ctypes
import tempfile
import asyncio
import winsound
from typing import Optional, Tuple, Callable
from collections import deque
from dotenv import load_dotenv
import numpy as np
import sounddevice as sd
import speech_recognition as sr
import edge_tts

# Загрузка конфигурации из .env
ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(ENV_PATH, override=True)

# Имя ассистента для голосовой активации (настраивается в .env)
ASSISTANT_NAME: str = os.getenv("ASSISTANT_NAME", "ишак").strip().lower()

# Настройки голосового синтеза
VOICE_FEEDBACK: bool = os.getenv("VOICE_FEEDBACK", "true").lower() in ("true", "1", "yes")
VOICE_LANGUAGE: str = os.getenv("VOICE_LANGUAGE", "ru-RU")
VOICE_NAME: str = os.getenv("VOICE_NAME", "ru-RU-DmitryNeural")

# Папка для локальных звуков и кэша
SOUNDS_DIR = os.path.join(os.path.dirname(__file__), "sounds")
os.makedirs(SOUNDS_DIR, exist_ok=True)
SLUSHAYU_AUDIO = os.path.join(SOUNDS_DIR, "slushayu.mp3")


def play_chime():
    """Мгновенный звуковой сигнал активации (без задержки сети)."""
    try:
        winsound.Beep(1200, 60)
        winsound.Beep(1800, 80)
    except Exception:
        pass


def play_done_chime():
    """Мгновенный звуковой сигнал подтверждения выполнения."""
    try:
        winsound.Beep(1600, 50)
    except Exception:
        pass


def play_audio(file_path: str) -> None:
    """Воспроизводит аудиофайл через системный Windows MCI API."""
    try:
        alias = f"sp_{int(time.time() * 1000)}"
        ctypes.windll.winmm.mciSendStringW(f'open "{file_path}" type mpegvideo alias {alias}', None, 0, None)
        ctypes.windll.winmm.mciSendStringW(f"play {alias} wait", None, 0, None)
        ctypes.windll.winmm.mciSendStringW(f"close {alias}", None, 0, None)
    except Exception as e:
        print(f"[!] Ошибка воспроизведения звука: {e}")


def ensure_cached_sounds():
    """Предварительно генерирует аудио для частых ответов, чтобы не зависеть от сети."""
    if not os.path.exists(SLUSHAYU_AUDIO):
        try:
            asyncio.run(edge_tts.Communicate("Слушаю", VOICE_NAME).save(SLUSHAYU_AUDIO))
        except Exception:
            pass


async def _synthesize_edge_tts(text: str, output_path: str, voice: str = VOICE_NAME) -> None:
    communicate = edge_tts.Communicate(text, voice=voice)
    await communicate.save(output_path)


def speak(text: str, voice: str = VOICE_NAME) -> None:
    """
    Озвучивает ответ ассистента с защитой от ошибок edge-tts и нулевой задержкой для частых фраз.
    """
    if not VOICE_FEEDBACK or not text:
        return

    clean = text.strip().lower()

    # Быстрый оффлайн-ответ для "Слушаю"
    if clean in ("слушаю", "слушаю!", "слушаю..."):
        if os.path.exists(SLUSHAYU_AUDIO):
            play_audio(SLUSHAYU_AUDIO)
            return

    # Синтез через edge-tts с защитой от сбоев
    for attempt in range(2):
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                temp_path = f.name

            # Таймаут синтеза 3 секунды для предотвращения зависаний
            asyncio.run(asyncio.wait_for(_synthesize_edge_tts(text, temp_path, voice=voice), timeout=3.0))
            play_audio(temp_path)
            try:
                os.remove(temp_path)
            except OSError:
                pass
            return
        except Exception as e:
            if attempt == 0:
                time.sleep(0.15)
                continue
            print(f"[!] Синтез речи пропущен ({e})")
            play_done_chime()


def extract_command(text: str, name: str = ASSISTANT_NAME) -> Tuple[bool, str]:
    """
    Проверяет обращение к ассистенту по имени с поддержкой фонетических вариаций,
    раздельного написания (Google STT: 'и шаг', 'и шак', 'ешак') и падежей.
    Возвращает: (is_triggered, command_text)
    """
    if not text or not name:
        return False, ""

    clean_text = text.strip()
    clean_name = name.strip().lower()

    # 1. Специфические фонетические вариации для имени "ишак"
    if clean_name == "ишак":
        pattern = re.compile(r"\b(?:и\s*ша[ккг]|еша[ккг]|иша[ккг])[а-яa-z]*\b", re.IGNORECASE)
    # 2. Фонетические вариации для имени "гойда"
    elif clean_name == "гойда":
        pattern = re.compile(r"\b(?:гойд[а-я]*|пойд[а-я]*|когда|года|ой\s*да)\b", re.IGNORECASE)
    # 3. Универсальный шаблон для любого другого имени
    else:
        if clean_name.endswith(("а", "я", "о", "е", "ы", "и", "у")) and len(clean_name) > 3:
            stem = clean_name[:-1]
        else:
            stem = clean_name
        pattern = re.compile(rf"\b{re.escape(stem)}[а-яa-z]*\b", re.IGNORECASE)

    if not pattern.search(clean_text):
        return False, ""

    # Извлечение команды: удаляем найденное имя
    command = pattern.sub("", clean_text)
    command = re.sub(r"^[,\s:!-]+|[,\s:!-]+$", "", command)
    command = re.sub(r"^(?:эй|слушай|привет|пожалуйста)\s+", "", command, flags=re.IGNORECASE)
    command = re.sub(r"\s+", " ", command).strip()

    return True, command


class VoiceListener:
    """
    Высокоскоростной, чувствительный захват речи с микрофона с защитой от
    завышения порогов и программной нормализацией тихого звука.
    """

    def __init__(
        self,
        assistant_name: str = ASSISTANT_NAME,
        sample_rate: int = 16000,
        block_size: int = 800,  # 50 мс
        silence_frames_needed: int = 8,  # 8 блоков * 50мс = 400 мс тишины для завершения фразы
        max_duration: float = 4.5,  # Максимальная длительность команды
        min_speech_duration: float = 0.30,
    ):
        self.assistant_name = assistant_name.strip().lower()
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.silence_frames_needed = silence_frames_needed
        self.max_duration = max_duration
        self.min_speech_duration = min_speech_duration
        self.recognizer = sr.Recognizer()

        # Базовые пороги громкости
        self.ambient_rms = 150.0
        self.speech_start_threshold = 500.0
        self.speech_stop_threshold = 280.0
        self.is_running = False

    def calibrate(self, duration: float = 0.8) -> None:
        """
        Калибрует фоновый шум, находя тихие промежутки между звуками.
        Защищен от случайных звуков и музыки (порог никогда не задерется выше разумного).
        """
        samples_needed = int(self.sample_rate * duration)
        try:
            rec = sd.rec(samples_needed, samplerate=self.sample_rate, channels=1, dtype="int16")
            sd.wait()
            chunks = np.array_split(rec, 10)
            rms_vals = sorted([float(np.sqrt(np.mean(c.astype(np.float32) ** 2))) for c in chunks])

            # Берем тихое значение (2-й с конца), отбрасывая случайные громкие всплески
            quiet_chunk_rms = rms_vals[1] if len(rms_vals) > 1 else rms_vals[0]

            # Ограничиваем шум сверху 350.0, чтобы даже при играющей музыке порог не улетал в космос
            self.ambient_rms = min(350.0, max(80.0, quiet_chunk_rms))
            self.speech_start_threshold = max(450.0, min(850.0, self.ambient_rms * 1.8))
            self.speech_stop_threshold = max(240.0, min(500.0, self.ambient_rms * 1.25))

            print(f"[+] Фон микрофона: {self.ambient_rms:.1f} RMS | Порог старта: {self.speech_start_threshold:.1f} | Порог тишины: {self.speech_stop_threshold:.1f}")
        except Exception as e:
            print(f"[!] Ошибка калибровки: {e}")
            self.speech_start_threshold = 500.0
            self.speech_stop_threshold = 280.0

    def listen_phrase(self) -> Optional[str]:
        """
        Слушает микрофон. Мгновенно начинает запись при появлении голоса
        и останавливает через 400 мс после его окончания.
        """
        pre_buffer: deque = deque(maxlen=6)  # 300 мс пре-буфера для сохранения начала фразы
        recording_chunks = []
        is_speaking = False
        silence_frames = 0
        start_time = 0.0
        smooth_rms = self.ambient_rms

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=self.block_size,
        ) as stream:
            while self.is_running:
                data, _ = stream.read(self.block_size)
                raw_rms = float(np.sqrt(np.mean(data.astype(np.float32) ** 2)))
                smooth_rms = 0.65 * smooth_rms + 0.35 * raw_rms

                if not is_speaking:
                    pre_buffer.append(data.copy())
                    # Плавная адаптация к шуму в тишине с жестким потолком
                    self.ambient_rms = min(350.0, 0.98 * self.ambient_rms + 0.02 * raw_rms)
                    self.speech_start_threshold = max(450.0, min(850.0, self.ambient_rms * 1.8))
                    self.speech_stop_threshold = max(240.0, min(500.0, self.ambient_rms * 1.25))

                    if smooth_rms > self.speech_start_threshold:
                        print("[*] Запись...", end="", flush=True)
                        is_speaking = True
                        start_time = time.time()
                        silence_frames = 0
                        recording_chunks.extend(list(pre_buffer))
                        recording_chunks.append(data.copy())
                else:
                    recording_chunks.append(data.copy())
                    if smooth_rms < self.speech_stop_threshold:
                        silence_frames += 1
                    else:
                        silence_frames = max(0, silence_frames - 1)

                    # Завершение по 400 мс паузы
                    if silence_frames >= self.silence_frames_needed:
                        print(" [пауза, отправка]")
                        break

                    # Жесткий лимит на команду
                    if (time.time() - start_time) > self.max_duration:
                        print(" [таймаут]")
                        break

        if not recording_chunks:
            return None

        audio_array = np.concatenate(recording_chunks, axis=0)
        duration = len(audio_array) / self.sample_rate
        if duration < self.min_speech_duration:
            return None

        # Программное выравнивание громкости для тихих фраз издалека
        max_val = float(np.max(np.abs(audio_array)))
        if 800 <= max_val < 18000:
            scale = min(3.5, 20000.0 / max_val)
            audio_array = np.clip(audio_array.astype(np.float32) * scale, -32768, 32767).astype(np.int16)

        raw_bytes = audio_array.tobytes()
        audio_data = sr.AudioData(raw_bytes, self.sample_rate, 2)

        try:
            text = self.recognizer.recognize_google(audio_data, language=VOICE_LANGUAGE)
            return text.strip()
        except sr.UnknownValueError:
            print("[!] Речь зафиксирована, но слова не распознаны (слишком тихо или искажено).")
            return None
        except Exception as e:
            print(f"[!] Ошибка связи с Google STT: {e}")
            return None

    def run(self, handler_callback: Callable[[str], str]) -> None:
        """Главный цикл голосового ассистента."""
        self.is_running = True
        ensure_cached_sounds()
        self.calibrate(0.8)

        print("\n" + "=" * 55)
        print(f" [ГОЛОСОВОЙ РЕЖИМ АКТИВЕН]")
        print(f" Имя ассистента: '{self.assistant_name}'")
        print(f" Поддерживаются варианты: 'ишак', 'и шаг', 'ешак' и др.")
        print(f" Скажите: '{self.assistant_name.capitalize()}, включи свет' или '{self.assistant_name.capitalize()}, сделай синий'")
        print(" Остановка: нажмите Ctrl+C в консоли.")
        print("=" * 55 + "\n")

        # Приветственный сигнал
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

                print(f"[Google услышал]: \"{recognized_text}\"")

                # Если ассистент уже ответил "Слушаю", принимаем следующую фразу без повтора имени
                if waiting_direct_command and (time.time() <= direct_command_timeout):
                    triggered, command = extract_command(recognized_text, self.assistant_name)
                    if not triggered:
                        command = recognized_text
                    waiting_direct_command = False
                    triggered = True
                else:
                    triggered, command = extract_command(recognized_text, self.assistant_name)

                if not triggered:
                    print(f"[-] Проигнорировано (нет имени '{self.assistant_name}'): \"{recognized_text}\"\n")
                    continue

                print(f"[★] Активация по имени '{self.assistant_name}'!")
                play_chime()

                if not command:
                    # Пользователь назвал только имя
                    print(f"[*] Имя распознано. Ожидание команды...")
                    speak("Слушаю")
                    waiting_direct_command = True
                    direct_command_timeout = time.time() + 5.0
                    continue

                print(f"[*] Команда: \"{command}\"")
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


def test_activation():
    """Тестирование парсинга имени."""
    print(f"Тест детекции имени '{ASSISTANT_NAME}':")
    phrases = [
        f"{ASSISTANT_NAME}, включи свет",
        "и шаг включи свет",
        "и шак сделай красный цвет",
        "ешак выключи музыку",
        f"{ASSISTANT_NAME}",
        "и шаг",
        "какая сейчас погода",
    ]
    for p in phrases:
        trig, cmd = extract_command(p, ASSISTANT_NAME)
        print(f"Фраза: '{p:30}' -> Активация: {str(trig):5} | Команда: '{cmd}'")


if __name__ == "__main__":
    import sys
    if "--test" in sys.argv:
        test_activation()
    else:
        from agent import chat
        listener = VoiceListener(assistant_name=ASSISTANT_NAME)
        listener.run(chat)
