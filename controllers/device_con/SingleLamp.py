
import re
from typing import Any, Dict, Optional, Tuple, Union

from miio import Device
from miio.exceptions import DeviceException

from controllers.device_con.constants import PRESET_COLORS
from controllers.resolver import resolve_all_ips


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