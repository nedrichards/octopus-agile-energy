"""Render trusted Pango markup templates with escaped interpolated values."""

from html import escape
from string.templatelib import Interpolation, Template, convert


def markup(template: Template) -> str:
    """Keep literal markup; format and escape every interpolation as text.

    Use a t-string with trusted literal tags. Interpolated values cannot insert
    markup, including when using conversions or format specifications.
    """
    parts = []
    for part in template:
        if isinstance(part, Interpolation):
            value = convert(part.value, part.conversion)
            parts.append(escape(format(value, part.format_spec)))
        else:
            parts.append(part)
    return "".join(parts)
