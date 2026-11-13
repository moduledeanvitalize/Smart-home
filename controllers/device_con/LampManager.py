import os
from typing import Dict, Any, Optional, Tuple, Union, List
from dotenv import load_dotenv
from typing import Optional

from controllers.resolver import resolve_all_ips
from controllers.device_con.constants import PRESET_COLORS, ROOM_ALIASES
from controllers.device_con.SingleLamp import SingleLamp

ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(ENV_PATH, override=True)


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
        # 1. Определяем комнату (если не указана — спальня)
        target_room = "спальня" if not room or "все" in room else room
        
        # 2. Оставляем только лампы, умеющие в цвет
        targets = [lamp for lamp in self.resolve_targets(target_room) if lamp.has_color]
        if not targets:
            return {"status": "error", "message": "Среди выбранных ламп нет устройств с поддержкой цвета."}
        
        # 3. У каждой найденной лампы вызываем её родной SingleLamp.set_color()!
        results = {lamp.name: lamp.set_color(color) for lamp in targets}
        return {"status": "success", "color": color, "results": results}

    def set_rgb(self, r: int, g: int, b: int, room: Optional[str] = "спальня") -> Dict[str, Any]:
        # Цвет есть только в спальне
        target_room = "спальня" if not room or "все" in room else room
        targets = [lamp for lamp in self.resolve_targets(target_room) if lamp.has_color]
        if not targets:
            return {"status": "error", "message": "Среди выбранных ламп нет устройств с поддержкой цвета."}
        results = {lamp.name: lamp.set_rgb(r, g, b) for lamp in targets}
        return {"status": "success", "color": (r, g, b), "results": results}

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