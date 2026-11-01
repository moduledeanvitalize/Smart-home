import ctypes
import os
import time


class PCController:

  def __init__(self):
    self.user32 = ctypes.windll.user32
    # Коды клавиш Windows (Win32 API)
    self.VK_MEDIA_NEXT_TRACK = 0xB0
    self.VK_MEDIA_PREV_TRACK = 0xB1
    self.VK_MEDIA_PLAY_PAUSE = 0xB3
    self.VK_VOLUME_MUTE = 0xAD
    self.VK_VOLUME_DOWN = 0xAE
    self.VK_VOLUME_UP = 0xAF
    self.KEYEVENTF_KEYUP = 0x0002

  def _press_key(self, key_code: int):
    """Эмулирует нажатие и отпускание мультимедийной клавиши."""
    self.user32.keybd_event(key_code, 0, 0, 0)
    time.sleep(0.04)
    self.user32.keybd_event(key_code, 0, self.KEYEVENTF_KEYUP, 0)

  # --- Мультимедиа ---
  def next_track(self) -> dict:
    self._press_key(self.VK_MEDIA_NEXT_TRACK)
    return {"status": "success", "action": "next_track"}

  def prev_track(self) -> dict:
    self._press_key(self.VK_MEDIA_PREV_TRACK)
    return {"status": "success", "action": "prev_track"}

  def play_pause(self) -> dict:
    self._press_key(self.VK_MEDIA_PLAY_PAUSE)
    return {"status": "success", "action": "play_pause"}

  # --- Громкость Windows ---
  def volume_up(self, steps: int = 5) -> dict:
    """Прибавляет громкость (каждый шаг ≈ 2%)."""
    for _ in range(max(1, min(steps, 25))):
      self._press_key(self.VK_VOLUME_UP)
      time.sleep(0.01)
    return {"status": "success", "action": "volume_up"}

  def volume_down(self, steps: int = 5) -> dict:
    """Убавляет громкость."""
    for _ in range(max(1, min(steps, 25))):
      self._press_key(self.VK_VOLUME_DOWN)
      time.sleep(0.01)
    return {"status": "success", "action": "volume_down"}

  def volume_mute(self) -> dict:
    """Включает/выключает звук Windows."""
    self._press_key(self.VK_VOLUME_MUTE)
    return {"status": "success", "action": "volume_mute"}

  # --- Запуск приложений ---
  def open_app(self, app_name: str) -> dict:
    """Запускает частые приложения Windows."""
    app = app_name.strip().lower()
    apps_map = {
        "браузер": "https://ya.ru",
        "хром": "chrome",
        "телеграм": "telegram",
        "тг": "telegram",
        "стим": "steam://open/main",
        "калькулятор": "calc",
        "блокнот": "notepad",
    }
    target = apps_map.get(app, app)
    try:
      os.startfile(target)
      return {"status": "success", "app": app_name}
    except Exception as e:
      return {"status": "error", "message": f"Не удалось открыть {app}: {e}"}