# agent.py
import argparse
import json
import os
import re
from openai import OpenAI

import config
from device_controller import LampManager, PRESET_COLORS
from pc_controller import PCController

devices = LampManager()
pc = PCController()

client = OpenAI(
    api_key=config.LLM_API_KEY or "dummy_key",
    base_url=config.LLM_BASE_URL,
    timeout=15.0,
    max_retries=1,
)

ROOM_PARAM = {
    "type": "string",
    "description": "Комната: 'спальня', 'кухня', 'ванная', 'прихожая' или 'все'/'везде'. По умолчанию 'спальня'.",
    "enum": ["спальня", "кухня", "ванная", "прихожая", "все"]
}

TOOLS = [
    {"type": "function", "function": {"name": "turn_on_lamp", "description": "Включить свет.", "parameters": {"type": "object", "properties": {"room": ROOM_PARAM}}}},
    {"type": "function", "function": {"name": "turn_off_lamp", "description": "Выключить свет.", "parameters": {"type": "object", "properties": {"room": ROOM_PARAM}}}},
    {"type": "function", "function": {"name": "toggle_lamp", "description": "Переключить свет.", "parameters": {"type": "object", "properties": {"room": ROOM_PARAM}}}},
    {"type": "function", "function": {"name": "set_lamp_brightness", "description": "Установить яркость (1-100%).", "parameters": {"type": "object", "properties": {"level": {"type": "integer"}, "room": ROOM_PARAM}, "required": ["level"]}}},
    {"type": "function", "function": {"name": "set_lamp_color", "description": "Установить цвет (только спальня).", "parameters": {"type": "object", "properties": {"color": {"type": "string"}}, "required": ["color"]}}},
    {"type": "function", "function": {"name": "set_lamp_color_temp", "description": "Температура 1700-6500K (только спальня).", "parameters": {"type": "object", "properties": {"kelvin": {"type": "integer"}}, "required": ["kelvin"]}}},
    {"type": "function", "function": {"name": "get_lamp_status", "description": "Проверить статус ламп.", "parameters": {"type": "object", "properties": {"room": ROOM_PARAM}}}},
    {"type": "function", "function": {"name": "next_track", "description": "Следующий трек на ПК.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "prev_track", "description": "Предыдущий трек на ПК.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "play_pause_track", "description": "Пауза/плей музыки на ПК.", "parameters": {"type": "object", "properties": {}}}},
]

# Диспетчер инструментов с поддержкой комнат
TOOL_HANDLERS = {
    "turn_on_lamp": lambda a: devices.turn_on(a.get("room")),
    "turn_off_lamp": lambda a: devices.turn_off(a.get("room")),
    "toggle_lamp": lambda a: devices.toggle(a.get("room")),
    "set_lamp_brightness": lambda a: devices.set_brightness(a.get("level", 100), a.get("room")),
    "set_lamp_color": lambda a: devices.set_color(a.get("color", "белый"), a.get("room") or "спальня"),
    "set_lamp_color_temp": lambda a: devices.set_color_temp(a.get("kelvin", 4000), a.get("room") or "спальня"),
    "get_lamp_status": lambda a: devices.get_status(a.get("room")),
    "next_track": lambda a: pc.next_track(),
    "prev_track": lambda a: pc.prev_track(),
    "play_pause_track": lambda a: pc.play_pause(),
}

def execute_tool(name: str, arguments: dict) -> dict:
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return {"status": "error", "message": f"Неизвестный инструмент: {name}"}
    try:
        return handler(arguments)
    except Exception as e:
        return {"status": "error", "message": str(e)}

def format_tool_response(name: str, arguments: dict, result: dict) -> str:
    room = arguments.get("room")
    loc = "везде" if room in ("все", "везде") else (f" в {room}" if room else "")
    if name == "turn_on_lamp": return f"Свет{loc} включен."
    if name == "turn_off_lamp": return f"Свет{loc} выключен."
    if name == "toggle_lamp": return f"Свет{loc} переключен."
    if name == "set_lamp_brightness": return f"Яркость{loc} установлена на {arguments.get('level', 100)}%."
    if name == "set_lamp_color":
        if result.get("status") == "error": return result.get("message", "Ошибка цвета.")
        return f"Цвет в спальне изменен на {arguments.get('color')}."
    if name == "set_lamp_color_temp": return f"Температура света установлена на {arguments.get('kelvin')}K."
    if name == "next_track": return "Включен следующий трек."
    if name == "prev_track": return "Включен предыдущий трек."
    if name == "play_pause_track": return "Воспроизведение переключено."
    return "Действие выполнено."

def parse_room_from_text(cmd: str) -> str:
    if any(w in cmd for w in ("везде", "весь свет", "все лампы", "во всей квартире", "всех комнатах")): return "все"
    if any(w in cmd for w in ("кухн", "кухне", "кухню")): return "кухня"
    if any(w in cmd for w in ("ванн", "сануз", "туалет")): return "ванная"
    if any(w in cmd for w in ("прихож", "коридор")): return "прихожая"
    return "спальня"

# Предкомпилированные регулярки для Fast-Path
TEMP_RULES = [
    (re.compile(r"тепл\w*\s+(?:бел\w*\s+)?свет|тепл\w*\s+бел\w*"), 2700),
    (re.compile(r"холодн\w*\s+(?:бел\w*\s+)?свет|холодн\w*\s+бел\w*"), 6000),
    (re.compile(r"(?:дневн|нейтральн)\w*\s+свет"), 4000),
]

