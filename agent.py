import argparse
import json
import os
import re
import sys
from dotenv import load_dotenv
from openai import OpenAI

ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(ENV_PATH, override=True)

from device_controller import LampManager
from pc_controller import PCController

ASSISTANT_NAME = os.getenv("ASSISTANT_NAME", "ишак").strip().lower()

# Инициализация менеджера ламп
devices = LampManager()
pc = PCController()

API_KEY = os.getenv("LLM_API_KEY")
BASE_URL = os.getenv("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
MODEL_NAME = os.getenv("LLM_MODEL", "gemini-3.1-flash-lite")

client = OpenAI(api_key=API_KEY or "dummy_key", base_url=BASE_URL)

ROOM_PARAM = {
    "type": "string",
    "description": "Комната: 'спальня', 'кухня', 'ванная', 'прихожая' или 'все'/'везде'. Если не указана, по умолчанию 'спальня'.",
    "enum": ["спальня", "кухня", "ванная", "прихожая", "все"]
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "turn_on_lamp",
            "description": "Включить освещение в конкретной комнате (спальня, кухня, ванная, прихожая) или везде.",
            "parameters": {"type": "object", "properties": {"room": ROOM_PARAM}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "turn_off_lamp",
            "description": "Выключить освещение в конкретной комнате или везде.",
            "parameters": {"type": "object", "properties": {"room": ROOM_PARAM}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "toggle_lamp",
            "description": "Переключить свет (вкл/выкл) в комнате.",
            "parameters": {"type": "object", "properties": {"room": ROOM_PARAM}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_lamp_brightness",
            "description": "Установить яркость (1-100%).",
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {"type": "integer", "description": "Яркость 1-100%"},
                    "room": ROOM_PARAM,
                },
                "required": ["level"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_lamp_color",
            "description": "Установить цвет лампы (работает только для спальни, в остальных комнатах лампы монохромные).",
            "parameters": {
                "type": "object",
                "properties": {
                    "color": {"type": "string", "description": "Название цвета ('красный', 'синий', 'зеленый' и т.д.)"},
                },
                "required": ["color"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_lamp_color_temp",
            "description": "Установить цветовую температуру (1700-6500K) для спальни (теплый/холодный свет).",
            "parameters": {
                "type": "object",
                "properties": {"kelvin": {"type": "integer", "description": "Температура 1700-6500K"}},
                "required": ["kelvin"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_lamp_status",
            "description": "Проверить статус ламп.",
            "parameters": {"type": "object", "properties": {"room": ROOM_PARAM}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "next_track",
            "description": "Переключить на следующий трек на ПК.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "prev_track",
            "description": "Переключить на предыдущий трек на ПК.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "play_pause_track",
            "description": "Пауза/плей музыки на ПК.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

def execute_tool(name: str, arguments: dict) -> dict:
    room = arguments.get("room")
    if name == "turn_on_lamp":
        return devices.turn_on(room)
    elif name == "turn_off_lamp":
        return devices.turn_off(room)
    elif name == "toggle_lamp":
        return devices.toggle(room)
    elif name == "set_lamp_brightness":
        return devices.set_brightness(arguments.get("level", 100), room)
    elif name == "set_lamp_color":
        return devices.set_color(arguments.get("color", "белый"), "спальня")
    elif name == "set_lamp_color_temp":
        return devices.set_color_temp(arguments.get("kelvin", 4000), "спальня")
    elif name == "get_lamp_status":
        return devices.get_status(room)
    elif name == "next_track":
        return pc.next_track()
    elif name == "prev_track":
        return pc.prev_track()
    elif name == "play_pause_track":
        return pc.play_pause()
    return {"status": "error", "message": f"Неизвестный инструмент: {name}"}

def format_tool_response(name: str, arguments: dict, result: dict) -> str:
    room = arguments.get("room")
    loc = "везде" if room in ("все", "везде") else (f" в {room}" if room else "")
    if name == "turn_on_lamp":
        return f"Свет{loc} включен."
    elif name == "turn_off_lamp":
        return f"Свет{loc} выключен."
    elif name == "toggle_lamp":
        return f"Свет{loc} переключен."
    elif name == "set_lamp_brightness":
        return f"Яркость{loc} установлена на {arguments.get('level', 100)}%."
    elif name == "set_lamp_color":
        if result.get("status") == "error":
            return result.get("message", "Ошибка смены цвета.")
        return f"Цвет в спальне изменен на {arguments.get('color')}."
    elif name == "set_lamp_color_temp":
        return f"Температура света установлена на {arguments.get('kelvin')}K."
    elif name == "next_track":
        return "Включен следующий трек."
    elif name == "prev_track":
        return "Включен предыдущий трек."
    elif name == "play_pause_track":
        return "Воспроизведение переключено."
    return "Действие выполнено."

def parse_room_from_text(cmd: str) -> str:
    """Извлекает комнату из текста для быстрого пути (Fast-Path)."""
    if any(w in cmd for w in ("везде", "весь свет", "все лампы", "во всей квартире", "всех комнатах")):
        return "все"
    if any(w in cmd for w in ("кухн", "кухне", "кухню")):
        return "кухня"
    if any(w in cmd for w in ("ванн", "сануз")):
        return "ванная"
    if any(w in cmd for w in ("прихож", "коридор")):
        return "прихожая"
    if any(w in cmd for w in ("спальн", "комнат")):
        return "спальня"
    return "спальня"  # по умолчанию спальня

def try_fast_intent(text: str) -> str | None:
    cmd = text.strip().lower()
    room = parse_room_from_text(cmd)

    # 1. Включение света
    if any(v in cmd for v in ("включи свет", "вруби свет", "зажги свет", "включи лампу", "включи всё", "включи везде")):
        res = execute_tool("turn_on_lamp", {"room": room})
        return format_tool_response("turn_on_lamp", {"room": room}, res)

    # 2. Выключение света
    if any(v in cmd for v in ("выключи свет", "выруби свет", "погаси свет", "выключи лампу", "выключи всё", "выключи везде", "потуши свет")):
        res = execute_tool("turn_off_lamp", {"room": room})
        return format_tool_response("turn_off_lamp", {"room": room}, res)

    # 3. Переключение
    if "переключи свет" in cmd:
        res = execute_tool("toggle_lamp", {"room": room})
        return format_tool_response("toggle_lamp", {"room": room}, res)

    # 4. Цвета (только для спальни)
    colors = ["красный", "синий", "зеленый", "зелёный", "желтый", "жёлтый", "голубой", "фиолетовый", "розовый", "оранжевый", "белый"]
    for c in colors:
        if c in cmd and any(w in cmd for w in ("свет", "цвет", "сделай", "поставь")):
            res = execute_tool("set_lamp_color", {"color": c})
            return format_tool_response("set_lamp_color", {"color": c}, res)

    # 5. Музыка
    if any(w in cmd for w in ("следующий трек", "скипни трек", "скип", "переключи трек")):
        return format_tool_response("next_track", {}, execute_tool("next_track", {}))
    if any(w in cmd for w in ("предыдущий трек", "назад трек")):
        return format_tool_response("prev_track", {}, execute_tool("prev_track", {}))
    if any(w in cmd for w in ("пауза", "стоп музыка", "плей", "продолжи музыку")):
        return format_tool_response("play_pause_track", {}, execute_tool("play_pause_track", {}))

    return None

SYSTEM_PROMPT = f"""Ты — ассистент по имени '{ASSISTANT_NAME.capitalize()}'.
Твои обязанности:
1. Управление умным домом. У пользователя 4 лампы:
   - 'спальня' (цветная, поддерживает вкл/выкл, яркость, цвет, температуру);
   - 'кухня', 'прихожая', 'ванная' (монохромные: только вкл/выкл и яркость, цвет менять нельзя!).
   Если комната не названа, по умолчанию управляй спальней. Если просят "везде/все" — управляй всеми.
2. Управление музыкой на компьютере.

Правила:
- Всегда вызывай соответствующий инструмент.
- Отвечай лаконично — строго 1 короткое предложение.
"""

conversation_history = [{"role": "system", "content": SYSTEM_PROMPT}]

def trim_history():
    global conversation_history
    if len(conversation_history) > 9:
        conversation_history = [conversation_history[0]] + conversation_history[-8:]

def chat(user_text: str) -> str:
    fast_reply = try_fast_intent(user_text)
    if fast_reply is not None:
        conversation_history.append({"role": "user", "content": user_text})
        conversation_history.append({"role": "assistant", "content": fast_reply})
        return fast_reply

    conversation_history.append({"role": "user", "content": user_text})
    trim_history()

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=conversation_history,
            tools=TOOLS,
            tool_choice="auto",
        )
    except Exception as e:
        return f"[Ошибка LLM API]: {e}"

    msg = response.choices[0].message
    if msg.tool_calls:
        responses = []
        for tool_call in msg.tool_calls:
            fn_name = tool_call.function.name
            try:
                fn_args = json.loads(tool_call.function.arguments or "{}")
            except Exception:
                fn_args = {}
            tool_res = execute_tool(fn_name, fn_args)
            responses.append(format_tool_response(fn_name, fn_args, tool_res))
        answer = " ".join(responses)
        conversation_history.append({"role": "assistant", "content": answer})
        return answer

    conversation_history.append({"role": "assistant", "content": msg.content})
    return msg.content

def start_voice_mode():
    from voice_controller import VoiceListener
    listener = VoiceListener(assistant_name=ASSISTANT_NAME)
    listener.run(chat)

def main():
    parser = argparse.ArgumentParser(description="Ассистент умного дома")
    parser.add_argument("--voice", "-v", action="store_true", help="Голосовой режим")
    args = parser.parse_args()

    if args.voice:
        start_voice_mode()
        return

    print("=" * 55)
    print(f" Ассистент '{ASSISTANT_NAME.capitalize()}' готов к работе.")
    print(" Лампы: спальня (RGB), кухня, прихожая, ванная.")
    print(" Команды: 'включи свет на кухне', 'выключи везде', 'голос'.")
    print("=" * 55)

    while True:
        try:
            inp = input("\nВы: ").strip()
            if not inp: continue
            if inp.lower() in ("exit", "quit", "выход"): break
            if inp.lower() in ("voice", "голос", "микрофон"):
                start_voice_mode()
                continue
            print(f"\n{ASSISTANT_NAME.capitalize()}:\n{chat(inp)}")
        except KeyboardInterrupt:
            break

if __name__ == "__main__":
    main()