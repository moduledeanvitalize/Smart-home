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

LAMPS_RESPONSES = {
    "on": "Свет включен.",
    "off": "Свет выключен.",
    "brightness": "Яркость установлена.",
    "rgb": "Цвет изменен.",
    "color_temp": "Температура света установлена.",
    "status": "Статус лампы получен.",
}

def _format_lamp_reply(action: dict, result: dict) -> str:
    """Форматирует ответ для действий с лампами."""
    if result.get("status") != "success":
        return result.get("message", "Не удалось выполнить действие.")

    # проверка на обесточенность
    results = result.get("results", {})
    offline = [room for room, res in results.items() if res.get("status") == "offline"]
    if offline:
        return f"Лампа в комнате {', '.join(offline)} обесточена. Проверь выключатель."

    return LAMPS_RESPONSES.get(action.get("action"), "Выполнено.")

@register_tool(
    name="lamp_control",
    description="Управление лампами(вкл/выкл/яркость/цвет/статус/температура).",
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string", 
            "enum": ["on", "off", "brightness", "rgb", "color_temp", "status"]},
            "room": ROOM_PARAM,
            "level": {"type": "integer", "description": "Яркость 1-100% (только для brightness)"},
            "r": {"type": "integer", "description": "Красный (0-255) для action='rgb'"},
            "g": {"type": "integer", "description": "Зеленый (0-255) для action='rgb'"},
            "b": {"type": "integer", "description": "Синий (0-255) для action='rgb'"},
            "kelvin": {"type": "integer", "description": "Цветовая температура 1700-6500K (только для color_temp в спальне)"},
        },
        "required": ["action"],
    },
    response_template=_format_lamp_reply,
)

def lamp_control(action: str, room: str = "спальня", level: int = 100, r: int = 255, g: int = 255, b: int = 255, kelvin: int = 4000):
    if action == "on":
        return devices.turn_on(room)
    elif action == "off":
        return devices.turn_off(room)
    elif action == "brightness":
        return devices.set_brightness(level, room)
    elif action == "rgb":
        return devices.set_rgb(r, g, b, room)
    elif action == "color_temp":
        return devices.set_color_temp(kelvin, room)
    elif action == "status":
        return devices.get_status(room)
    else:
        return {"status": "error", "message": f"Неизвестное действие лампы: {action}"}


# ==========================================
# 2. УПРАВЛЕНИЕ ПК И МУЛЬТИМЕДИА
# ==========================================

MEDIA_RESPONSES = {
    "next": "Включен следующий трек.",
    "prev": "Включен предыдущий трек.",
    "play_pause": "Воспроизведение переключено.",
    "volume_up": "Сделал погромче.",
    "volume_down": "Сделал потише.",
    "mute": "Звук переключен.",
}


@register_tool(
    name="control_media",
    description="Управление плеером и громкостью звука на ПК (пауза/плей, следующий/предыдущий трек, громче, тише, заглушить).",
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["play_pause", "next", "prev", "volume_up", "volume_down", "mute"],
            },
            "steps": {
                "type": "integer",
                "description": "Количество шагов громкости от 1 до 10 (нужно только для volume_up и volume_down)",
            },
        },
        "required": ["action"],
    },
    response_template=lambda a, r: MEDIA_RESPONSES.get(a.get("action"), "Действие выполнено."),
)
def control_media(action: str, steps: int = 5):
    if action == "next":
        return pc.next_track()
    elif action == "prev":
        return pc.prev_track()
    elif action == "play_pause":
        return pc.play_pause()
    elif action == "volume_up":
        return pc.volume_up(steps)
    elif action == "volume_down":
        return pc.volume_down(steps)
    elif action == "mute":
        return pc.volume_mute()
    return {"status": "error", "message": f"Неизвестное действие медиа: {action}"}


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


def _format_notes_reply(a: dict, r: dict) -> str:
    if r.get("status") != "success":
        return r.get("message", "Ошибка при работе с заметками.")

    action = a.get("action")
    if action == "add":
        note = r.get("note", {})
        return f"Записал под номером {note.get('id')}: {note.get('text')}."

    elif action == "list":
        notes = r.get("notes", [])
        if not notes:
            return "Список заметок пуст."
        items = [f"{n['id']}. {n['text']}" for n in notes]
        return "Твои заметки: " + "; ".join(items) + "."

    elif action == "delete":
        deleted = r.get("deleted", {})
        return f"Удалил заметку: {deleted.get('text')}."

    return "Готово."
@register_tool(
    name="manage_notes",
    description="Управление временными заметками и списками дел (добавить, прочитать список, удалить).",
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "list", "delete"],},
            "text": {
                "type": "string",
                "description": "Текст новой заметки (нужно только для action='add')",
            },
            "target": {
                "type": "string",
                "description": "Номер (ID) или ключевое слово для удаления (нужно только для action='delete')",
                },
        },
        "required": ["action"],
    },
    response_template=_format_notes_reply,
)
def tool_manage_notes(action: str, text: str = "", target: str | None = None):
    return memory.manage_notes(action=action, text=text, target=target)

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