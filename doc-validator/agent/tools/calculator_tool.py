import math
import re
from typing import Any, Union
from .base import BaseTool, ToolResult, ToolDefinition, ToolCapability


class CalculatorTool(BaseTool):
    SAFE_OPERATORS = {
        "+": lambda a, b: a + b,
        "-": lambda a, b: a - b,
        "*": lambda a, b: a * b,
        "/": lambda a, b: a / b if b != 0 else "division by zero",
        "**": lambda a, b: a ** b,
        "%": lambda a, b: a % b,
    }

    SAFE_FUNCTIONS = {
        "sqrt": math.sqrt,
        "abs": abs,
        "round": round,
        "min": min,
        "max": max,
        "sum": sum,
        "len": len,
        "log": math.log,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
    }

    def __init__(self):
        super().__init__()

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="calculator",
            description="수학적 계산 및 연산 수행",
            capabilities=[ToolCapability.CALCULATION],
            parameters={
                "required": ["expression"],
                "properties": {
                    "expression": {"type": "string", "description": "계산식 (예: 2+2, sqrt(16))"},
                    "precision": {"type": "integer", "description": "소수점 정밀도", "default": 6}
                }
            }
        )

    def execute(self, expression: str, precision: int = 6) -> ToolResult:
        try:
            result = self._evaluate(expression, precision)
            return ToolResult(
                success=True,
                data={"expression": expression, "result": result},
                metadata={
                    "tool": "calculator",
                    "action": "calculate"
                }
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    def _evaluate(self, expression: str, precision: int) -> Union[float, str]:
        expression = expression.strip()
        
        if expression.replace(" ", "").replace(".", "").replace("-", "").isdigit():
            return float(expression)

        for func_name, func in self.SAFE_FUNCTIONS.items():
            pattern = rf"{func_name}\s*\(\s*(-?\d+\.?\d*)\s*\)"
            match = re.search(pattern, expression, re.IGNORECASE)
            if match:
                value = float(match.group(1))
                result = func(value)
                if isinstance(result, float):
                    return round(result, precision)
                return result

        for op, func in self.SAFE_OPERATORS.items():
            if op in expression:
                parts = expression.split(op)
                if len(parts) == 2:
                    try:
                        a, b = float(parts[0].strip()), float(parts[1].strip())
                        result = func(a, b)
                        if isinstance(result, float):
                            return round(result, precision)
                        return result
                    except ValueError:
                        continue

        raise ValueError(f"Cannot evaluate expression: {expression}")
