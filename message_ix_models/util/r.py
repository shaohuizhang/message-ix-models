"""Utilities for compatibility with R code."""
import re

from .common import MESSAGE_DATA_PATH, MESSAGE_MODELS_PATH

_SOURCED = set()


def source_module(path):
    from rpy2.robjects import r

    path_parts = path.split(".")
    package = (
        path_parts.pop(0)
        if re.match("message_(data|ix_models)", path_parts[0])
        else "message_ix_models"
    )

    path = (
        {
            "message_data": MESSAGE_DATA_PATH,
            "message_ix_models": MESSAGE_MODELS_PATH,
        }[package]
        .joinpath(*path_parts)
        .with_suffix(".R")
    )

    if path not in _SOURCED:
        _SOURCED.add(path)
        r.source(str(path))


def get_r_func(path):
    from rpy2.robjects import r

    path, name = path.rsplit(":", maxsplit=1)

    source_module(path)

    return r[name]