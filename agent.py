import argparse
import json
import os
import re
import sys
from dotenv import load_dotenv
from openai import OpenAI

# Загрузка настроек из .env с принудительным обновлением (override=True)
ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(ENV_PATH, override=True)

from device_controller import LampController
from pc_controller import PCController

# Имя ассистента (настраиваемая переменная из .env)
ASSISTANT_NAME = os.getenv("ASSISTANT_NAME", "гойда").strip().lower()

# Инициализация контроллеров
lamp = None
try:
    lamp = LampController()
except Exception as e:
    print(f"[!] Предупреждение по лампе: {e}")

pc = PCController()

# Инициализация LLM клиента
API_KEY = os.getenv("LLM_API_KEY")
BASE_URL = os.getenv("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
MODEL_NAME = os.getenv("LLM_MODEL", "gemini-3.1-flash-lite")

client = OpenAI(
    api_key=API_KEY or "dummy_key",
    base_url=BASE_URL,
)

# Описание инструментов (умный дом + управление медиа)
TOOLS = [
    # Инструменты лампы
    {
        "type": "function",
        "function": {
            "name": "turn_on_lamp",
            "description": "Включить освещение лампы.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "turn_off_lamp",
            "description": "Выключить освещение лампы.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "toggle_lamp",
            "description": "Переключить питание лампы (вкл/выкл).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_lamp_brightness",
            "description": "Установить процент яркости лампы от 1 до 100.",
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {
                        "type": "integer",
                        "description": "Яркость лампы (1-100).",
                    }
                },
                "required": ["level"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_lamp_color",
            "description": "Установить цвет лампы (по названию или через RGB). Вызывай при запросах на смену цвета: например, 'красный свет', 'сделай синий', 'зеленый свет', 'поставь фиолетовый'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "color": {
                        "type": "string",
                        "description": "Название цвета (например, 'красный', 'синий', 'зеленый', 'желтый', 'голубой', 'фиолетовый', 'оранжевый', 'розовый') или HEX (#FF0000).",
                    },
                    "red": {
                        "type": "integer",
                        "description": "Красный компонент RGB (0-255).",
                    },
                    "green": {
                        "type": "integer",
                        "description": "Зеленый компонент RGB (0-255).",
                    },
                    "blue": {
                        "type": "integer",
                        "description": "Синий компонент RGB (0-255).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_lamp_color_temp",
            "description": "Установить цветовую температуру белого света лампы в Кельвинах (1700-6500K). Вызывай для белого света: 'теплый свет' (2700-3000K), 'нейтральный/дневной свет' (4000K), 'холодный свет' (5500-6500K).",
            "parameters": {
                "type": "object",
                "properties": {
                    "kelvin": {
                        "type": "integer",
                        "description": "Цветовая температура в Кельвинах (от 1700 до 6500).",
                    }
                },
                "required": ["kelvin"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_lamp_status",
            "description": "Проверить текущее состояние лампы (включена ли, какая яркость, цвет или температура).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    # Инструменты управления музыкой на ПК
    {
        "type": "function",
        "function": {
            "name": "next_track",
            "description": "Переключить на следующий трек / песню на компьютере (скипнуть песню).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "prev_track",
            "description": "Переключить на предыдущий трек / песню на компьютере.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "play_pause_track",
            "description": "Поставить музыку на паузу или возобновить воспроизведение на компьютере.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

def execute_tool(name: str, arguments: dict) -> dict:
    """Выполняет вызов локального инструмента."""
    global lamp
    if name in (
        "turn_on_lamp",
        "turn_off_lamp",
        "toggle_lamp",
        "set_lamp_brightness",
        "set_lamp_color",
        "set_lamp_color_temp",
        "get_lamp_status",
    ):
        if lamp is None:
            try:
                lamp = LampController()
            except Exception as e:
                return {"status": "error", "message": f"Лампа недоступна: {e}"}

        if name == "turn_on_lamp":
            return lamp.turn_on()
        elif name == "turn_off_lamp":
            return lamp.turn_off()
        elif name == "toggle_lamp":
            return lamp.toggle()
        elif name == "set_lamp_brightness":
            return lamp.set_brightness(arguments.get("level", 100))
        elif name == "set_lamp_color":
            color = arguments.get("color")
            if color:
                return lamp.set_color(color)
            return lamp.set_rgb(
                arguments.get("red", 255),
                arguments.get("green", 255),
                arguments.get("blue", 255),
            )
        elif name == "set_lamp_color_temp":
            return lamp.set_color_temp(arguments.get("kelvin", 4000))
        elif name == "get_lamp_status":
            return lamp.get_status()

    elif name == "next_track":
        return pc.next_track()
    elif name == "prev_track":
        return pc.prev_track()
    elif name == "play_pause_track":
        return pc.play_pause()

    return {"status": "error", "message": f"Неизвестный инструмент: {name}"}

def format_tool_response(name: str, arguments: dict, result: dict) -> str:
    """Формирует быстрый ответ пользователю без повторного обращения к LLM (экономия запросов и ускорение в 2 раза)."""
    if result.get("status") == "error":
        return f"Не удалось выполнить действие: {result.get('message', 'ошибка')}"
    if name == "turn_on_lamp":
        return "Свет включен."
    elif name == "turn_off_lamp":
        return "Свет выключен."
    elif name == "toggle_lamp":
        return "Состояние света изменено."
    elif name == "set_lamp_brightness":
        return f"Яркость установлена на {arguments.get('level', 100)}%."
    elif name == "set_lamp_color":
        color = arguments.get("color")
        if color:
            return f"Цвет лампы изменен на {color}."
        r = arguments.get("red", 255)
        g = arguments.get("green", 255)
        b = arguments.get("blue", 255)
        return f"Цвет лампы установлен на RGB({r}, {g}, {b})."
    elif name == "set_lamp_color_temp":
        kelvin = arguments.get("kelvin", 4000)
        return f"Цветовая температура установлена на {kelvin}K."
    elif name == "get_lamp_status":
        power = "включена" if result.get("power") == "on" else "выключена"
        bright = result.get("brightness", "?")
        rgb = result.get("rgb")
        mode = result.get("color_mode")
        color_info = ""
        if mode == "rgb" and rgb:
            color_info = f", цвет RGB: {rgb}"
        elif mode == "color_temp" and result.get("color_temp"):
            color_info = f", темп: {result.get('color_temp')}K"
        return f"Лампа {power}, яркость: {bright}%{color_info}."
    elif name == "next_track":
        return "Включен следующий трек."
    elif name == "prev_track":
        return "Включен предыдущий трек."
    elif name == "play_pause_track":
        return "Воспроизведение переключено."
    return "Действие выполнено."

def try_fast_intent(text: str) -> str | None:
    """
    Быстрое локальное выполнение базовых команд за ~40 мс без обращения к LLM.
    Если команда распознана, возвращает готовый ответ. Если нет — возвращает None.
    """
    cmd = text.strip().lower()

    # 1. Включение / выключение лампы
    if re.search(r"\b(включи|зажги|зажечь|вруби|включить)\s+(свет|лампу|освещение)\b", cmd) or cmd in ("включи свет", "включи лампу", "свет включи"):
        res = execute_tool("turn_on_lamp", {})
        return format_tool_response("turn_on_lamp", {}, res)

    if re.search(r"\b(выключи|погаси|потуши|выруби|выключить)\s+(свет|лампу|освещение)\b", cmd) or cmd in ("выключи свет", "выключи лампу", "свет выключи"):
        res = execute_tool("turn_off_lamp", {})
        return format_tool_response("turn_off_lamp", {}, res)

    if re.search(r"\b(переключи|переключить)\s+(свет|лампу)\b", cmd) or cmd in ("переключи свет", "переключи лампу"):
        res = execute_tool("toggle_lamp", {})
        return format_tool_response("toggle_lamp", {}, res)

    # 2. Яркость
    bright_match = re.search(r"\b(?:яркость|яркости)\s+(?:на\s+)?(\d{1,3})\s*%?\b", cmd) or re.search(r"\bпоставь\s+(\d{1,3})\s*%\s*(?:яркост\w*)?\b", cmd)
    if bright_match:
        val = int(bright_match.group(1))
        if 1 <= val <= 100:
            res = execute_tool("set_lamp_brightness", {"level": val})
            return format_tool_response("set_lamp_brightness", {"level": val}, res)

    if "яркость на максимум" in cmd or "максимальная яркость" in cmd or "максимум яркости" in cmd:
        res = execute_tool("set_lamp_brightness", {"level": 100})
        return format_tool_response("set_lamp_brightness", {"level": 100}, res)

    if "яркость на минимум" in cmd or "минимальная яркость" in cmd or "минимум яркости" in cmd:
        res = execute_tool("set_lamp_brightness", {"level": 1})
        return format_tool_response("set_lamp_brightness", {"level": 1}, res)

    # 3. Цвета лампы
    colors_map = {
        "красный": "красный",
        "синий": "синий",
        "зеленый": "зеленый",
        "зелёный": "зеленый",
        "желтый": "желтый",
        "жёлтый": "желтый",
        "голубой": "голубой",
        "бирюзовый": "бирюзовый",
        "фиолетовый": "фиолетовый",
        "розовый": "розовый",
        "оранжевый": "оранжевый",
        "белый": "белый",
        "пурпурный": "пурпурный",
        "сиреневый": "сиреневый",
    }
    for c_word, c_name in colors_map.items():
        if re.search(rf"\b(сделай|включи|поставь)?\s*{c_word}(\s+(свет|цвет))?\b", cmd):
            res = execute_tool("set_lamp_color", {"color": c_name})
            return format_tool_response("set_lamp_color", {"color": c_name}, res)

    # 4. Цветовая температура
    if "теплый свет" in cmd or "тёплый свет" in cmd:
        res = execute_tool("set_lamp_color_temp", {"kelvin": 2700})
        return format_tool_response("set_lamp_color_temp", {"kelvin": 2700}, res)

    if "холодный свет" in cmd:
        res = execute_tool("set_lamp_color_temp", {"kelvin": 6000})
        return format_tool_response("set_lamp_color_temp", {"kelvin": 6000}, res)

    if "дневной свет" in cmd or "нейтральный свет" in cmd:
        res = execute_tool("set_lamp_color_temp", {"kelvin": 4000})
        return format_tool_response("set_lamp_color_temp", {"kelvin": 4000}, res)

    # 5. Статус
    if any(phrase in cmd for phrase in ("статус лампы", "состояние лампы", "что со светом", "лампа включена")):
        res = execute_tool("get_lamp_status", {})
        return format_tool_response("get_lamp_status", {}, res)

    # 6. Музыка на компьютере
    if any(phrase in cmd for phrase in ("следующий трек", "следующая песня", "скипни трек", "скип трек", "скип", "переключи трек", "переключи песню", "дальше")):
        res = execute_tool("next_track", {})
        return format_tool_response("next_track", {}, res)

    if any(phrase in cmd for phrase in ("предыдущий трек", "предыдущая песня", "назад трек", "предыдущий")):
        res = execute_tool("prev_track", {})
        return format_tool_response("prev_track", {}, res)

    if any(phrase in cmd for phrase in ("пауза", "поставь на паузу", "стоп музыка", "продолжи", "плей", "играть музыку", "сними с паузы", "возобнови")):
        res = execute_tool("play_pause_track", {})
        return format_tool_response("play_pause_track", {}, res)

    return None

SYSTEM_PROMPT = f"""Ты — ассистент по имени '{ASSISTANT_NAME.capitalize()}'.
Твои единственные обязанности:
1. Управление умным домом (физическая лампа: свет, яркость, цвет, цветовая температура, статус).
2. Управление музыкой на компьютере (переключение треков, пауза/плей).

Строгие правила:
- При командах управления светом или музыкой всегда вызывай соответствующий инструмент.
- Отвечай предельно лаконично.
"""

conversation_history = [
    {"role": "system", "content": SYSTEM_PROMPT}
]

def trim_history():
    """Ограничивает историю диалога последними 8 сообщениями для экономии токенов."""
    global conversation_history
    if len(conversation_history) > 9:
        # Сохраняем системный промпт и последние 8 сообщений
        conversation_history = [conversation_history[0]] + conversation_history[-8:]

def chat(user_text: str) -> str:
    """Обрабатывает входящую команду пользователя."""
    # 1. Быстрый локальный путь (Fast-path): 40 мс без сетевых задержек LLM
    fast_reply = try_fast_intent(user_text)
    if fast_reply is not None:
        print(f"[*] Локальное выполнение: \"{user_text}\" -> {fast_reply}")
        conversation_history.append({"role": "user", "content": user_text})
        conversation_history.append({"role": "assistant", "content": fast_reply})
        return fast_reply

    # 2. Интеллектуальный путь через Gemini LLM для сложных запросов
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
            raw_args = tool_call.function.arguments or "{}"
            try:
                fn_args = json.loads(raw_args)
            except Exception:
                fn_args = {}

            print(f"[*] Вызов действия: {fn_name}({fn_args})")
            tool_res = execute_tool(fn_name, fn_args)
            responses.append(format_tool_response(fn_name, fn_args, tool_res))

        answer = " ".join(responses)
        conversation_history.append({"role": "assistant", "content": answer})
        return answer

    conversation_history.append({"role": "assistant", "content": msg.content})
    return msg.content

def start_voice_mode():
    """Запуск голосового управления с постоянным прослушиванием микрофона."""
    from voice_controller import VoiceListener
    listener = VoiceListener(assistant_name=ASSISTANT_NAME)
    listener.run(chat)

def main():
    parser = argparse.ArgumentParser(description="Локальный ассистент умного дома")
    parser.add_argument(
        "--voice", "-v", action="store_true", help="Запустить сразу в режиме голосового управления"
    )
    args = parser.parse_args()

    if args.voice:
        start_voice_mode()
        return

    print("=" * 55)
    print(f" Локальный ассистент '{ASSISTANT_NAME.capitalize()}' готов к работе.")
    print(f" Модель: {MODEL_NAME}")
    print(f" Сервер: {BASE_URL}")
    print(" Сфера: умный дом + переключение музыки на ПК.")
    print(f" Имя для голосовой активации: '{ASSISTANT_NAME}'")
    print(" Для перехода в голосовой режим введите: 'голос' или 'voice'.")
    print(" Для выхода введите: exit или quit.")
    print("=" * 55)

    while True:
        try:
            user_input = input("\nВы: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "выход"):
                print(f"{ASSISTANT_NAME.capitalize()} отключен.")
                break
            if user_input.lower() in ("voice", "голос", "микрофон"):
                start_voice_mode()
                continue
            reply = chat(user_input)
            print(f"\n{ASSISTANT_NAME.capitalize()}:\n{reply}")
        except KeyboardInterrupt:
            print("\nСеанс завершен.")
            break
        except Exception as e:
            print(f"\n[Ошибка]: {e}")

if __name__ == "__main__":
    main()
