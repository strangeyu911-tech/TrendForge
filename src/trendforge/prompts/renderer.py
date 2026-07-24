"""Prompt 渲染器 — Jinja2 模板渲染"""
from __future__ import annotations
from jinja2 import Environment, BaseLoader, StrictUndefined


_env = Environment(loader=BaseLoader(), undefined=StrictUndefined, autoescape=False)


def render(template_text: str, variables: dict) -> str:
    """渲染 Prompt 模板"""
    tpl = _env.from_string(template_text)
    return tpl.render(**variables)
