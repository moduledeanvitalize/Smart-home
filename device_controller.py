import os
import re
from typing import Dict, Any, Optional, Tuple, Union
from dotenv import load_dotenv
from miio import Device
from miio.exceptions import DeviceException

# Загружаем переменные окружения из .env в текущей директории
ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(ENV_PATH)

# Предустановленные именованные цвета
PRESET_COLORS: Dict[str, Tuple[int, int, int]] = {
    # Русские названия
    "красный": (255, 0, 0),
    "зеленый": (0, 255, 0),
    "зелёный": (0, 255, 0),
    "синий": (0, 0, 255),
    "желтый": (255, 255, 0),
    "жёлтый": (255, 255, 0),
    "голубой": (0, 191, 255),
    "бирюзовый": (64, 224, 208),
    "фиолетовый": (128, 0, 128),
    "сиреневый": (200, 162, 200),
    "пурпурный": (255, 0, 255),
    "розовый": (255, 105, 180),
    "оранжевый": (255, 165, 0),
    "белый": (255, 255, 255),
    "теплый белый": (255, 214, 170),
    "тёплый белый": (255, 214, 170),
    "холодный белый": (200, 220, 255),
    # Английские названия
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "cyan": (0, 255, 255),
    "magenta": (255, 0, 255),
    "purple": (128, 0, 128),
    "orange": (255, 165, 0),
    "pink": (255, 192, 203),
    "white": (255, 255, 255),
}

