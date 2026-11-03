import inspect
from typing import Any, Callable

# Сюда автоматически собираются описания для нейросети
TOOLS_SCHEMA: list[dict] = []

# Сюда автоматически собираются функции: {name: (func, response_template)}
TOOL_HANDLERS: dict[str, tuple[Callable, Any]] = {}


def register_tool(
    name: str,
    description: str,
    parameters: dict,
    response_template: Any = "Выполнено.",
):
  """Декоратор: берет функцию и сама прописывает её в схему для LLM и словарь обработчиков."""

  def decorator(func: Callable):
    schema = {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }
    TOOLS_SCHEMA.append(schema)
    TOOL_HANDLERS[name] = (func, response_template)
    return func

  return decorator


def execute_tool(name: str, arguments: dict) -> Any:
  """Вызывает функцию инструмента, передавая только нужные аргументы."""
  if name not in TOOL_HANDLERS:
    return {"status": "error", "message": f"Неизвестный инструмент: {name}"}

  func, _ = TOOL_HANDLERS[name]
  try:
    # Защита от лишних аргументов модели
    sig = inspect.signature(func)
    has_kwargs = any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )
    if has_kwargs:
      return func(**arguments)

    filtered_args = {k: v for k, v in arguments.items() if k in sig.parameters}
    return func(**filtered_args)
  except Exception as e:
    return {"status": "error", "message": str(e)}


def format_tool_response(name: str, arguments: dict, result: dict) -> str:
  """Формирует текстовый ответ для Руслана."""
  if name not in TOOL_HANDLERS:
    return "Действие выполнено."

  _, template = TOOL_HANDLERS[name]

  if callable(template):
    try:
      return template(arguments, result)
    except Exception:
      return "Действие выполнено."

  if isinstance(template, str):
    try:
      format_data = {**arguments}
      if isinstance(result, dict):
        format_data.update(result)
      return template.format(**format_data)
    except Exception:
      return template

  return "Действие выполнено."