import os
import re
from typing import Dict, Any, Optional, Tuple, Union, List
from dotenv import load_dotenv
from miio import Device
from miio import Discovery
from miio.exceptions import DeviceException
from typing import Optional

from controllers.resolver import resolve_all_ips

ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(ENV_PATH, override=True)

PRESET_COLORS: Dict[str, Tuple[int, int, int]] = {
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
}

ROOM_ALIASES = {
    "спальня":  ["спальня",  "спальне",   "спальню", "комната",   "комнате", "комнату", "bedroom"],
    "кухня":    ["кухня",    "кухне",     "кухню",   "kitchen"],
    "прихожая": ["прихожая", "прихожей", "прихожую", "коридор",   "коридоре", "hallway"],
    "ванная":   ["ванная",   "ванной",    "ванную",  "туалет",    "санузел", "bathroom"],
    "все":      ["все"  ,    "всё",       "везде",   "все лампы", "весь свет", "all"],
}


class SingleLamp:
    """Управление одной конкретной лампой."""

    def __init__(self, name: str, mac: str, token: str, ip: Optional[str] = None, has_color: bool = False):
        self.name = name
        self.mac = mac
        self.token = token
        self.ip = ip
        self.has_color = has_color

        # Если IP уже известен при запуске — сразу цепляем Device, иначе пока None
        self.device = Device(ip=self.ip, token=self.token) if self.ip else None

    def _try_reconnect(self) -> bool:
        """Пытается переподключиться к лампе, если она ожила после выключателя."""
        if not self.mac:
            return False

        found_ips = resolve_all_ips([self.mac])
        new_ip = found_ips.get(self.mac)
        if new_ip:
            self.ip = new_ip
            self.device = Device(ip=self.ip, token=self.token)
            print(f"[+] Лампа '{self.name}' снова доступна на {self.ip}")
            return True
        return False

    def _safe_send(self, command: str, params: list) -> Tuple[bool, Any]:
        """Единая точка отправки команд с перехватом таймаутов."""
        if not self.device:
            if not self._try_reconnect():
                return False, "offline"

        try:
            res = self.device.send(command, params)
            return True, res
        except DeviceException:
            # Лампа обесточена клавишей на стене
            self.device = None
            return False, "offline"
        except Exception as e:
            return False, str(e)

    def _ensure_power_on(self):
        """Гарантирует включение питания перед сменой яркости, цвета или температуры."""
        self._safe_send("set_power", ["on"])

    def turn_on(self) -> Dict[str, Any]:
        ok, res = self._safe_send("set_power", ["on"])
        if not ok and res == "offline":
            return {"status": "offline", "message": f"Лампа '{self.name}' обесточена на выключателе."}
        if not ok:
            return {"status": "error", "message": res}
        return {"status": "success", "power": "on", "response": res}

    def turn_off(self) -> Dict[str, Any]:
        ok, res = self._safe_send("set_power", ["off"])
        if not ok and res == "offline":
            return {"status": "offline", "message": f"Лампа '{self.name}' обесточена на выключателе."}
        if not ok:
            return {"status": "error", "message": res}
        return {"status": "success", "power": "off", "response": res}

    def toggle(self) -> Dict[str, Any]:
        ok, res = self._safe_send("toggle", [])
        if ok:
            return {"status": "success", "action": "toggle", "response": res}
        if res == "offline":
            return {"status": "offline", "message": f"Лампа '{self.name}' обесточена на выключателе."}

        # Фолбэк через проверку текущего статуса
        status = self.get_status()
        if status.get("status") == "success":
            return self.turn_off() if status.get("power") == "on" else self.turn_on()
        return {"status": "error", "message": "Не удалось переключить питание"}

    def set_brightness(self, level: int) -> Dict[str, Any]:
        self._ensure_power_on()
        level = max(1, min(100, int(level)))
        ok, res = self._safe_send("set_bright", [level])
        if not ok and res == "offline":
            return {"status": "offline", "message": f"Лампа '{self.name}' обесточена на выключателе."}
        if not ok:
            return {"status": "error", "message": res}
        return {"status": "success", "brightness": level, "response": res}

    def set_rgb(self, red: int, green: int, blue: int) -> Dict[str, Any]:
        if not self.has_color:
            return {"status": "error", "message": f"Лампа '{self.name}' не поддерживает цвет."}
        self._ensure_power_on()
        r, g, b = max(0, min(255, int(red))), max(0, min(255, int(green))), max(0, min(255, int(blue)))
        rgb_int = (r << 16) + (g << 8) + b
        ok, res = self._safe_send("set_rgb", [rgb_int])
        if not ok and res == "offline":
            return {"status": "offline", "message": f"Лампа '{self.name}' обесточена на выключателе."}
        if not ok:
            return {"status": "error", "message": res}
        return {"status": "success", "rgb": [r, g, b], "response": res}

    def set_color_temp(self, kelvin: int) -> Dict[str, Any]:
        if not self.has_color:
            return {"status": "error", "message": f"Лампа в '{self.name}' не поддерживает цветовую температуру."}
        self._ensure_power_on()
        k = max(1700, min(6500, int(kelvin)))
        ok, res = self._safe_send("set_ct_abx", [k, "smooth", 500])
        if not ok and res == "offline":
            return {"status": "offline", "message": f"Лампа '{self.name}' обесточена на выключателе."}
        if not ok:
            return {"status": "error", "message": res}
        return {"status": "success", "color_temp": k, "response": res}

    def set_color(self, color: Union[str, Tuple[int, int, int], list]) -> Dict[str, Any]:
        if not self.has_color:
            return {"status": "error", "message": f"Лампа в '{self.name}' монохромная, цвет менять нельзя."}

        if isinstance(color, (tuple, list)) and len(color) == 3:
            return self.set_rgb(int(color[0]), int(color[1]), int(color[2]))

        if isinstance(color, str):
            clean = color.strip().lower().replace("ё", "е")
            if clean in PRESET_COLORS:
                return self.set_rgb(*PRESET_COLORS[clean])
            hex_match = re.match(r"^#?([0-9a-f]{6})$", clean)
            if hex_match:
                val = hex_match.group(1)
                return self.set_rgb(int(val[0:2], 16), int(val[2:4], 16), int(val[4:6], 16))
        return {"status": "error", "message": f"Неизвестный цвет: {color}"}

    def get_status(self) -> Dict[str, Any]:
        props = ["power", "bright"]
        if self.has_color:
            props.extend(["rgb", "ct", "color_mode"])

        ok, res = self._safe_send("get_prop", props)
        if not ok and res == "offline":
            return {"status": "offline", "message": f"Лампа '{self.name}' обесточена на выключателе."}
        if not ok:
            return {"status": "error", "message": res}

        if isinstance(res, list) and len(res) >= 2:
            status = {"status": "success", "power": res[0], "brightness": res[1]}
            if self.has_color and len(res) >= 3 and res[2]:
                rgb_val = int(res[2])
                status["rgb"] = [(rgb_val >> 16) & 0xFF, (rgb_val >> 8) & 0xFF, rgb_val & 0xFF]
            return status
        return {"status": "success", "raw": res}


