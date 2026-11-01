import json
import os

MEMORY_FILE = os.path.join(os.path.dirname(__file__), "user_memory.json")


def load_memory() -> list[str]:
  """Загружает список сохраненных заметок."""
  if not os.path.exists(MEMORY_FILE):
    return []
  try:
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
      return json.load(f)
  except Exception:
    return []


def save_fact(fact: str) -> str:
  """Сохраняет новый факт о пользователе в JSON."""
  fact_clean = fact.strip()
  if not fact_clean:
    return "Пустой факт не сохранен."

  memories = load_memory()
  if fact_clean not in memories:
    memories.append(fact_clean)
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
      json.dump(memories, f, ensure_ascii=False, indent=2)
    return f"Запомнил: {fact_clean}"
  return "Этот факт уже был записан ранее."