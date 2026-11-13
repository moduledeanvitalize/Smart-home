import argparse
import time
import json
import logging
import os
import re
from openai import OpenAI


import config
from controllers.device_con.LampManager import PRESET_COLORS
from core import memory
from core import tools_impl  # Загружает все функции и регистрирует их
from core.tools_registry import TOOLS_SCHEMA as TOOLS
from core.tools_registry import execute_tool, format_tool_response

# Настройка логирования
os.makedirs("logs", exist_ok=True)
logger = logging.getLogger("SmartHome")
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)

file_handler = logging.FileHandler(
    os.path.join("logs", "llm.log"), encoding="utf-8"
)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(formatter)

if not logger.handlers:
  logger.addHandler(console_handler)
  logger.addHandler(file_handler)

client = OpenAI(
    api_key=config.LLM_API_KEY or "dummy_key",
    base_url=config.LLM_BASE_URL,
    timeout=15.0,
    max_retries=1,
)


def parse_room_from_text(cmd: str) -> str:
  if any(
      w in cmd
      for w in (
          "везде",
          "весь свет",
          "все лампы",
          "во всей квартире",
          "всех комнатах",
      )
  ):
    return "все"
  if any(w in cmd for w in ("кухн", "кухне", "кухню")):
    return "кухня"
  if any(w in cmd for w in ("ванн", "сануз", "туалет")):
    return "ванная"
  if any(w in cmd for w in ("прихож", "коридор")):
    return "прихожая"
  return "спальня"


TEMP_RULES = [
    (re.compile(r"тепл\w*\s+(?:бел\w*\s+)?свет|тепл\w*\s+бел\w*"), 2700),
    (re.compile(r"холодн\w*\s+(?:бел\w*\s+)?свет|холодн\w*\s+бел\w*"), 6000),
    (re.compile(r"(?:дневн|нейтральн)\w*\s+свет"), 4000),
]

_RU_COLORS = sorted(
    [c for c in PRESET_COLORS if re.fullmatch(r"[а-я]+", c)],
    key=len,
    reverse=True,
)
_COLOR_RE = re.compile(
    r"\b(?:сделай|включи|поставь|установи|зажги)\s+(?:\w+\s+){0,2}("
    + "|".join(_RU_COLORS)
    + r")\b"
)

_BRIGHTNESS_RE = re.compile(
    r"(?:яркость\w*\s*(?:на|до)?\s*(\d{1,3})|свет\w*\s+на\s+(\d{1,3})\s*%?)"
)


def try_fast_intent(text: str) -> str | None:
  cmd = text.strip().lower().replace("ё", "е")

  if len(cmd.split()) > 7 or re.search(r"\b(и|потом|заодно)\b", cmd):
    return None

  room = parse_room_from_text(cmd)

  # Мультимедиа и громкость
  if any(w in cmd for w in ("следующий трек", "следующую песню", "переключи трек", "скипни трек")):
      return format_tool_response("control_media", {"action": "next"}, execute_tool("control_media", {"action": "next"}))

  if any(w in cmd for w in ("предыдущий трек", "предыдущую песню", "назад трек")):
      return format_tool_response("control_media", {"action": "prev"}, execute_tool("control_media", {"action": "prev"}))

  if any(w in cmd for w in ("поставь на паузу", "пауза", "продолжи музыку", "включи музыку", "стоп музыка")):
      return format_tool_response("control_media", {"action": "play_pause"}, execute_tool("control_media", {"action": "play_pause"}))

  if any(w in cmd for w in ("погромче", "прибавь звук", "громче")):
      return format_tool_response("control_media", {"action": "volume_up", "steps": 5}, execute_tool("control_media", {"action": "volume_up", "steps": 5}))

  if any(w in cmd for w in ("потише", "убавь звук", "тише")):
      return format_tool_response("control_media", {"action": "volume_down", "steps": 5}, execute_tool("control_media", {"action": "volume_down", "steps": 5}))

  if any(w in cmd for w in ("заглуши звук", "без звука", "выключи звук")):
      return format_tool_response("control_media", {"action": "mute"}, execute_tool("control_media", {"action": "mute"}))

  # Лампы
  if any(v in cmd for v in ("включи свет", "вруби свет", "зажги свет", "включи лампу", "включи все", "включи везде")):
    return format_tool_response("lamp_control", {"action": "on", "room": room}, execute_tool("lamp_control", {"action": "on", "room": room}))

  if any(v in cmd for v in ("выключи свет", "выруби свет", "погаси свет", "потуши свет", "выключи лампу", "выключи все", "выключи везде")):
    return format_tool_response("lamp_control", {"action": "off", "room": room}, execute_tool("lamp_control", {"action": "off", "room": room}))

  brightness_match = _BRIGHTNESS_RE.search(cmd)
  if brightness_match:
    raw_value = brightness_match.group(1) or brightness_match.group(2)
    level = max(1, min(100, int(raw_value)))
    args = {"action": "brightness", "level": level, "room": room}
    return format_tool_response("lamp_control", args, execute_tool("lamp_control", args))

  for pattern, kelvin in TEMP_RULES:
    if pattern.search(cmd):
      return format_tool_response("lamp_control", {"action": "color_temp", "kelvin": kelvin}, execute_tool("lamp_control", {"action": "color_temp", "kelvin": kelvin}))

  color_match = _COLOR_RE.search(cmd)
  if color_match:
    color_val = color_match.group(1)
    res = tools_impl.devices.set_color(color_val, room)
    if res.get("status") != "success":
      return res.get("message", "Не удалось изменить цвет лампы.")
    return f"Свет в {room} установлен на цвет {color_val}."
  return None


