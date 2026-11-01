import os
import time

from dotenv import load_dotenv
from controllers.device_con.LampManager import LampManager

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))


def main():
    print("=== Тестирование управления лампой (включая цвет) ===")
    try:
        manager = LampManager()
        if "спальня" not in manager.lamps:
            print("[-] Лампа спальни не найдена! Проверьте LAMP_BEDROOM_TOKEN в .env файле.")
            return

        lamp = manager.lamps["спальня"]
        print(f"Подключение к лампе {lamp.ip}...")

        print("\n1. Исходный статус лампы:")
        initial_status = lamp.get_status()
        print(initial_status)

        print("\n2. Проверка включения...")
        res = lamp.turn_on()
        print("Включение:", res)
        time.sleep(1)

        print("\n3. Установка цвета (Красный через RGB)...")
        res = lamp.set_rgb(255, 0, 0)
        print("Красный (RGB 255, 0, 0):", res)
        time.sleep(1)

        print("\n4. Установка цвета (Синий по названию)...")
        res = lamp.set_color("синий")
        print("Синий ('синий'):", res)
        time.sleep(1)

        print("\n5. Установка цвета (Зеленый через HEX)...")
        res = lamp.set_color("#00FF00")
        print("Зеленый ('#00FF00'):", res)
        time.sleep(1)

        print("\n6. Установка цветовой температуры (тёплый свет 3000K)...")
        res = lamp.set_color_temp(3000)
        print("Температура 3000K:", res)
        time.sleep(1)

        print("\n7. Проверка текущего статуса после настройки цвета:")
        status = lamp.get_status()
        print("Текущий статус:", status)

        if initial_status.get("color_temp"):
            lamp.set_color_temp(initial_status["color_temp"])
        if initial_status.get("brightness"):
            lamp.set_brightness(initial_status["brightness"])
        if initial_status.get("power") == "off":
            lamp.turn_off()

        print("\n[+] Все тесты управления цветом успешно пройдены!")
    except Exception as e:
        print(f"[-] Ошибка во время теста: {e}")


if __name__ == "__main__":
    main()