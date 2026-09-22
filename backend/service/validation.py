"""Проверка ответа модели: шлюз может проигнорировать response_format."""

import json
import math

from ..core.errors import UpstreamError


def validate_extracted_fields(result, schema):
    def unique_object(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("Duplicate JSON key")
            obj[key] = value
        return obj

    def validate(value, node):
        types = node["type"] if isinstance(node["type"], list) else [node["type"]]
        if value is None and "null" in types:
            return
        kind = types[0]
        if kind == "object":
            if not isinstance(value, dict) or set(value) != set(node["required"]):
                raise ValueError("Incorrect field names")
            for name, child in node["properties"].items():
                validate(value[name], child)
        elif kind == "array":
            if not isinstance(value, list):
                raise ValueError("Expected array")
            for item in value:
                validate(item, node["items"])
        elif kind == "string" and isinstance(value, str):
            return
        elif kind == "boolean" and type(value) is bool:
            return
        elif kind in {"integer", "number"} and type(value) in {int, float} and math.isfinite(value):
            if kind == "integer" and value != int(value):
                raise ValueError("Expected integer")
        else:
            raise ValueError("Incorrect field type")

    try:
        value = json.loads(result, object_pairs_hook=unique_object)
        validate(value, schema)
    except (ValueError, TypeError, OverflowError, RecursionError) as error:
        raise UpstreamError("Ответ модели не соответствует JSON Schema: проверьте поля, типы данных и вложенную структуру.") from error


def result_fields(result):
    """Структурированный результат раскладывается в поля документа."""
    try:
        value = json.loads(result)
        return value if isinstance(value, dict) else {"result": value}
    except ValueError:
        return {}
