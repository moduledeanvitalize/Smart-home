import json
import os
import re
import time
from typing import Any

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
SCENARIOS_FILE = os.path.join(BASE_DIR, "data", "scenarios.json")


def load_scenarios() -> dict:
  """Загружает все сценарии из JSON-файла."""
  if not os.path.exists(SCENARIOS_FILE):
    return {}
  try:
    with open(SCENARIOS_FILE, "r", encoding="utf-8") as f:
      return json.load(f)
  except Exception:
    return {}


def save_scenarios(scenarios: dict) -> bool:
  """Сохраняет словарь сценариев на диск."""
  try:
    with open(SCENARIOS_FILE, "w", encoding="utf-8") as f:
      json.dump(scenarios, f, ensure_ascii=False, indent=2)
    return True
  except Exception as e:
    print(f"[!] Ошибка сохранения сценариев: {e}")
    return False


def run_scenario(name: str, execute_tool_func) -> dict[str, Any]:
  """Запускает цепочку действий из указанного сценария."""
  scenarios = load_scenarios()
  clean_name = name.strip().lower()

  if clean_name not in scenarios:
    return {
        "status": "error",
        "message": f"Сценарий '{clean_name}' не найден. Доступные: {list(scenarios.keys())}",
    }

  steps = scenarios[clean_name]
  executed_steps = []

  for step in steps:
    tool_name = step.get("tool")
    args = step.get("args", {})
    delay = step.get("delay", 0)

    if tool_name:
      result = execute_tool_func(tool_name, args)
      executed_steps.append({"tool": tool_name, "result": result})

    if delay > 0:
      time.sleep(delay)

  return {
      "status": "success",
      "scenario": clean_name,
      "steps_count": len(executed_steps),
  }


def add_scenario(name: str, steps: list[dict]) -> dict[str, Any]:
  """Добавляет новый сценарий или обновляет существующий."""
  clean_name = name.strip().lower()
  if not clean_name or not steps:
    return {"status": "error", "message": "Имя или список шагов пустые"}

  scenarios = load_scenarios()
  scenarios[clean_name] = steps

  if save_scenarios(scenarios):
    return {"status": "success", "scenario": clean_name}
  return {"status": "error", "message": "Не удалось записать в файл"}

def find_scenario_in_text(text: str) -> str | None:
  """Проверяет, упоминается ли в тексте какой-либо из сохранённых сценариев."""
  scenarios = load_scenarios()
  if not scenarios:
    return None

  clean_text = text.lower().replace("ё", "е")

  # Сортируем имена по длине (убывание), чтобы составные имена ("кино вечер")
  # проверялись раньше коротких ("кино")
  for name in sorted(scenarios.keys(), key=len, reverse=True):
    # Ищем имя сценария как отдельное слово или после ключевых слов
    pattern = rf"\b(?:сценарий|режим|запусти|включи|активируй)?\s*{re.escape(name)}\b"
    if re.search(pattern, clean_text):
      return name

  return None