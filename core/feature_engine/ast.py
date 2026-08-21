from __future__ import annotations

import ast as py_ast
import json
import re
from dataclasses import dataclass, field
from typing import Any

from .exceptions import FeatureSpecInvalid

ALIASES={"SAFE_DIVIDE":"SAFE_DIV","SAFEDIV":"SAFE_DIV","MISSING":"MISSING_FLAG","AND":"BOOLEAN_AND"}
COMPARE={py_ast.Eq:"EQ",py_ast.NotEq:"NE",py_ast.Gt:"GT",py_ast.GtE:"GE",py_ast.Lt:"LT",py_ast.LtE:"LE",py_ast.In:"IN"}
FORBIDDEN=("__","lambda","import ","from ","df[","system(","subprocess","open(","compile(","globals(","locals(",";","\n")


@dataclass(frozen=True)
class Node:
    node_type: str
    def to_dict(self) -> dict[str,Any]: return {"node_type":self.node_type}

@dataclass(frozen=True)
class FieldNode(Node):
    name: str
    def __init__(self,name):object.__setattr__(self,"node_type","FIELD");object.__setattr__(self,"name",name)
    def to_dict(self):return {"node_type":self.node_type,"name":self.name}

@dataclass(frozen=True)
class ConstantNode(Node):
    value: Any
    def __init__(self,value):object.__setattr__(self,"node_type","CONSTANT");object.__setattr__(self,"value",value)
    def to_dict(self):return {"node_type":self.node_type,"value":self.value}

@dataclass(frozen=True)
class WindowNode(Node):
    value: str
    def __init__(self,value):object.__setattr__(self,"node_type","WINDOW");object.__setattr__(self,"value",value.lower())
    def to_dict(self):return {"node_type":self.node_type,"value":self.value}

@dataclass(frozen=True)
class ConditionNode(Node):
    op: str; args: tuple[Node,...]
    def __init__(self,op,args):object.__setattr__(self,"node_type","CONDITION");object.__setattr__(self,"op",op);object.__setattr__(self,"args",tuple(args))
    def to_dict(self):return {"node_type":self.node_type,"op":self.op,"args":[x.to_dict() for x in self.args]}

@dataclass(frozen=True)
class OperatorNode(Node):
    op: str; args: tuple[Node,...]; kwargs: tuple[tuple[str,Node],...] = field(default_factory=tuple)
    def __init__(self,op,args,kwargs=None):object.__setattr__(self,"node_type","OPERATOR");object.__setattr__(self,"op",ALIASES.get(op.upper(),op.upper()));object.__setattr__(self,"args",tuple(args));object.__setattr__(self,"kwargs",tuple(sorted((kwargs or {}).items())))
    def to_dict(self):return {"node_type":self.node_type,"op":self.op,"args":[x.to_dict() for x in self.args],"kwargs":{k:v.to_dict() for k,v in self.kwargs}}


def normalize_expression(expression: str) -> str:
    value=expression.strip(); value=re.sub(r"\bAND\b","and",value,flags=re.I)
    value=re.sub(r"\bOR\b","or",value,flags=re.I)
    return value


def parse_expression(expression: str) -> Node:
    if not expression or any(x in expression.lower() for x in FORBIDDEN):raise FeatureSpecInvalid("Unsafe or empty feature expression")
    try:root=py_ast.parse(normalize_expression(expression),mode="eval").body
    except (SyntaxError,ValueError) as exc:raise FeatureSpecInvalid("Invalid DSL expression") from exc
    return _convert(root)


def _convert(node: py_ast.AST) -> Node:
    if isinstance(node,py_ast.Name):return FieldNode(node.id)
    if isinstance(node,py_ast.Constant):
        if isinstance(node.value,str) and re.fullmatch(r"\d+(?:h|d)",node.value,re.I):return WindowNode(node.value)
        if isinstance(node.value,(str,int,float,bool,type(None))):return ConstantNode(node.value)
        raise FeatureSpecInvalid("Unsupported constant")
    if isinstance(node,(py_ast.List,py_ast.Tuple)):
        values=[]
        for child in node.elts:
            parsed=_convert(child)
            if not isinstance(parsed,ConstantNode):raise FeatureSpecInvalid("IN values must be constants")
            values.append(parsed.value)
        return ConstantNode(values)
    if isinstance(node,py_ast.Call):
        if not isinstance(node.func,py_ast.Name):raise FeatureSpecInvalid("Only named DSL operators are allowed")
        return OperatorNode(node.func.id,[_convert(x) for x in node.args],{x.arg:_convert(x.value) for x in node.keywords if x.arg})
    if isinstance(node,py_ast.Compare) and len(node.ops)==1 and len(node.comparators)==1:
        op=COMPARE.get(type(node.ops[0]))
        if not op:raise FeatureSpecInvalid("Comparison is not supported")
        return ConditionNode(op,[_convert(node.left),_convert(node.comparators[0])])
    if isinstance(node,py_ast.BoolOp):
        op="BOOLEAN_AND" if isinstance(node.op,py_ast.And) else "BOOLEAN_OR"
        return ConditionNode(op,[_convert(x) for x in node.values])
    if isinstance(node,py_ast.UnaryOp) and isinstance(node.op,py_ast.USub) and isinstance(node.operand,py_ast.Constant) and isinstance(node.operand.value,(int,float)):return ConstantNode(-node.operand.value)
    raise FeatureSpecInvalid(f"Unsupported DSL syntax: {type(node).__name__}")


def operators(node: Node) -> list[str]:
    found=[]
    if isinstance(node,(OperatorNode,ConditionNode)):found.append(node.op)
    for child in getattr(node,"args",()):found.extend(operators(child))
    for _,child in getattr(node,"kwargs",()):found.extend(operators(child))
    return sorted(set(found))


def fields(node: Node) -> list[str]:
    found=[node.name] if isinstance(node,FieldNode) else []
    for child in getattr(node,"args",()):found.extend(fields(child))
    for _,child in getattr(node,"kwargs",()):found.extend(fields(child))
    return sorted(set(found))


def windows(node: Node) -> list[str]:
    found=[node.value] if isinstance(node,WindowNode) else []
    for child in getattr(node,"args",()):found.extend(windows(child))
    for _,child in getattr(node,"kwargs",()):found.extend(windows(child))
    return sorted(set(found))


def normalized_ast(node: Node) -> str:return json.dumps(node.to_dict(),sort_keys=True,ensure_ascii=False,separators=(",",":"))


def from_dict(value: dict[str,Any]) -> Node:
    kind=value["node_type"]
    if kind=="FIELD":return FieldNode(value["name"])
    if kind=="CONSTANT":return ConstantNode(value.get("value"))
    if kind=="WINDOW":return WindowNode(value["value"])
    if kind=="CONDITION":return ConditionNode(value["op"],[from_dict(x) for x in value.get("args",[])])
    if kind=="OPERATOR":return OperatorNode(value["op"],[from_dict(x) for x in value.get("args",[])],{k:from_dict(v) for k,v in value.get("kwargs",{}).items()})
    raise FeatureSpecInvalid(f"Unknown AST node: {kind}")
