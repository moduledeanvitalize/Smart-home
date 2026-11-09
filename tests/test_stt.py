import time
from faster_whisper import WhisperModel
import sounddevice as sd
import os

# Подключение CUDA DLL из установленных pip-пакетов NVIDIA
try:
  import nvidia.cublas.lib
  import nvidia.cudnn.lib

  # Получаем реальные пути к папкам с библиотеками
  cublas_dir = nvidia.cublas.lib.__path__[0]
  cudnn_dir = nvidia.cudnn.lib.__path__[0]

  for p in (cublas_dir, cudnn_dir):
    if os.path.exists(p):
      os.add_dll_directory(p)
      os.environ["PATH"] = p + os.pathsep + os.environ["PATH"]

  print("[+] Библиотеки CUDA успешно подключены.")
except Exception as e:
  # Если пакетов нет или что-то пошло не так — пробуем через site-packages напрямую
  try:
    import site

    for sp in site.getsitepackages():
      for n_pkg in ("nvidia/cublas/bin", "nvidia/cudnn/bin"):
        full_p = os.path.join(sp, n_pkg.replace("/", os.sep))
        if os.path.exists(full_p):
          os.add_dll_directory(full_p)
          os.environ["PATH"] = full_p + os.pathsep + os.environ["PATH"]
    print("[+] Библиотеки CUDA подключены через site-packages.")
  except Exception as err:
    print(f"[!] Не удалось подключить CUDA: {err}")

from faster_whisper import WhisperModel

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
SAMPLE_RATE = 16000
DURATION = 3  # секунды записи для теста

print("[*] Загрузка модели faster-whisper (small, CPU int8)...")
t0 = time.time()

model = WhisperModel("small", device="cuda", compute_type="float16")
print(f"[+] Модель загружена за {time.time() - t0:.2f} сек.")

print(
    f"\n[*] Скажи что-нибудь в микрофон (запись {DURATION} сек. пошла)...",
    flush=True,
)
audio = sd.rec(
    int(DURATION * SAMPLE_RATE),
    samplerate=SAMPLE_RATE,
    channels=1,
    dtype="float32",
)
sd.wait()
audio_flat = audio.flatten()

print("[*] Распознаю...")
t_start = time.time()

# beam_size=1 дает максимальную скорость для коротких команд
# initial_prompt задает контекст, чтобы модель знала имя ассистента
segments, info = model.transcribe(
    audio_flat,
    language="ru",
    beam_size=2,  # Оптимально: проверяет альтернативы, точность растет в 2 раза, время почти то же
    best_of=2,
    temperature=0.0,  # Отключает случайные галлюцинации
    condition_on_previous_text=False,  # Запрещает зацикливаться на предыдущих фразах
    vad_filter=False,  # В боевом коде у нас VAD уже отрезал всё лишнее
    initial_prompt="Ишак, включи свет, выключи музыку, сделай громче, открой браузер, блядь, хуй, писюн.",
)
text = " ".join([seg.text for seg in segments]).strip()
elapsed = time.time() - t_start

print(f"\n[Распознано за {elapsed:.2f} сек]: «{text}»")