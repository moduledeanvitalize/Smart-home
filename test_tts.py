import os
import wave
import winsound
from piper import PiperVoice

MODEL_PATH = os.path.join(
    os.path.dirname(__file__), "models", "piper", "ru_RU-ruslan-medium.onnx"
)
CONFIG_PATH = MODEL_PATH + ".json"
OUT_WAV = os.path.join(os.path.dirname(__file__), "test_piper.wav")

print("[*] Загрузка нейросети Piper TTS...")
voice = PiperVoice.load(MODEL_PATH, config_path=CONFIG_PATH)

phrase = "Привет! Теперь я говорю полностью локально через нейросеть, без интернета и ошибок сервера."

print(f"[*] Синтезирую: '{phrase}'")
with wave.open(OUT_WAV, "wb") as wav_file:
  if hasattr(voice, "synthesize_wav"):
    voice.synthesize_wav(phrase, wav_file)
  else:
    # Универсальный вариант для любой версии piper
    wav_file.setnchannels(1)
    wav_file.setsampwidth(2)
    wav_file.setframerate(voice.config.sample_rate)
    for chunk in voice.synthesize(phrase):
      wav_file.writeframes(chunk.audio_int16_bytes)

print("[+] Готово! Воспроизвожу...")
winsound.PlaySound(OUT_WAV, winsound.SND_FILENAME)