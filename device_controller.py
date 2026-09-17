import os
import re
from typing import Dict, Any, Optional, Tuple, Union, List
from dotenv import load_dotenv
from miio import Device
from miio.exceptions import DeviceException

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
    "спальня": ["спальня", "спальне", "спальню", "комната", "комнате", "комнату", "bedroom"],
    "кухня": ["кухня", "кухне", "кухню", "kitchen"],
    "прихожая": ["прихожая", "прихожей", "прихожую", "коридор", "коридоре", "hallway"],
    "ванная": ["ванная", "ванной", "ванную", "туалет", "санузел", "bathroom"],
    "все": ["все", "всё", "везде", "все лампы", "весь свет", "all"],
}


class SingleLamp:
    """Управление одной конкретной лампой."""

    def __init__(self, name: str, ip: str, token: str, has_color: bool = False):
        self.name = name
        self.ip = ip
        self.token = token
        self.has_color = has_color
        self.device = Device(ip=self.ip, token=self.token)

    def turn_on(self) -> Dict[str, Any]:
        try:
            res = self.device.send("set_power", ["on"])
            return {"status": "success", "power": "on", "response": res}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def turn_off(self) -> Dict[str, Any]:
        try:
            res = self.device.send("set_power", ["off"])
            return {"status": "success", "power": "off", "response": res}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def toggle(self) -> Dict[str, Any]:
        try:
            res = self.device.send("toggle", [])
            return {"status": "success", "action": "toggle", "response": res}
        except DeviceException:
            status = self.get_status()
            if status.get("status") == "success":
                return self.turn_off() if status.get("power") == "on" else self.turn_on()
            return {"status": "error", "message": "Не удалось переключить питание"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def set_brightness(self, level: int) -> Dict[str, Any]:
        try:
            level = max(1, min(100, int(level)))
            res = self.device.send("set_bright", [level])
            return {"status": "success", "brightness": level, "response": res}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def set_rgb(self, red: int, green: int, blue: int) -> Dict[str, Any]:
        if not self.has_color:
            return {"status": "error", "message": f"Лампа в '{self.name}' не поддерживает смену цвета."}
        try:
            r, g, b = max(0, min(255, int(red))), max(0, min(255, int(green))), max(0, min(255, int(blue)))
            rgb_int = (r << 16) + (g << 8) + b
            res = self.device.send("set_rgb", [rgb_int])
            return {"status": "success", "rgb": [r, g, b], "response": res}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def set_color_temp(self, kelvin: int) -> Dict[str, Any]:
        if not self.has_color:
            return {"status": "error", "message": f"Лампа в '{self.name}' не поддерживает цветовую температуру."}
        try:
            k = max(1700, min(6500, int(kelvin)))
            res = self.device.send("set_ct_abx", [k, "smooth", 500])
            return {"status": "success", "color_temp": k, "response": res}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def set_color(self, color: Union[str, Tuple[int, int, int], list]) -> Dict[str, Any]:
        if not self.has_color:
            return {"status": "error", "message": f"Лампа в '{self.name}' монохромная, цвет менять нельзя."}

        if isinstance(color, (tuple, list)) and len(color) == 3:
            return self.set_rgb(int(color[0]), int(color[1]), int(color[2]))

        if isinstance(color, str):
            clean = color.strip().lower()
            if clean in PRESET_COLORS:
                return self.set_rgb(*PRESET_COLORS[clean])
            hex_match = re.match(r"^#?([0-9a-f]{6})$", clean)
            if hex_match:
                val = hex_match.group(1)
                return self.set_rgb(int(val[0:2], 16), int(val[2:4], 16), int(val[4:6], 16))
        return {"status": "error", "message": f"Неизвестный цвет: {color}"}

    def get_status(self) -> Dict[str, Any]:
        try:
            props = ["power", "bright"]
            if self.has_color:
                props.extend(["rgb", "ct", "color_mode"])
            res = self.device.send("get_prop", props)
            if isinstance(res, list) and len(res) >= 2:
                status = {"status": "success", "power": res[0], "brightness": res[1]}
                if self.has_color and len(res) >= 3 and res[2]:
                    rgb_val = int(res[2])
                    status["rgb"] = [(rgb_val >> 16) & 0xFF, (rgb_val >> 8) & 0xFF, rgb_val & 0xFF]
                return status
            return {"status": "success", "raw": res}
        except Exception as e:
            return {"status": "error", "message": str(e)}


class LampManager:
    """Менеджер для управления группой ламп по комнатам."""

    def __init__(self):
        self.lamps: Dict[str, SingleLamp] = {}

        # Инициализация ламп из .env
        configs = [
            ("спальня", os.getenv("LAMP_BEDROOM_IP", "192.168.0.4"), os.getenv("LAMP_BEDROOM_TOKEN"), True),
            ("кухня", os.getenv("LAMP_KITCHEN_IP", "192.168.0.7"), os.getenv("LAMP_KITCHEN_TOKEN"), False),
            ("прихожая", os.getenv("LAMP_HALLWAY_IP", "192.168.0.8"), os.getenv("LAMP_HALLWAY_TOKEN"), False),
            ("ванная", os.getenv("LAMP_BATHROOM_IP", "192.168.0.10"), os.getenv("LAMP_BATHROOM_TOKEN"), False),
        ]

        for name, ip, token, has_color in configs:
            if ip and token and token != "ваш_токен":
                try:
                    self.lamps[name] = SingleLamp(name=name, ip=ip, token=token, has_color=has_color)
                except Exception as e:
                    print(f"[!] Ошибка подключения к лампе '{name}': {e}")

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