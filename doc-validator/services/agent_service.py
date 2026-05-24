import logging
import sys
import os
from typing import Optional, List
from agent import AgentOrchestrator, Brain
from agent.tools import BaseTool, StockChartTool


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


def initialize_agent(provider: str, api_key: str, base_url: Optional[str] = None,
                     tools: Optional[List[BaseTool]] = None) -> AgentOrchestrator:
    brain = Brain(provider=provider, api_key=api_key, base_url=base_url)
    agent = AgentOrchestrator(brain=brain)

    if tools:
        for tool in tools:
            agent.add_tool(tool)

    return agent


def build_retriever(algorithm: str, api_key: str):
    raise NotImplementedError("Retrieval is not yet activated.")
