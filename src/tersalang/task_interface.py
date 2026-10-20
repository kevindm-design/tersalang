# SPDX-License-Identifier: Apache-2.0
"""Function signatures a task's `interface.tersa` requires (design §22.1).

A required function is a header inside an `interface` block (with that
interface's type parameters first) or a top-level function. The attempt must
define a top-level function of the same name with the same type parameters
(compared by position, so `T` and `U` match), constraints, parameter
types, and return type. Parameter names, `public`, and contracts are not
compared: the interface's contracts replace the attempt's. Effects are not
compared either; the task's `effects` grant governs them.
"""

from __future__ import annotations

from dataclasses import replace

from tersalang.ast import FunctionDecl, FunctionSig, InterfaceDecl, Module, TypeExpr, TypeParam
from tersalang.diagnostics import Diagnostic, Fix, Related

CODE = "E3047"


def required_signatures(interface: Module | None) -> list[FunctionSig]:
    """Every function `interface` requires, in declaration order.

    A header inside an `interface` block gets that block's type parameters
    ahead of its own. No interface requires nothing.
    """
    found: list[FunctionSig] = []
    if interface is None:
        return found
    for decl in interface.decls:
        if isinstance(decl, InterfaceDecl):
            for header in decl.headers:
                found.append(replace(header, type_params=[*decl.type_params, *header.type_params]))
        elif isinstance(decl, FunctionDecl):
            found.append(decl.sig)
    return found


def signature_diagnostics(attempt: Module, interface: Module | None) -> list[Diagnostic]:
    """One `E3047` for each required function the attempt lacks or declares differently."""
    defined: dict[str, FunctionSig] = {}
    for decl in attempt.decls:
        if isinstance(decl, FunctionDecl):
            defined.setdefault(decl.sig.name, decl.sig)
    diagnostics: list[Diagnostic] = []
    for wanted in required_signatures(interface):
        required = f"`{signature_text(wanted)}`"
        related = [
            Related(f"{wanted.span.file} requires {required}", wanted.span.file, wanted.span)
        ]
        fix = Fix(f"declare the function as {required}")
        sig = defined.get(wanted.name)
        if sig is None:
            message = f"no function `{wanted.name}`; {wanted.span.file} requires {required}"
            diagnostics.append(
                Diagnostic(CODE, message, attempt.span.file, attempt.span, related, fix=fix)
            )
            continue
        reason = mismatch(sig, wanted)
        if reason is not None:
            message = f"`{wanted.name}` does not match {wanted.span.file}: {reason}"
            diagnostics.append(Diagnostic(CODE, message, sig.span.file, sig.span, related, fix=fix))
    return diagnostics


def mismatch(sig: FunctionSig, wanted: FunctionSig) -> str | None:
    """The first difference between an attempt signature and the required one."""
    if len(sig.type_params) != len(wanted.type_params):
        return (
            f"it has {_count(len(sig.type_params), 'type parameter')}, "
            f"the interface has {len(wanted.type_params)}"
        )
    own = _renaming(sig.type_params)
    theirs = _renaming(wanted.type_params)
    for mine, other in zip(sig.type_params, wanted.type_params, strict=True):
        if sorted(_key(item, own) for item in mine.constraints) != sorted(
            _key(item, theirs) for item in other.constraints
        ):
            return f"type parameter `{_param_text(mine)}` should be `{_param_text(other)}`"
    if len(sig.params) != len(wanted.params):
        return (
            f"it takes {_count(len(sig.params), 'parameter')}, "
            f"the interface takes {len(wanted.params)}"
        )
    for index, (mine_param, other_param) in enumerate(zip(sig.params, wanted.params, strict=True)):
        if _key(mine_param.ty, own) != _key(other_param.ty, theirs):
            return (
                f"parameter {index + 1} (`{mine_param.name}`) is `{type_text(mine_param.ty)}`, "
                f"the interface says `{type_text(other_param.ty)}`"
            )
    if _key(sig.ret, own) != _key(wanted.ret, theirs):
        return f"it returns `{type_text(sig.ret)}`, the interface says `{type_text(wanted.ret)}`"
    return None


def signature_text(sig: FunctionSig) -> str:
    """The signature as Tersalang source, such as `function f(x: Int) returns Int uses Console`."""
    params = ", ".join(f"{param.name}: {type_text(param.ty)}" for param in sig.params)
    type_params = ""
    if sig.type_params:
        type_params = "[" + ", ".join(_param_text(param) for param in sig.type_params) + "]"
    text = f"function {sig.name}{type_params}({params}) returns {type_text(sig.ret)}"
    if sig.effects:
        text += " uses " + ", ".join(name for name, _span in sig.effects)
    return text


def type_text(ty: TypeExpr) -> str:
    """The type as Tersalang source, such as `List[Int]` or `function(Int) returns Unit`."""
    if ty.kind == "function":
        params = ", ".join(type_text(item) for item in ty.params)
        ret = type_text(ty.ret) if ty.ret is not None else "Unit"
        return f"function({params}) returns {ret}"
    name = ".".join([*ty.path, ty.name])
    if ty.args:
        name += "[" + ", ".join(type_text(item) for item in ty.args) + "]"
    return name


def _param_text(param: TypeParam) -> str:
    if not param.constraints:
        return param.name
    return param.name + ": " + " and ".join(type_text(item) for item in param.constraints)


def _renaming(params: list[TypeParam]) -> dict[str, str]:
    return {param.name: f"${index}" for index, param in enumerate(params)}


def _key(ty: TypeExpr, renaming: dict[str, str]) -> str:
    if ty.kind == "function":
        params = ",".join(_key(item, renaming) for item in ty.params)
        ret = _key(ty.ret, renaming) if ty.ret is not None else "Unit"
        return f"function({params})->{ret}"
    name = renaming.get(ty.name, ty.name) if not ty.path else ".".join([*ty.path, ty.name])
    if ty.args:
        name += "[" + ",".join(_key(item, renaming) for item in ty.args) + "]"
    return name


def _count(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"
