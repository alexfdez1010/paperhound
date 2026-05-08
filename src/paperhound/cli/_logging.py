"""CLI logging configuration.

Default mode silences third-party loggers (docling, httpx, transformers, …)
and tqdm progress bars so that piping ``paperhound`` into another LLM does
not pollute its context window. ``--verbose`` switches to DEBUG-level output.
"""

from __future__ import annotations

import logging
import os
import warnings

# Loggers that are noisy by default — silenced unless ``--verbose``. docling
# alone emits dozens of INFO lines per PDF (page processing, model loads, OCR
# fallbacks); httpx logs every request. Stdout/stderr leakage corrupts the
# context window when the CLI is invoked from another LLM.
NOISY_LOGGERS: tuple[str, ...] = (
    "docling",
    "docling_core",
    "docling_ibm_models",
    "docling_parse",
    "httpx",
    "httpcore",
    "urllib3",
    "PIL",
    "huggingface_hub",
    "transformers",
    "torch",
    "matplotlib",
    "filelock",
    "fsspec",
    "asyncio",
)


def configure_logging(verbose: bool) -> None:
    """Set up logging + library output for the requested verbosity.

    Default (``verbose=False``): suppress 3rd-party logs and tqdm progress
    bars. Only ERROR-level records from paperhound itself reach stderr.

    ``--verbose``: route everything at DEBUG to stderr.
    """
    if verbose:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(levelname)s %(name)s: %(message)s",
            force=True,
        )
        for name in NOISY_LOGGERS:
            logging.getLogger(name).setLevel(logging.NOTSET)
        return

    # tqdm checks the env var at bar instantiation. Setting it before docling
    # is imported (docling import is lazy in convert.py) silences the bars.
    os.environ.setdefault("TQDM_DISABLE", "1")
    warnings.filterwarnings("ignore")
    logging.basicConfig(
        level=logging.ERROR,
        format="%(levelname)s %(name)s: %(message)s",
        force=True,
    )
    for name in NOISY_LOGGERS:
        lib_logger = logging.getLogger(name)
        lib_logger.setLevel(logging.CRITICAL)
        lib_logger.propagate = False
