from importlib import import_module
from types import ModuleType


def get_prompts(version: str) -> ModuleType:
    try:
        return import_module(f"app.prompts.{version}")
    except ModuleNotFoundError as error:
        raise ValueError(f"Versão de prompt desconhecida: {version}") from error