def build_system_prompt() -> str:
  memories = memory.load_memory()
  memory_block = ""
  if memories:
    formatted_notes = "\n".join(f"- {note}" for note in memories)
    memory_block = f"\n\nФАКТЫ И ПРЕДПОЧТЕНИЯ ПОЛЬЗОВАТЕЛЯ:\n{formatted_notes}"

  return f"""Ты — домашний голосовой ассистент по имени Ишак.
Твой характер: ироничный, сообразительный, полезный друг.

ПРАВИЛА РАБОТЫ:
1. Если запрос связан со светом, музыкой, громкостью или ПК — обязательно вызывай нужные tools.
2. Если пользователь говорит запомнить какую-то деталь о себе, привычках или настройках — вызывай инструмент 'remember_user_preference'.
3. Формулируй ответы лаконично (1–3 предложения для озвучки голосом).{memory_block}
4. Когда в диалоге присутствуют результаты выполнения инструментов (роль tool), действие УЖЕ завершено. Твоя задача на этом шаге — ТОЛЬКО сформулировать короткий живой ответ пользователю голосом (1–2 предложения). КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО вызывать инструменты повторно, переводить параметры на английский или выводить теги вызовов
"""


conversation_history = [{"role": "system", "content": build_system_prompt()}]


def trim_history():
  global conversation_history
  if len(conversation_history) > 9:
    conversation_history = [conversation_history[0]] + conversation_history[-8:]


