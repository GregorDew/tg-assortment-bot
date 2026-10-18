import html
import json
import re
from typing import Any, Dict, List

# Регулярний вираз для знаходження {field_name} або {field_name|default_val}
VAR_PATTERN = re.compile(r"\{([a-zA-Z0-9_\.\-]+)(?:\|([^}]*))?\}")


def extract_template_variables(template_text: str) -> List[str]:
    """Витягує список усіх імен змінних, що використовуються у шаблоні."""
    if not template_text:
        return []
    matches = VAR_PATTERN.findall(template_text)
    seen = set()
    result = []
    for var_name, _ in matches:
        if var_name not in seen:
            seen.add(var_name)
            result.append(var_name)
    return result


def render_template(
    template_text: str,
    data: Dict[str, Any],
    escape_for_html: bool = False
) -> str:
    """
    Безпечно рендерить текст повідомлення з підстановкою значень полів.
    Виконання довільного програмного коду повністю виключено.
    """
    if not template_text:
        return ""

    def replace_match(match: re.Match) -> str:
        var_name = match.group(1)
        default_val = match.group(2) if match.group(2) is not None else ""

        val = data.get(var_name)
        if val is None or val == "":
            res = default_val
        else:
            res = str(val)

        if escape_for_html:
            return html.escape(res)
        return res

    return VAR_PATTERN.sub(replace_match, template_text)


def render_json_template(template_json_str: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Рендерить шаблон тіла запиту для HTTP API.
    Якщо це валідний JSON-рядок з плейсхолдерами, підставляє значення та парсить у dict.
    """
    if not template_json_str:
        return data

    try:
        # 1. Якщо передано валідний JSON, спробуємо зробити заміну всередині
        rendered_str = render_template(template_json_str, data, escape_for_html=False)
        return json.loads(rendered_str)
    except Exception:
        # Якщо шаблон не валідний JSON напряму, повертаємо словник даних
        return data


def render_discord_embed(
    title_template: str | None,
    body_template: str | None,
    extra_config: Dict[str, Any] | None,
    data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Формує структуру Discord Embed на основі шаблону та даних.
    """
    extra = extra_config or {}
    title = render_template(title_template or "", data, escape_for_html=False).strip()
    description = render_template(body_template or "", data, escape_for_html=False).strip()

    embed: Dict[str, Any] = {}
    if title:
        embed["title"] = title
    if description:
        embed["description"] = description

    # Колір embed (десяткове або hex число)
    color = extra.get("color", 0x3498DB)
    if isinstance(color, str) and color.startswith("#"):
        try:
            color = int(color[1:], 16)
        except ValueError:
            color = 0x3498DB
    embed["color"] = color

    # Фото / Зображення
    image_field = extra.get("image_field")
    if image_field and data.get(image_field):
        embed["image"] = {"url": str(data[image_field])}
    elif extra.get("image_url"):
        embed["image"] = {"url": render_template(extra["image_url"], data)}

    # Додаткові поля (Embed Fields)
    fields_config = extra.get("fields", [])
    if isinstance(fields_config, list) and fields_config:
        rendered_fields = []
        for f in fields_config:
            f_name = render_template(f.get("name", ""), data).strip()
            f_val = render_template(f.get("value", ""), data).strip()
            if f_name and f_val:
                rendered_fields.append({
                    "name": f_name,
                    "value": f_val,
                    "inline": f.get("inline", True)
                })
        if rendered_fields:
            embed["fields"] = rendered_fields

    # Footer
    footer_text = extra.get("footer_text")
    if footer_text:
        embed["footer"] = {"text": render_template(footer_text, data)}

    return embed