class LampManager:
    """Менеджер для управления группой ламп по комнатам."""

    def __init__(self):
        self.lamps: Dict[str, SingleLamp] = {}

        # Инициализация ламп из .env
        configs = [
            ("спальня", os.getenv("LAMP_BEDROOM_MAC"), os.getenv("LAMP_BEDROOM_TOKEN"), True),
            ("кухня", os.getenv("LAMP_KITCHEN_MAC"), os.getenv("LAMP_KITCHEN_TOKEN"), False),
            ("прихожая", os.getenv("LAMP_HALLWAY_MAC"), os.getenv("LAMP_HALLWAY_TOKEN"), False),
            ("ванная", os.getenv("LAMP_BATHROOM_MAC"), os.getenv("LAMP_BATHROOM_TOKEN"), False),
            #  c[0]                 c[1]                            c[2]                  c[3]
        ]

        # 1. Валидация конфигов с понятными ошибками
        valid_configs = []
        for name, mac, token, has_color in configs:
            if not mac and not token:
                continue
            if mac and not token:
                print(f"[!] Ошибка конфига: для лампы '{name}' указан MAC, но отсутствует TOKEN в .env")
                continue
            if not mac and token:
                print(f"[!] Ошибка конфига: для лампы '{name}' указан TOKEN, но отсутствует MAC в .env")
                continue
            valid_configs.append((name, mac, token, has_color))

        # 2. Оптовый поиск IP сразу для всех ламп
        all_macs = [c[1] for c in valid_configs]
        ip_map = resolve_all_ips(all_macs)

        # 3. Инициализируем лампы по готовым адресам
        for name, mac, token, has_color in valid_configs:
            clean_mac = mac.lower().replace("-", ":")
            current_ip = ip_map.get(clean_mac)

            if current_ip:
                try:
                    self.lamps[name] = SingleLamp(name=name, mac=clean_mac, token=token, ip=current_ip, has_color=has_color)
                    print(f"[+] Лампа '{name}' найдена на {current_ip}")
                except Exception as e:
                    print(f"[!] Ошибка подключения к лампе '{name}': {e}")
            else:
                print(f"[-] Не удалось найти лампу '{name}' с MAC {mac} в сети.")

    def resolve_targets(self, room: Optional[str]) -> List[SingleLamp]:
        """Определяет список целевых ламп по названию комнаты или синониму."""
        if not room:
            # По умолчанию управляем спальней (где стоит ПК)
            return [self.lamps["спальня"]] if "спальня" in self.lamps else list(self.lamps.values())

        room_clean = room.strip().lower()

        # Если запрошено "везде" / "все"
        for alias in ROOM_ALIASES["все"]:
            if alias in room_clean:
                return list(self.lamps.values())

        # Поиск по конкретным комнатам
        for canonical_name, aliases in ROOM_ALIASES.items():
            if any(a in room_clean for a in aliases):
                if canonical_name in self.lamps:
                    return [self.lamps[canonical_name]]

        # Резервный поиск по прямому ключу
        if room_clean in self.lamps:
            return [self.lamps[room_clean]]

        # Если комната не опознана, возвращаем спальню
        return [self.lamps["спальня"]] if "спальня" in self.lamps else list(self.lamps.values())

    def turn_on(self, room: Optional[str] = None) -> Dict[str, Any]:
        targets = self.resolve_targets(room)
        results = {lamp.name: lamp.turn_on() for lamp in targets}
        return {"status": "success", "room": room or "спальня", "results": results}

    def turn_off(self, room: Optional[str] = None) -> Dict[str, Any]:
        targets = self.resolve_targets(room)
        results = {lamp.name: lamp.turn_off() for lamp in targets}
        return {"status": "success", "room": room or "спальня", "results": results}

    def toggle(self, room: Optional[str] = None) -> Dict[str, Any]:
        targets = self.resolve_targets(room)
        results = {lamp.name: lamp.toggle() for lamp in targets}
        return {"status": "success", "room": room or "спальня", "results": results}

    def set_brightness(self, level: int, room: Optional[str] = None) -> Dict[str, Any]:
        targets = self.resolve_targets(room)
        results = {lamp.name: lamp.set_brightness(level) for lamp in targets}
        return {"status": "success", "level": level, "room": room or "спальня", "results": results}

    def set_color(self, color: str, room: Optional[str] = "спальня") -> Dict[str, Any]:
        # Цвет есть только в спальне
        target_room = "спальня" if not room or "все" in room else room
        targets = [lamp for lamp in self.resolve_targets(target_room) if lamp.has_color]
        if not targets:
            return {"status": "error", "message": "Среди выбранных ламп нет устройств с поддержкой цвета."}
        results = {lamp.name: lamp.set_color(color) for lamp in targets}
        return {"status": "success", "color": color, "results": results}

    def set_color_temp(self, kelvin: int, room: Optional[str] = "спальня") -> Dict[str, Any]:
        target_room = "спальня" if not room or "все" in room else room
        targets = [lamp for lamp in self.resolve_targets(target_room) if lamp.has_color]
        if not targets:
            return {"status": "error", "message": "Выбранная лампа не поддерживает смену температуры."}
        results = {lamp.name: lamp.set_color_temp(kelvin) for lamp in targets}
        return {"status": "success", "kelvin": kelvin, "results": results}

    def get_status(self, room: Optional[str] = None) -> Dict[str, Any]:
        targets = self.resolve_targets(room)
        return {"status": "success", "statuses": {lamp.name: lamp.get_status() for lamp in targets}}


# Для обратной совместимости
LampController = LampManager