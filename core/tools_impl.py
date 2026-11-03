from controllers.device_con.LampManager import LampManager
from controllers.pc_controller import PCController
from core import memory
from core import scenarios_manager
from core.tools_registry import execute_tool, register_tool

devices = LampManager()
pc = PCController()

ROOM_PARAM = {
    "type": "string",
    "description": (
        "Комната: 'спальня', 'кухня', 'ванная', 'прихожая' или 'все'/'везде'."
        " По умолчанию 'спальня'."
    ),
    "enum": ["спальня", "кухня", "ванная", "прихожая", "все"],
}


def _loc(room: str | None) -> str:
  return " везде" if room in ("все", "везде") else (f" в {room}" if room else "")


# ==========================================
# 1. УПРАВЛЕНИЕ ЛАМПАМИ
# ==========================================


@register_tool(
    name="turn_on_lamp",
    description="Включить свет.",
    parameters={"type": "object", "properties": {"room": ROOM_PARAM}},
    response_template=lambda a, r: f"Свет{_loc(a.get('room'))} включен.",
)
def turn_on_lamp(room: str = "спальня"):
  return devices.turn_on(room)


@register_tool(
    name="turn_off_lamp",
    description="Выключить свет.",
    parameters={"type": "object", "properties": {"room": ROOM_PARAM}},
    response_template=lambda a, r: f"Свет{_loc(a.get('room'))} выключен.",
)
def turn_off_lamp(room: str = "спальня"):
  return devices.turn_off(room)


@register_tool(
    name="toggle_lamp",
    description="Переключить состояние света (вкл/выкл).",
    parameters={"type": "object", "properties": {"room": ROOM_PARAM}},
    response_template=lambda a, r: f"Свет{_loc(a.get('room'))} переключен.",
)
def toggle_lamp(room: str = "спальня"):
  return devices.toggle(room)


@register_tool(
    name="set_lamp_brightness",
    description="Установить яркость света (1-100%).",
    parameters={
        "type": "object",
        "properties": {"level": {"type": "integer"}, "room": ROOM_PARAM},
        "required": ["level"],
    },
    response_template=lambda a, r: (
        f"Яркость{_loc(a.get('room'))} установлена на {a.get('level', 100)}%."
    ),
)
def set_lamp_brightness(level: int, room: str = "спальня"):
  return devices.set_brightness(level, room)


@register_tool(
    name="set_lamp_rgb",
    description=(
        "Установить цвет лампы через компоненты RGB (0-255). Модель сама"
        " подбирает числа (только спальня)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "r": {"type": "integer"},
            "g": {"type": "integer"},
            "b": {"type": "integer"},
            "room": ROOM_PARAM,
        },
        "required": ["r", "g", "b"],
    },
    response_template=lambda a, r: (
        f"Цвет в спальне изменен на RGB ({a.get('r')}, {a.get('g')},"
        f" {a.get('b')})."
    ),
)
def set_lamp_rgb(
    r: int = 255, g: int = 255, b: int = 255, room: str = "спальня"
):
  return devices.set_rgb(r, g, b, room)


@register_tool(
    name="set_lamp_color",
    description="Установить цвет по названию (для быстрых команд).",
    parameters={
        "type": "object",
        "properties": {"color": {"type": "string"}, "room": ROOM_PARAM},
        "required": ["color"],
    },
    response_template=lambda a, r: (
        f"Цвет в спальне изменен на {a.get('color')}."
    ),
)
def set_lamp_color(color: str = "белый", room: str = "спальня"):
  return devices.set_color(color, room)


@register_tool(
    name="set_lamp_color_temp",
    description="Цветовая температура 1700-6500K (только спальня).",
    parameters={
        "type": "object",
        "properties": {"kelvin": {"type": "integer"}, "room": ROOM_PARAM},
        "required": ["kelvin"],
    },
    response_template=lambda a, r: (
        f"Температура света установлена на {a.get('kelvin')}K."
    ),
)
def set_lamp_color_temp(kelvin: int = 4000, room: str = "спальня"):
  return devices.set_color_temp(kelvin, room)


@register_tool(
    name="get_lamp_status",
    description="Проверить статус ламп.",
    parameters={"type": "object", "properties": {"room": ROOM_PARAM}},
    response_template="Статус ламп получен.",
)
def get_lamp_status(room: str = "спальня"):
  return devices.get_status(room)


