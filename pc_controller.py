import ctypes
import sys
from typing import Dict, Any

# Виртуальные клавиши мультимедиа в Windows
VK_MEDIA_NEXT_TRACK = 0xB0  # Следующий трек
VK_MEDIA_PREV_TRACK = 0xB1  # Предыдущий трек
VK_MEDIA_PLAY_PAUSE = 0xB3  # Плей / Пауза
KEYEVENTF_KEYUP = 0x0002

class PCController:
    """Управление мультимедиа на компьютере через стандартные медиа-клавиши."""

    @staticmethod
    def _send_key(vk_code: int):
        if sys.platform == "win32":
            ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
            ctypes.windll.user32.keybd_event(vk_code, 0, KEYEVENTF_KEYUP, 0)
        else:
            # Заглушка для Linux при необходимости
            pass

    def next_track(self) -> Dict[str, Any]:
        """Переключает на следующий трек."""
        self._send_key(VK_MEDIA_NEXT_TRACK)
        return {"status": "success", "action": "next_track"}

    def prev_track(self) -> Dict[str, Any]:
        """Переключает на предыдущий трек."""
        self._send_key(VK_MEDIA_PREV_TRACK)
        return {"status": "success", "action": "prev_track"}

    def play_pause(self) -> Dict[str, Any]:
        """Ставит на паузу или возобновляет воспроизведение."""
        self._send_key(VK_MEDIA_PLAY_PAUSE)
        return {"status": "success", "action": "play_pause"}

if __name__ == "__main__":
    pc = PCController()
    print("Тест мультимедиа контроллера...")
    print("Результат next_track:", pc.next_track())