class LampController:
    """Контроллер управления лампой Xiaomi/Yeelight по протоколу MiIO."""

    def __init__(self, ip: Optional[str] = None, token: Optional[str] = None):
        self.ip = ip or os.getenv("LAMP_IP")
        self.token = token or os.getenv("LAMP_TOKEN")

        if not self.ip:
            raise ValueError("IP-адрес лампы не указан (задайте LAMP_IP в .env).")
        if not self.token or self.token == "ваш_32_значный_токен_шифрования":
            raise ValueError("Токен лампы не настроен. Запустите token_extractor.py для получения токена.")

        self.device = Device(ip=self.ip, token=self.token)

    def turn_on(self) -> Dict[str, Any]:
        """Включает питание лампы."""
        try:
            res = self.device.send("set_power", ["on"])
            return {"status": "success", "power": "on", "response": res}
        except DeviceException as e:
            return {"status": "error", "message": f"Ошибка MiIO: {e}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def turn_off(self) -> Dict[str, Any]:
        """Выключает питание лампы."""
        try:
            res = self.device.send("set_power", ["off"])
            return {"status": "success", "power": "off", "response": res}
        except DeviceException as e:
            return {"status": "error", "message": f"Ошибка MiIO: {e}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def toggle(self) -> Dict[str, Any]:
        """Переключает состояние питания лампы."""
        try:
            res = self.device.send("toggle", [])
            return {"status": "success", "action": "toggle", "response": res}
        except DeviceException:
            # Если метод toggle не поддерживается прошивкой, проверяем текущее состояние
            status = self.get_status()
            if status.get("status") == "success":
                current_power = status.get("power")
                if current_power == "on":
                    return self.turn_off()
                else:
                    return self.turn_on()
            return {"status": "error", "message": "Не удалось переключить питание"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def set_brightness(self, level: int) -> Dict[str, Any]:
        """
        Устанавливает яркость лампы.
        :param level: Процент яркости от 1 до 100.
        """
        try:
            level = max(1, min(100, int(level)))
            res = self.device.send("set_bright", [level])
            return {"status": "success", "brightness": level, "response": res}
        except DeviceException as e:
            return {"status": "error", "message": f"Ошибка MiIO: {e}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def set_rgb(self, red: int, green: int, blue: int) -> Dict[str, Any]:
        """
        Устанавливает цвет лампы в формате RGB.
        :param red: Красный компонент от 0 до 255.
        :param green: Зеленый компонент от 0 до 255.
        :param blue: Синий компонент от 0 до 255.
        """
        try:
            r = max(0, min(255, int(red)))
            g = max(0, min(255, int(green)))
            b = max(0, min(255, int(blue)))
            rgb_int = (r << 16) + (g << 8) + b
            res = self.device.send("set_rgb", [rgb_int])
            return {"status": "success", "rgb": [r, g, b], "rgb_int": rgb_int, "response": res}
        except DeviceException as e:
            return {"status": "error", "message": f"Ошибка MiIO: {e}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def set_color_temp(self, kelvin: int) -> Dict[str, Any]:
        """
        Устанавливает цветовую температуру белого света (в Кельвинах).
        :param kelvin: Температура от 1700K (тёплый) до 6500K (холодный).
        """
        try:
            k = max(1700, min(6500, int(kelvin)))
            res = self.device.send("set_ct_abx", [k, "smooth", 500])
            return {"status": "success", "color_temp": k, "response": res}
        except DeviceException as e:
            return {"status": "error", "message": f"Ошибка MiIO: {e}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def set_color(self, color: Union[str, Tuple[int, int, int], list]) -> Dict[str, Any]:
        """
        Универсальный метод установки цвета по названию, HEX-коду или кортежу/списку RGB.
        Примеры:
            lamp.set_color("красный")
            lamp.set_color("#00FF00")
            lamp.set_color((0, 0, 255))
        """
        if isinstance(color, (tuple, list)) and len(color) == 3:
            return self.set_rgb(int(color[0]), int(color[1]), int(color[2]))

        if isinstance(color, str):
            clean = color.strip().lower()
            if clean in PRESET_COLORS:
                r, g, b = PRESET_COLORS[clean]
                return self.set_rgb(r, g, b)

            # Проверка HEX (#RRGGBB или RRGGBB)
            hex_match = re.match(r"^#?([0-9a-f]{6})$", clean)
            if hex_match:
                hex_val = hex_match.group(1)
                r = int(hex_val[0:2], 16)
                g = int(hex_val[2:4], 16)
                b = int(hex_val[4:6], 16)
                return self.set_rgb(r, g, b)

            return {
                "status": "error",
                "message": f"Неизвестный цвет '{color}'. Доступные названия: {', '.join(list(PRESET_COLORS.keys())[:10])}...",
            }

        return {"status": "error", "message": f"Неверный формат цвета: {color}"}

    def get_status(self) -> Dict[str, Any]:
        """Запрашивает состояние питания, текущей яркости и цвета."""
        try:
            # Стандартные свойства для ламп Xiaomi/Yeelight
            res = self.device.send("get_prop", ["power", "bright", "rgb", "ct", "color_mode"])
            if isinstance(res, list) and len(res) >= 2:
                status_dict: Dict[str, Any] = {
                    "status": "success",
                    "power": res[0],
                    "brightness": int(res[1]) if str(res[1]).isdigit() else res[1],
                }
                if len(res) >= 3 and res[2] is not None and str(res[2]).isdigit():
                    rgb_val = int(res[2])
                    status_dict["rgb"] = [
                        (rgb_val >> 16) & 0xFF,
                        (rgb_val >> 8) & 0xFF,
                        rgb_val & 0xFF,
                    ]
                    status_dict["rgb_int"] = rgb_val
                if len(res) >= 4 and res[3] is not None and str(res[3]).isdigit():
                    status_dict["color_temp"] = int(res[3])
                if len(res) >= 5 and res[4] is not None and str(res[4]).isdigit():
                    mode = int(res[4])
                    mode_names = {1: "rgb", 2: "color_temp", 3: "hsv"}
                    status_dict["color_mode"] = mode_names.get(mode, str(mode))
                return status_dict

            return {"status": "success", "raw": res}
        except DeviceException:
            # Резервный запрос базовых свойств, если расширенные не поддерживаются
            try:
                res = self.device.send("get_prop", ["power", "bright"])
                if isinstance(res, list) and len(res) >= 2:
                    return {"status": "success", "power": res[0], "brightness": res[1]}
                return {"status": "success", "raw": res}
            except DeviceException as e:
                return {"status": "error", "message": f"Ошибка MiIO: {e}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    print("Проверка модуля LampController...")
    try:
        lamp = LampController()
        print(f"Подключение к лампе {lamp.ip}...")
        status = lamp.get_status()
        print("Статус лампы:", status)
    except Exception as err:
        print("Ошибка при инициализации лампы:", err)
