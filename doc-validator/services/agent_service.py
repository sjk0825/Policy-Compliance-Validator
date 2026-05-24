import logging
import sys
import os
from typing import Optional
from agent import AgentOrchestrator, Brain


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("doc_validator")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        ))
        logger.addHandler(handler)

        os.makedirs("logs", exist_ok=True)
        file_handler = logging.FileHandler("logs/streamlit_errors.log", encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        ))
        logger.addHandler(file_handler)

    return logger


def initialize_agent(provider: str, api_key: str, base_url: Optional[str] = None) -> AgentOrchestrator:
    brain = Brain(provider=provider, api_key=api_key, base_url=base_url)
    agent = AgentOrchestrator(brain=brain)
    return agent


def build_retriever(algorithm: str, api_key: str):
    raise NotImplementedError("Retrieval is not yet activated.")
