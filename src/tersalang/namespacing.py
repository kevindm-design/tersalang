# SPDX-License-Identifier: Apache-2.0
"""Private namespace for hidden task code in the harness merge (design §22.1).

Every name the hidden files declare, top-level or local, is renamed to
`name@hidden`. The lexer cannot produce `@`, so a candidate can neither
reach nor redefine a hidden helper, constant, record, choice, case, interface,
or interface function. Names that `interface.tersa` declares are the
candidate's and are never renamed. Visible task files go through the same
renaming with the suffix `@visible`.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from dataclasses import field as dataclass_field
from typing import Any

from tersalang.ast import (
    BindPat,
    CallExpr,
    ChoiceDecl,
    ConstDecl,
    CtorPat,
    Decl,
    FieldExpr,
    ForStmt,
    FunctionDecl,
    FunctionSig,
    ImplementsDecl,
    Import,
    InterfaceDecl,
    LetStmt,
    Module,
    NameExpr,
    Param,
    RecordDecl,
    SetStmt,
    TestDecl,
    TypeExpr,
    TypeParam,
    UsingStmt,
)
from tersalang.source import Span


@dataclass
class HiddenMerge:
    """Task declarations renamed into a private namespace, ready to merge with the candidate.

    `renamed` maps each original name to its suffixed name. `dropped` names the
    declarations that were left out.
    """

    imports: list[Import]
    decls: list[Decl]
    renamed: dict[str, str] = dataclass_field(default_factory=dict)
    dropped: list[str] = dataclass_field(default_factory=list)


def public_name(name: str) -> str:
    """The name a program wrote. Harness namespacing adds an `@` suffix."""
    return name.split("@", 1)[0]


def interface_names(module: Module | None) -> set[str]:
    """Names the candidate owns: everything `interface.tersa` declares."""
    names: set[str] = set()
    if module is None:
        return names
    for decl in module.decls:
        if isinstance(decl, InterfaceDecl):
            names.add(decl.name)
            names.update(header.name for header in decl.headers)
        elif isinstance(decl, FunctionDecl):
            names.add(decl.sig.name)
        elif isinstance(decl, (RecordDecl, ConstDecl)):
            names.add(decl.name)
        elif isinstance(decl, ChoiceDecl):
            names.add(decl.name)
            names.update(case.name for case in decl.cases)
    return names


def namespace_hidden(
    modules: list[Module], shared: set[str], candidate: Module, suffix: str
) -> HiddenMerge:
    """Rename hidden declarations into a private namespace and return them.

    Hidden functions (except `main`), constants, records, choices,
    interfaces, and tests are kept. A hidden declaration of a shared name is
    dropped, because the candidate supplies it.

    A hidden `implements` block is kept when its interface is a kept hidden
    interface, or when the interface is public (`Comparable` or one that
    `interface.tersa` declares) and the type is a kept hidden record or
    choice. Any other block would implement a public interface for a type the
    candidate can name: it could change which function the candidate's own
    calls dispatch to, and a candidate that implements the same pair would get
    a coherence error (E3043) caused by hidden code. Those blocks, and hidden
    `foreign` declarations, are dropped and listed in `dropped`.
    """
    kept: list[Decl] = []
    dropped: list[str] = []
    implements: list[ImplementsDecl] = []
    for module in modules:
        for decl in module.decls:
            if isinstance(decl, TestDecl):
                kept.append(decl)
            elif isinstance(decl, FunctionDecl):
                if decl.sig.name != "main" and decl.sig.name not in shared:
                    kept.append(decl)
            elif isinstance(decl, (ConstDecl, RecordDecl, ChoiceDecl, InterfaceDecl)):
                if decl.name not in shared:
                    kept.append(decl)
            elif isinstance(decl, ImplementsDecl):
                implements.append(decl)
            else:
                dropped.append(type(decl).__name__)
    hidden_interfaces = {decl.name for decl in kept if isinstance(decl, InterfaceDecl)}
    hidden_types = {decl.name for decl in kept if isinstance(decl, (RecordDecl, ChoiceDecl))}
    private_impls: set[int] = set()
    for decl in implements:
        iface = decl.interface.name
        owner = decl.interface.args[0].name if decl.interface.args else ""
        if iface in hidden_interfaces:
            private_impls.add(id(decl))
            kept.append(decl)
        elif (iface == "Comparable" or iface in shared) and owner in hidden_types:
            kept.append(decl)
        else:
            label = f"{iface}[{owner}]" if owner else iface
            dropped.append(f"ImplementsDecl {label}")
    choices: dict[str, set[str]] = {}
    bound: set[str] = set()
    for decl in kept:
        if isinstance(decl, FunctionDecl):
            bound.add(decl.sig.name)
        elif isinstance(decl, ChoiceDecl):
            bound.add(decl.name)
            choices[decl.name] = {case.name for case in decl.cases}
            bound.update(choices[decl.name])
        elif isinstance(decl, (ConstDecl, RecordDecl)):
            bound.add(decl.name)
        elif isinstance(decl, InterfaceDecl):
            bound.add(decl.name)
            bound.update(header.name for header in decl.headers)
        collect_locals(decl, bound)
    candidate_exposed = {name for item in candidate.imports for name, _span in item.exposing or []}
    imports: list[Import] = []
    qualifiers: set[str] = set()
    exposed: dict[str, str] = {}
    seen: set[tuple[tuple[str, ...], str]] = set()
    kept_upper: set[str] = set()
    for module in modules:
        for item in module.imports:
            qualifier = item.alias or item.path[-1]
            qualifiers.add(qualifier)
            if qualifier not in shared:
                bound.add(qualifier)
            renamed_qualifier = qualifier + suffix if qualifier not in shared else qualifier
            upper: list[tuple[str, Span]] = []
            for name, span in item.exposing or []:
                if name[:1].isupper():
                    # Std types and cases are global names, so the same name is the same entity.
                    if name not in candidate_exposed and name not in kept_upper:
                        upper.append((name, span))
                        kept_upper.add(name)
                else:
                    exposed[name] = renamed_qualifier
            key = (tuple(item.path), renamed_qualifier)
            if key in seen and not upper:
                continue
            seen.add(key)
            imports.append(Import(item.span, list(item.path), renamed_qualifier, upper or None))
    bound -= shared
    bound.discard("_")
    for name in exposed:
        bound.discard(name)
    # A call `recv.f(...)` names a method unless `recv` is a module or a type.
    cases = set(_std_cases()) | {name for names in choices.values() for name in names}
    cases.update(
        case.name for decl in candidate.decls if isinstance(decl, ChoiceDecl) for case in decl.cases
    )
    methods = {decl.sig.name for decl in kept if isinstance(decl, FunctionDecl)}
    for decl in kept:
        if isinstance(decl, InterfaceDecl):
            methods.update(header.name for header in decl.headers)
    methods &= bound
    renamer = _Renamer(bound, choices, exposed, suffix, methods, qualifiers, cases)
    for decl in kept:
        if isinstance(decl, ImplementsDecl):
            renamer.implements(decl, private=id(decl) in private_impls)
        else:
            renamer.decl(decl)
    return HiddenMerge(
        imports=imports,
        decls=kept,
        renamed={name: name + suffix for name in sorted(bound)},
        dropped=dropped,
    )


def collect_locals(value: object, bound: set[str]) -> None:
    """Add every name `value` binds at any depth to `bound`.

    That is parameters, type parameters, `let`, `for`, and `using` names, and
    pattern bindings. A record contributes its type parameters and the names
    bound in its invariants; a choice contributes only its type parameters.
    """
    if isinstance(value, (Param, TypeParam, LetStmt, ForStmt, UsingStmt, BindPat)):
        bound.add(value.name)
    if isinstance(value, RecordDecl):
        for param in value.type_params:
            bound.add(param.name)
        for invariant in value.invariants:
            collect_locals(invariant, bound)
        return
    if isinstance(value, ChoiceDecl):
        for param in value.type_params:
            bound.add(param.name)
        return
    if isinstance(value, Span) or not is_dataclass(value):
        if isinstance(value, (list, tuple)):
            for item in value:
                collect_locals(item, bound)
        return
    for item in fields(value):
        collect_locals(getattr(value, item.name), bound)


def _std_cases() -> set[str]:
    from tersalang.checker import CASE_FIELDS

    return set(CASE_FIELDS)


class _Renamer:
    def __init__(
        self,
        bound: set[str],
        choices: dict[str, set[str]],
        exposed: dict[str, str],
        suffix: str,
        methods: set[str] | None = None,
        qualifiers: set[str] | None = None,
        cases: set[str] | None = None,
    ) -> None:
        self.bound = bound
        self.choices = choices
        self.exposed = exposed
        self.suffix = suffix
        self.methods = methods or set()
        self.qualifiers = qualifiers or set()
        self.cases = cases or set()

    def implements(self, decl: ImplementsDecl, *, private: bool) -> None:
        """Rename a kept `implements` block.

        The functions of a hidden interface are renamed with its headers. The
        functions of a public interface keep the names that interface declares.
        """
        if private:
            decl.interface.name = self.rename(decl.interface.name)
        decl.interface.args = [self.walk(arg) for arg in decl.interface.args]
        for fn in decl.functions:
            if private:
                fn.sig.name = self.rename(fn.sig.name)
            for item in fields(fn.sig):
                if item.name not in {"span", "name"}:
                    setattr(fn.sig, item.name, self.walk(getattr(fn.sig, item.name)))
            fn.body = self.walk(fn.body)

    def _method_receiver(self, recv: Any) -> bool:
        if not isinstance(recv, NameExpr):
            return True
        if recv.name in self.qualifiers:
            return False
        return not recv.name[:1].isupper() or recv.name in self.cases

    def rename(self, name: str, exclude: frozenset[str] = frozenset()) -> str:
        if name in self.bound and name not in exclude:
            return name + self.suffix
        return name

    def decl(self, decl: Decl) -> None:
        if isinstance(decl, RecordDecl):
            decl.name = self.rename(decl.name)
            for param in decl.type_params:
                self.walk(param)
            for item in decl.fields:
                item.ty = self.walk(item.ty)
            # Record fields are in scope inside invariants and are never renamed.
            own = frozenset(item.name for item in decl.fields)
            decl.invariants = [self.walk(expr, own) for expr in decl.invariants]
            return
        if isinstance(decl, ChoiceDecl):
            cases = self.choices.get(decl.name, set())
            decl.name = self.rename(decl.name)
            for param in decl.type_params:
                self.walk(param)
            for case in decl.cases:
                if case.name in cases:
                    case.name = self.rename(case.name)
                for item in case.params:
                    item.ty = self.walk(item.ty)
            return
        if isinstance(decl, ConstDecl):
            decl.name = self.rename(decl.name)
            decl.ty = self.walk(decl.ty)
            decl.expr = self.walk(decl.expr)
            return
        if isinstance(decl, InterfaceDecl):
            decl.name = self.rename(decl.name)
            decl.type_params = self.walk(decl.type_params)
            decl.headers = self.walk(decl.headers)
            return
        self.walk(decl)

    def walk(self, value: Any, exclude: frozenset[str] = frozenset()) -> Any:
        if (
            isinstance(value, CallExpr)
            and isinstance(value.func, FieldExpr)
            and value.func.name in self.methods
            and self._method_receiver(value.func.recv)
        ):
            value.func.name = self.rename(value.func.name)
        if isinstance(value, NameExpr):
            if value.name in exclude:
                return value
            if value.name in self.exposed:
                return FieldExpr(
                    value.span, NameExpr(value.span, self.exposed[value.name]), value.name
                )
            value.name = self.rename(value.name)
            return value
        if isinstance(value, FieldExpr):
            recv = value.recv
            if (
                isinstance(recv, NameExpr)
                and recv.name not in exclude
                and value.name in self.choices.get(recv.name, set())
            ):
                value.name = self.rename(value.name)
            value.recv = self.walk(recv, exclude)
            return value
        if isinstance(value, TypeExpr):
            if value.path:
                value.path = [self.rename(value.path[0], exclude), *value.path[1:]]
            else:
                value.name = self.rename(value.name, exclude)
            value.args = [self.walk(arg, exclude) for arg in value.args]
            value.params = [self.walk(arg, exclude) for arg in value.params]
            if value.ret is not None:
                value.ret = self.walk(value.ret, exclude)
            return value
        if isinstance(value, CtorPat):
            if value.path:
                head = value.path[0]
                if value.name in self.choices.get(head, set()):
                    value.name = self.rename(value.name)
                value.path = [self.rename(head, exclude), *value.path[1:]]
            else:
                value.name = self.rename(value.name, exclude)
            if value.fields is not None:
                value.fields = [self.walk(item, exclude) for item in value.fields]
            return value
        if isinstance(value, SetStmt):
            value.place = [self.rename(value.place[0], exclude), *value.place[1:]]
            value.expr = self.walk(value.expr, exclude)
            return value
        if isinstance(value, (FunctionSig, Param, TypeParam, LetStmt, ForStmt, UsingStmt, BindPat)):
            value.name = self.rename(value.name, exclude)
        if isinstance(value, (list, tuple)):
            items = [self.walk(item, exclude) for item in value]
            return items if isinstance(value, list) else tuple(items)
        if isinstance(value, Span) or not is_dataclass(value) or isinstance(value, type):
            return value
        for item in fields(value):
            if item.name in {"span", "name"}:
                continue
            setattr(value, item.name, self.walk(getattr(value, item.name), exclude))
        return value
