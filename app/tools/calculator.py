from __future__ import annotations

import ast
import math
import operator
import statistics
from collections.abc import Callable
from typing import Any

_BINARY: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY: dict[type[ast.unaryop], Callable[[Any], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "len": len,
    "mean": statistics.mean,
    "median": statistics.median,
    "stdev": statistics.stdev,
    "pstdev": statistics.pstdev,
    "sqrt": math.sqrt,
    "log": math.log,
    "exp": math.exp,
}


def calculate(expression: str) -> Any:
    """Evaluate arithmetic and basic statistics without Python eval."""
    if len(expression) > 4_000:
        raise ValueError("Expression is too long")
    tree = ast.parse(expression, mode="eval")
    return _evaluate(tree.body)


def _evaluate(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, str, bool)):
        return node.value
    if isinstance(node, ast.List):
        return [_evaluate(item) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_evaluate(item) for item in node.elts)
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and abs(float(right)) > 100:
            raise ValueError("Exponent is too large")
        return _BINARY[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_evaluate(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        function = _FUNCTIONS.get(node.func.id)
        if function is None or node.keywords:
            raise ValueError("Function is not allowed")
        return function(*[_evaluate(argument) for argument in node.args])
    raise ValueError(f"Unsupported expression: {type(node).__name__}")