def chat(user_text: str) -> str:
  fast_reply = try_fast_intent(user_text)
  if fast_reply is not None:
    conversation_history.append({"role": "user", "content": f"[{time.strftime('%H:%M')}] {user_text}"})
    conversation_history.append({"role": "assistant", "content": fast_reply})
    trim_history()
    return fast_reply

  conversation_history[0]["content"] = build_system_prompt()
  conversation_history.append({"role": "user", "content": f"[{time.strftime('%H:%M')}] {user_text}"})
  trim_history()

  logger.info("Отправка запроса 1 в LLM (выбор инструментов)...")

  try:
    response = client.chat.completions.create(
        model=getattr(config, "LLM_MODEL", "deepseek-chat"),
        messages=conversation_history,
        tools=TOOLS,
        tool_choice="auto",
    )

    # Лог расхода токенов и кэша для Запроса 1
    usage = response.usage
    if usage:
      prompt_tokens = getattr(usage, "prompt_tokens", 0)
      completion_tokens = getattr(usage, "completion_tokens", 0)
      details = getattr(usage, "prompt_tokens_details", None)
      cached = getattr(details, "cached_tokens", 0) if details else 0
      if not cached:
        cached = getattr(usage, "prompt_cache_hit_tokens", 0)

      logger.info(
          "[Шаг 1] Токены: Ввод=%d | Кэш=%d (%.1f%%) | Вывод=%d",
          prompt_tokens,
          cached,
          (cached / prompt_tokens * 100) if prompt_tokens else 0,
          completion_tokens,
      )
      
  except Exception as e:
    logger.error("Ошибка при обращении к LLM: %s", e)
    return "Не удалось связаться с сервером."

  msg = response.choices[0].message

  # Если модель ничего вызывать не захотела, а сразу ответила
  if not msg.tool_calls:
    answer = msg.content or "Слушаю."
    conversation_history.append({"role": "assistant", "content": answer})
    trim_history()
    return answer

  # Модель вернула вызовы инструментов
  conversation_history.append(msg.model_dump(exclude_unset=True))

  executed_summaries = []
  for tool_call in msg.tool_calls:
    fn_name = tool_call.function.name
    try:
      fn_args = json.loads(tool_call.function.arguments or "{}")
    except Exception:
      fn_args = {}

    logger.info("Выполняю инструмент: %s с аргументами %s", fn_name, fn_args)
    tool_result = execute_tool(fn_name, fn_args)

    conversation_history.append({
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": (
            json.dumps(tool_result, ensure_ascii=False)
            if isinstance(tool_result, (dict, list))
            else str(tool_result)
        ),
    })

    executed_summaries.append(
        format_tool_response(fn_name, fn_args, tool_result)
    )

  # --- ЗАПРОС 2: Отправка результатов работы тулсов обратно ---
  logger.info("Отправка запроса 2 в LLM (подведение итогов)...")
  try:
    final_response = client.chat.completions.create(
        model=getattr(config, "LLM_MODEL", "deepseek-chat"),
        messages=conversation_history,
    )

    usage2 = final_response.usage
    if usage2:
      prompt_tokens2 = getattr(usage2, "prompt_tokens", 0)
      completion_tokens2 = getattr(usage2, "completion_tokens", 0)
      details2 = getattr(usage2, "prompt_tokens_details", None)
      cached2 = getattr(details2, "cached_tokens", 0) if details2 else 0
      if not cached2:
        cached2 = getattr(usage2, "prompt_cache_hit_tokens", 0)

      logger.info(
          "[Шаг 2] Токены: Ввод=%d | Кэш=%d (%.1f%%) | Вывод=%d",
          prompt_tokens2,
          cached2,
          (cached2 / prompt_tokens2 * 100) if prompt_tokens2 else 0,
          completion_tokens2,
      )

    final_text = final_response.choices[0].message.content or "Сделано."
    conversation_history.append({"role": "assistant", "content": final_text})
    trim_history()
    return final_text
  except Exception as e:
    logger.error("Ошибка во 2-м запросе: %s", e)
    fallback_answer = " ".join(executed_summaries)
    conversation_history.append(
        {"role": "assistant", "content": fallback_answer}
    )
    trim_history()
    return fallback_answer


def start_voice_mode():
  from controllers.voice_controller import VoiceListener

  listener = VoiceListener(assistant_name=config.ASSISTANT_NAME.capitalize())
  listener.run(chat)


def main():
  parser = argparse.ArgumentParser(description="Ассистент умного дома")
  parser.add_argument(
      "--voice", "-v", action="store_true", help="Голосовой режим"
  )
  args = parser.parse_args()

  if args.voice:
    start_voice_mode()
    return

  print("=" * 55)
  print(f" Ассистент '{config.ASSISTANT_NAME.capitalize()}' готов к работе.")
  print(" Лампы, ПК, громкость, запуск приложений и память подключены.")
  print("=" * 55)

  while True:
    try:
      inp = input("\nВы: ").strip()
      if not inp:
        continue
      if inp.lower() in ("exit", "quit", "выход"):
        break
      if inp.lower() in ("voice", "голос", "микрофон"):
        start_voice_mode()
        continue
      print(f"\n{config.ASSISTANT_NAME.capitalize()}:\n{chat(inp)}")
    except KeyboardInterrupt:
      break


if __name__ == "__main__":
  main()