# ==========================================
# 2. УПРАВЛЕНИЕ ПК И МУЛЬТИМЕДИА
# ==========================================


@register_tool(
    name="next_track",
    description="Следующий трек в плеере на ПК.",
    parameters={"type": "object", "properties": {}},
    response_template="Включен следующий трек.",
)
def next_track():
  return pc.next_track()


@register_tool(
    name="prev_track",
    description="Предыдущий трек в плеере на ПК.",
    parameters={"type": "object", "properties": {}},
    response_template="Включен предыдущий трек.",
)
def prev_track():
  return pc.prev_track()


@register_tool(
    name="play_pause_track",
    description="Пауза или продолжение музыки на ПК.",
    parameters={"type": "object", "properties": {}},
    response_template="Воспроизведение переключено.",
)
def play_pause_track():
  return pc.play_pause()


@register_tool(
    name="volume_up",
    description="Сделать звук на ПК громче.",
    parameters={
        "type": "object",
        "properties": {"steps": {"type": "integer", "description": "Шагов (1-10)"}},
    },
    response_template="Сделал погромче.",
)
def volume_up(steps: int = 5):
  return pc.volume_up(steps)


@register_tool(
    name="volume_down",
    description="Сделать звук на ПК тише.",
    parameters={
        "type": "object",
        "properties": {"steps": {"type": "integer", "description": "Шагов (1-10)"}},
    },
    response_template="Сделал потише.",
)
def volume_down(steps: int = 5):
  return pc.volume_down(steps)


@register_tool(
    name="volume_mute",
    description="Заглушить/включить звук на ПК.",
    parameters={"type": "object", "properties": {}},
    response_template="Звук переключен.",
)
def volume_mute():
  return pc.volume_mute()


@register_tool(
    name="open_app",
    description=(
        "Открыть приложение на ПК (браузер, хром, телеграм, стим, калькулятор,"
        " блокнот)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "app_name": {
                "type": "string",
                "description": "Имя приложения на русском",
            }
        },
        "required": ["app_name"],
    },
    response_template=lambda a, r: (
        f"Открываю {a.get('app_name')}."
        if r.get("status") == "success"
        else r.get("message")
    ),
)
def open_app(app_name: str):
  return pc.open_app(app_name)


# ==========================================
# 3. ДОЛГОВРЕМЕННАЯ ПАМЯТЬ
# ==========================================


@register_tool(
    name="remember_user_preference",
    description="Сохранить предпочтение пользователя или привычку.",
    parameters={
        "type": "object",
        "properties": {
            "fact": {
                "type": "string",
                "description": "Краткая формулировка факта от 3-го лица",
            }
        },
        "required": ["fact"],
    },
    response_template=lambda a, r: r
    if isinstance(r, str)
    else "Запомнил.",
)
def remember_user_preference(fact: str):
  return memory.save_fact(fact)

# ==========================================
# 4. СЦЕНАРИИ
# ==========================================


@register_tool(
    name="run_scenario",
    description=(
        "Запустить готовый сценарий автоматизации по имени (например: 'кино',"
        " 'спать', 'вечеринка')."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Название сценария на русском",
            }
        },
        "required": ["name"],
    },
    response_template=lambda a, r: (
        f"Сценарий '{a.get('name')}' выполнен."
        if r.get("status") == "success"
        else r.get("message")
    ),
)
def tool_run_scenario(name: str):
  # Передаем сам execute_tool внутрь, чтобы сценарий мог вызывать любые функции
  return scenarios_manager.run_scenario(name, execute_tool)


@register_tool(
    name="save_scenario",
    description=(
        "Создать или сохранить новый сценарий из цепочки действий, когда"
        " пользователь прямо просит настроить или запомнить сценарий."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Краткое имя сценария (например: 'уборка')",
            },
            "steps": {
                "type": "array",
                "description": "Список шагов сценария",
                "items": {
                    "type": "object",
                    "properties": {
                        "tool": {
                            "type": "string",
                            "description": "Имя инструмента",
                        },
                        "args": {
                            "type": "object",
                            "description": "Параметры инструмента",
                        },
                    },
                    "required": ["tool"],
                },
            },
        },
        "required": ["name", "steps"],
    },
    response_template=lambda a, r: (
        f"Сценарий '{a.get('name')}' успешно сохранён."
        if r.get("status") == "success"
        else r.get("message")
    ),
)
def tool_save_scenario(name: str, steps: list[dict]):
  return scenarios_manager.add_scenario(name, steps)