_RU_COLORS = sorted([c for c in PRESET_COLORS if re.fullmatch(r"[а-я]+", c)], key=len, reverse=True)
_COLOR_RE = re.compile(r"\b(?:сделай|включи|поставь|установи|зажги)\s+(?:\w+\s+){0,2}(" + "|".join(_RU_COLORS) + r")\b")

def try_fast_intent(text: str) -> str | None:
    cmd = text.strip().lower().replace("ё", "е")

    # 1.4 Гвард: сложные и составные фразы сразу отдаем в LLM
    if len(cmd.split()) > 7 or re.search(r"\b(и|потом|заодно)\b", cmd):
        return None

    room = parse_room_from_text(cmd)

    # 1. Мультимедиа (строгие фразы без ложных одиночных слов)
    if any(w in cmd for w in ("следующий трек", "следующую песню", "переключи трек", "скипни трек")):
        return format_tool_response("next_track", {}, execute_tool("next_track", {}))
    if any(w in cmd for w in ("предыдущий трек", "предыдущую песню", "назад трек")):
        return format_tool_response("prev_track", {}, execute_tool("prev_track", {}))
    if any(w in cmd for w in ("поставь на паузу", "пауза", "продолжи музыку", "включи музыку")):
        return format_tool_response("play_pause_track", {}, execute_tool("play_pause_track", {}))

    # 2. Вкл / Выкл / Переключение
    if any(v in cmd for v in ("включи свет", "вруби свет", "зажги свет", "включи лампу", "включи все", "включи везде")):
        res = execute_tool("turn_on_lamp", {"room": room})
        return format_tool_response("turn_on_lamp", {"room": room}, res)

    if any(v in cmd for v in ("выключи свет", "выруби свет", "погаси свет", "потуши свет", "выключи лампу", "выключи все", "выключи везде")):
        res = execute_tool("turn_off_lamp", {"room": room})
        return format_tool_response("turn_off_lamp", {"room": room}, res)

    if "переключи свет" in cmd:
        res = execute_tool("toggle_lamp", {"room": room})
        return format_tool_response("toggle_lamp", {"room": room}, res)

    # 3. Температура света (ДО цветов, чтобы «тёплый белый» не стал «белым»)
    for pattern, kelvin in TEMP_RULES:
        if pattern.search(cmd):
            res = execute_tool("set_lamp_color_temp", {"kelvin": kelvin, "room": "спальня"})
            return format_tool_response("set_lamp_color_temp", {"kelvin": kelvin}, res)

    # 4. Цвет (только с глаголом)
    color_match = _COLOR_RE.search(cmd)
    if color_match:
        color_val = color_match.group(1)
        res = execute_tool("set_lamp_color", {"color": color_val})
        return format_tool_response("set_lamp_color", {"color": color_val}, res)

    return None

SYSTEM_PROMPT = f"""Ты — голосовой ассистент '{config.ASSISTANT_NAME.capitalize()}'.
В твоем распоряжении:
- Лампа 'спальня': цветная (вкл/выкл, яркость, цвет, температура).
- Лампы 'кухня', 'прихожая', 'ванная': монохромные (только вкл/выкл, яркость).
Если комната не названа, по умолчанию 'спальня'. Если 'везде' — 'все'.
Всегда вызывай нужный инструмент. Отвечай кратко — 1 предложение."""

conversation_history = [{"role": "system", "content": SYSTEM_PROMPT}]

def trim_history():
    global conversation_history
    if len(conversation_history) > 9:
        conversation_history = [conversation_history[0]] + conversation_history[-8:]

def chat(user_text: str) -> str:
    # 1.1 Fast-Path с гарантированной обрезкой истории
    fast_reply = try_fast_intent(user_text)
    if fast_reply is not None:
        conversation_history.append({"role": "user", "content": user_text})
        conversation_history.append({"role": "assistant", "content": fast_reply})
        trim_history()
        return fast_reply

    conversation_history.append({"role": "user", "content": user_text})
    trim_history()

    try:
        response = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=conversation_history,
            tools=TOOLS,
            tool_choice="auto",
        )
    except Exception as e:
        print(f"[!] Ошибка LLM: {e}")
        return "Не удалось связаться с сервером."

    msg = response.choices[0].message
    if msg.tool_calls:
        responses = []
        for tool_call in msg.tool_calls:
            try:
                fn_args = json.loads(tool_call.function.arguments or "{}")
            except Exception:
                fn_args = {}
            tool_res = execute_tool(tool_call.function.name, fn_args)
            responses.append(format_tool_response(tool_call.function.name, fn_args, tool_res))
        answer = " ".join(responses)
        conversation_history.append({"role": "assistant", "content": answer})
        trim_history()
        return answer

    answer = msg.content or "Выполнено."
    conversation_history.append({"role": "assistant", "content": answer})
    trim_history()
    return answer

def start_voice_mode():
    from voice_controller import VoiceListener
    listener = VoiceListener(assistant_name=config.ASSISTANT_NAME.capitalize())
    listener.run(chat)

def main():
    parser = argparse.ArgumentParser(description="Ассистент умного дома")
    parser.add_argument("--voice", "-v", action="store_true", help="Голосовой режим")
    args = parser.parse_args()

    if args.voice:
        start_voice_mode()
        return

    print("=" * 55)
    print(f" Ассистент '{config.ASSISTANT_NAME.capitalize()}' готов к работе.")
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
            print(f"\n{config.ASSISTANT_NAME.capitalize()}:\n{chat(inp)}")
        except KeyboardInterrupt:
            break

if __name__ == "__main__":
    main()