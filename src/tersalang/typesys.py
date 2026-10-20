# SPDX-License-Identifier: Apache-2.0
"""Runtime-independent types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Type:
    """A checker type.

    `args` are type arguments, as in `List[Int]`. A function type is named `function` and
    uses `params` and `ret` instead. `is_var` marks a type variable that `unify` may bind.
    """

    name: str
    args: tuple[Type, ...] = ()
    params: tuple[Type, ...] = ()
    ret: Type | None = None
    effects: frozenset[str] = frozenset()
    is_var: bool = False

    def display(self) -> str:
        """Source-style rendering used in diagnostics, e.g. `Map[Text, Int]`."""
        if self.is_var:
            return self.name
        if self.name == "function" and self.ret is not None:
            rendered = ", ".join(param.display() for param in self.params)
            return f"function({rendered}) returns {self.ret.display()}"
        if self.args:
            rendered = ", ".join(arg.display() for arg in self.args)
            return f"{self.name}[{rendered}]"
        return self.name


def t(name: str, *args: Type) -> Type:
    """The named type applied to `args`: `name[args...]`, or plain `name` with none."""
    return Type(name, args)


def var(name: str) -> Type:
    """A type variable called `name`."""
    return Type(name, is_var=True)


def fn_type(params: tuple[Type, ...], ret: Type) -> Type:
    """`function(params...) returns ret`."""
    return Type("function", params=params, ret=ret)


def opt(inner: Type) -> Type:
    """`Option[inner]`."""
    return t("Option", inner)


def res(ok: Type, err: Type) -> Type:
    """`Result[ok, err]`."""
    return t("Result", ok, err)


def lst(inner: Type) -> Type:
    """`List[inner]`."""
    return t("List", inner)


def mp(key: Type, value: Type) -> Type:
    """`Map[key, value]`."""
    return t("Map", key, value)


INT = t("Int")
INT64 = t("Int64")
FLOAT = t("Float")
BOOL = t("Bool")
TEXT = t("Text")
BYTES = t("Bytes")
UNIT = t("Unit")
ORDERING = t("Ordering")

COMPARABLE = frozenset({"Int", "Int64", "Text", "Bool", "Ordering"})
NUMERIC = frozenset({"Int", "Int64", "Float"})
EFFECTS = frozenset({"Console", "FileRead", "FileWrite", "Net", "Clock", "Random", "Env", "Python"})
TRANSCENDENTAL = frozenset(
    {
        "sin",
        "cos",
        "tan",
        "asin",
        "acos",
        "atan",
        "atan2",
        "exp",
        "log",
        "log2",
        "log10",
        "float_pow",
    }
)


def types_equal(left: Type, right: Type) -> bool:
    """Structural equality on name, variable flag, args, params, and return type.

    `effects` are not compared.
    """
    return (
        left.name == right.name
        and left.is_var == right.is_var
        and len(left.args) == len(right.args)
        and all(types_equal(a, b) for a, b in zip(left.args, right.args, strict=True))
        and len(left.params) == len(right.params)
        and all(types_equal(a, b) for a, b in zip(left.params, right.params, strict=True))
        and (
            (left.ret is None and right.ret is None)
            or (left.ret is not None and right.ret is not None and types_equal(left.ret, right.ret))
        )
    )


def substitute(ty: Type, env: dict[str, Type]) -> Type:
    """`ty` with every type variable bound in `env` replaced; unbound variables stay."""
    if ty.is_var:
        return env.get(ty.name, ty)
    ret = None if ty.ret is None else substitute(ty.ret, env)
    return Type(
        ty.name,
        tuple(substitute(arg, env) for arg in ty.args),
        tuple(substitute(param, env) for param in ty.params),
        ret,
        ty.effects,
        False,
    )


def unify(pattern: Type, actual: Type, env: dict[str, Type]) -> bool:
    """Whether `actual` matches `pattern`, binding the pattern's type variables in `env`.

    Only variables in `pattern` bind; a variable in `actual` never matches a concrete
    pattern. A variable that is already bound must equal `actual` exactly. `env` keeps
    any bindings made before a failed match.
    """
    if pattern.is_var:
        bound = env.get(pattern.name)
        if bound is None:
            env[pattern.name] = actual
            return True
        return types_equal(bound, actual)
    if actual.is_var or pattern.name != actual.name:
        return False
    if len(pattern.args) != len(actual.args):
        return False
    if any(
        not unify(left, right, env) for left, right in zip(pattern.args, actual.args, strict=True)
    ):
        return False
    if pattern.ret is not None or actual.ret is not None:
        if pattern.ret is None or actual.ret is None or len(pattern.params) != len(actual.params):
            return False
        if any(
            not unify(left, right, env)
            for left, right in zip(pattern.params, actual.params, strict=True)
        ):
            return False
        return unify(pattern.ret, actual.ret, env)
    return True


def contains_mutable(ty: Type) -> bool:
    """Whether `ty` is `MutableList` or `MutableMap` or has one nested in its type arguments."""
    if ty.name in {"MutableList", "MutableMap"}:
        return True
    return any(contains_mutable(arg) for arg in ty.args)


def contains_float(ty: Type) -> bool:
    """Whether `ty` is `Float` or has it nested in its type arguments."""
    if ty.name == "Float":
        return True
    return any(contains_float(arg) for arg in ty.args)


def is_resource(ty: Type) -> bool:
    """Whether `ty` is a resource type that `using` can bind; only `File` is."""
    return ty.name in {"File"}
