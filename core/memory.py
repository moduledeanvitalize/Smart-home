import json
import os
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
MEMORY_FILE = os.path.join(BASE_DIR, "data", "user_memory.json")

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

NOTES_FILE = os.path.join(BASE_DIR, "data", "notes.json")
DATE_FMT = "%Y-%m-%d %H:%M"

# Заметки нужны в основе как напоминалки
def save_notes(notes: list[dict]) -> bool:
    """Сохраняет список словарей с заметками на диск."""
    try:
        with open(NOTES_FILE, "w", encoding="utf-8") as f:
            json.dump(notes, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[!] Ошибка сохранения заметок: {e}")
        return False


def load_notes() -> list[dict]:
    """Загружает заметки и автоматически удаляет те, у которых истёк срок."""
    if not os.path.exists(NOTES_FILE):
        return []

    try:
        with open(NOTES_FILE, "r", encoding="utf-8") as f:
            notes = json.load(f)
    except Exception:
        return []

    now = datetime.now()
    active_notes = []
    changed = False

    for note in notes:
        exp_str = note.get("expires_at")
        if exp_str:
            try:
                if now >= datetime.strptime(exp_str, DATE_FMT):
                    changed = True
                    continue  # срок вышел — пропускаем заметку
            except ValueError:
                pass
        active_notes.append(note)

    # Если хоть одна заметка протухла и отсеялась — сразу обновляем файл
    if changed:
        save_notes(active_notes)

    return active_notes

def manage_notes(action: str, text: str = "", target: int | str | None = None, ttl_hours: int = 72) -> dict:
    """Единый диспетчер заметок: добавление, просмотр и удаление."""
    notes = load_notes()

    # 1. ДОБАВЛЕНИЕ
    if action == "add":
        clean_text = text.strip()
        if not clean_text:
            return {"status": "error", "message": "Текст заметки пустой."}

        # Находим следующий свободный ID
        next_id = max((n.get("id", 0) for n in notes), default=0) + 1
        expires_at = (datetime.now() + timedelta(hours=ttl_hours)).strftime(DATE_FMT)

        new_note = {
            "id": next_id,
            "text": clean_text,
            "expires_at": expires_at,
        }
        notes.append(new_note)
        save_notes(notes)
        return {"status": "success", "note": new_note}

    # 2. СПИСОК
    elif action == "list":
        return {"status": "success", "notes": notes}

    # 3. УДАЛЕНИЕ (по ID или по ключевому слову)
    elif action == "delete":
        if target is None or str(target).strip() == "":
            return {"status": "error", "message": "Не указано, какую заметку удалить."}

        target_str = str(target).strip().lower()
        updated_notes = []
        deleted_note = None

        for note in notes:
            # Если передали число (ID)
            if target_str.isdigit() and note.get("id") == int(target_str):
                deleted_note = note
                continue
            # Если передали текст/ключевое слово
            if not target_str.isdigit() and target_str in note.get("text", "").lower():
                deleted_note = note
                continue
            updated_notes.append(note)

        if not deleted_note:
            return {"status": "error", "message": f"Заметка '{target}' не найдена."}

        save_notes(updated_notes)
        return {"status": "success", "deleted": deleted_note}

    return {"status": "error", "message": f"Неизвестное действие с заметками: {action}"}