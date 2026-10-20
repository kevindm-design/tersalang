# SPDX-License-Identifier: Apache-2.0
"""Name resolution, type checking, and effect checking."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from tersalang.ast import (
    Arg,
    BinaryExpr,
    BindPat,
    Block,
    BreakStmt,
    CallExpr,
    ChoiceDecl,
    ConstDecl,
    ContinueStmt,
    Contract,
    CtorPat,
    ExpectStmt,
    Expr,
    ExprStmt,
    FailStmt,
    FieldExpr,
    ForeignDecl,
    ForStmt,
    FunctionDecl,
    GroupExpr,
    IfStmt,
    ImplementsDecl,
    InterfaceDecl,
    LambdaExpr,
    LetStmt,
    ListExpr,
    LiteralExpr,
    LitPat,
    MapExpr,
    MatchStmt,
    Module,
    NameExpr,
    OldExpr,
    RecordDecl,
    ResultExpr,
    ReturnStmt,
    SetStmt,
    TestDecl,
    TypeExpr,
    UnaryExpr,
    UsingStmt,
    WhileStmt,
    WildPat,
    WithExpr,
)
from tersalang.builtins import BY_ID, Builtin, methods_of, module_members, statics_of
from tersalang.diagnostics import Diagnostic, Fix
from tersalang.namespacing import public_name
from tersalang.source import Span
from tersalang.typesys import (
    BOOL,
    COMPARABLE,
    EFFECTS,
    FLOAT,
    INT,
    INT64,
    NUMERIC,
    ORDERING,
    TEXT,
    TRANSCENDENTAL,
    UNIT,
    Type,
    contains_float,
    contains_mutable,
    fn_type,
    is_resource,
    lst,
    mp,
    opt,
    res,
    substitute,
    t,
    types_equal,
    unify,
    var,
)

POISON = t("<error>")

CASE_FIELDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "Some": ("Option", ("value",)),
    "None": ("Option", ()),
    "Ok": ("Result", ("value",)),
    "Error": ("Result", ("error",)),
    "Less": ("Ordering", ()),
    "Equal": ("Ordering", ()),
    "Greater": ("Ordering", ()),
    "NotFound": ("FileError", ("path",)),
    "Denied": ("FileError", ("path",)),
    "Io": ("FileError", ("message",)),
    "Invalid": ("Utf8Error", ("index",)),
}

# Json constructors are spelled Null, Bool, Number, String, Array, Object.
# Bool clashes with the type Bool, so these cases live in the `Json` namespace
# (`Json.Bool`); only Null is also bound unqualified.
JSON_CASES = {
    "Null": (),
    "Bool": ("value",),
    "Number": ("literal",),
    "String": ("value",),
    "Array": ("items",),
    "Object": ("entries",),
}


@dataclass
class Binding:
    """A name in scope.

    `kind` says what the name denotes, such as `local`, `param`, `const`, `case`, `type`,
    `record`, `builtin`, or `namespace`. `payload` holds what that kind needs: the
    declaration, the `Builtin`, a case's `(type name, fields)`, or a module name.
    """

    name: str
    kind: str
    ty: Type
    mutable: bool = False
    payload: object = None
    effects: frozenset[str] = frozenset()
    span: Span | None = None


@dataclass
class RecordInfo:
    """A record type with its field types resolved. `module` is `std` for prelude records."""

    name: str
    type_params: tuple[str, ...]
    fields: tuple[tuple[str, Type], ...]
    invariants: list[Expr]
    span: Span
    module: str


@dataclass
class ChoiceInfo:
    """A choice type with each case's field types resolved, keyed by case name."""

    name: str
    type_params: tuple[str, ...]
    cases: dict[str, tuple[tuple[str, Type], ...]]
    span: Span
    module: str


@dataclass
class IfaceFn:
    """A function an interface declares, with its types resolved."""

    iface: str
    type_param: str | None
    name: str
    params: tuple[tuple[str, Type], ...]
    ret: Type
    effects: frozenset[str]
    contracts: tuple[Contract, ...]

    @property
    def dispatch(self) -> int | None:
        """The first parameter whose type is the interface's type parameter."""
        for index, (_name, ty) in enumerate(self.params):
            if ty.is_var and ty.name == self.type_param:
                return index
        return None


BUILTIN_INTERFACES = frozenset({"Comparable", "Equatable", "Hashable", "Showable"})

COMPARABLE_COMPARE = IfaceFn(
    "Comparable", "T", "compare", (("a", var("T")), ("b", var("T"))), ORDERING, frozenset(), ()
)


@dataclass
class Scope:
    """One lexical scope. Lookups fall through to `parent`."""

    names: dict[str, Binding] = field(default_factory=dict)
    parent: Scope | None = None

    def lookup(self, name: str) -> Binding | None:
        """The innermost binding of `name`, or `None`."""
        if name in self.names:
            return self.names[name]
        if self.parent is not None:
            return self.parent.lookup(name)
        return None


class Checker:
    """Checks one module and collects its diagnostics.

    `mode` changes what is allowed: `rl` rejects `Python` and RL-forbidden builtins (`E4012`,
    `E4011`), and only `host` accepts `foreign` declarations (`E4012` otherwise).
    """

    def __init__(self, module: Module, *, mode: str = "dev") -> None:
        self.module = module
        self.mode = mode
        self.diagnostics: list[Diagnostic] = []
        self.scope = Scope()
        self.records: dict[str, RecordInfo] = {}
        self.choices: dict[str, ChoiceInfo] = {}
        self.functions: list[FunctionDecl] = []
        self.fn_ret: Type | None = None
        self.fn_effects: frozenset[str] = frozenset()
        self.loop_depth = 0
        self.in_ensures = False
        self.in_test = False
        self._inside_lambda = False
        self._bounds_ok: set[tuple[str, str]] = set()
        self._implementations: dict[tuple[str, str], Span] = {}
        self.interfaces: dict[str, InterfaceDecl] = {}
        self.impls: dict[tuple[str, str], ImplementsDecl] = {}
        self.iface_fns: dict[str, list[IfaceFn]] = {"compare": [COMPARABLE_COMPARE]}
        self.constraints: dict[str, frozenset[str]] = {}
        # Constraints on record and choice type parameters, by type name.
        self.type_constraints: dict[str, tuple[tuple[str, frozenset[str]], ...]] = {}
        self._constraint_reported: set[tuple[Span, str]] = set()
        self._unhashable_reported: set[Span] = set()
        self._install_prelude()

    def check(self) -> list[Diagnostic]:
        """Every diagnostic for the module, in the order the passes find them."""
        self._check_module_name()
        self._declare_types()
        self._declare_headers()
        self._check_imports()
        for decl in self.module.decls:
            if isinstance(decl, (RecordDecl, ChoiceDecl)):
                self._check_type_decl_body(decl)
        for decl in self.module.decls:
            if isinstance(decl, FunctionDecl):
                self._check_function(decl)
            elif isinstance(decl, ConstDecl):
                self._check_const(decl)
            elif isinstance(decl, ForeignDecl):
                self._check_foreign(decl)
            elif isinstance(decl, ImplementsDecl):
                self._check_implements(decl)
            elif isinstance(decl, TestDecl):
                self._check_test(decl)
            elif isinstance(decl, InterfaceDecl):
                self._check_interface(decl)
        self._check_doc_examples()
        self._check_const_cycles()
        return self.diagnostics

    def _install_prelude(self) -> None:
        for name in (
            "Int",
            "Int64",
            "Float",
            "Bool",
            "Text",
            "Bytes",
            "Unit",
            "List",
            "Map",
            "Set",
            "Option",
            "Result",
            "Ordering",
            "MutableList",
            "MutableMap",
            "Entry",
            "File",
            "FileError",
            "Utf8Error",
            "Json",
            "JsonError",
            "Comparable",
            "Equatable",
            "Hashable",
            "Showable",
        ):
            self.scope.names[name] = Binding(name, "type", t(name))
        self.scope.names["PythonError"] = Binding("PythonError", "record", t("PythonError"))
        self.records["PythonError"] = RecordInfo(
            "PythonError",
            (),
            (("type_name", TEXT), ("message", TEXT)),
            [],
            self.module.span,
            "std",
        )
        # show[T] requires T: Showable. The check is in _call_builtin.
        self.scope.names["show"] = Binding(
            "show", "builtin", fn_type((var("T"),), TEXT), payload=BY_ID["show"]
        )
        for case, (type_name, fields) in CASE_FIELDS.items():
            self.scope.names[case] = Binding(
                case, "case", t(type_name), payload=(type_name, fields)
            )
        self.scope.names["Null"] = Binding("Null", "case", t("Json"), payload=("Json", ()))
        # Json.Bool would clash with the Bool type, so it stays qualified.
        self._namespaces: dict[str, dict[str, Binding]] = {}
        for type_name in (
            "Int",
            "Int64",
            "Float",
            "Text",
            "Bytes",
            "List",
            "Map",
            "Set",
            "MutableList",
            "MutableMap",
            "Option",
            "Result",
            "File",
            "Random",
        ):
            members: dict[str, Binding] = {}
            for name, builtin in statics_of(type_name).items():
                members[name] = Binding(
                    name,
                    "builtin",
                    self._builtin_fn_type(builtin),
                    payload=builtin,
                    effects=builtin.effects,
                )
            if type_name == "Int64":
                members["min"] = Binding("min", "const", INT64)
                members["max"] = Binding("max", "const", INT64)
            if type_name == "Float":
                members["infinity"] = Binding("infinity", "const", FLOAT)
                members["nan"] = Binding("nan", "const", FLOAT)
            self._namespaces[type_name] = members
        self._namespaces["Json"] = {
            case: Binding(case, "case", t("Json"), payload=("Json", fields))
            for case, fields in JSON_CASES.items()
        }
        for module, names in {
            "std.core": ["show"],
            "std.console": ["print", "print_error", "read_line"],
            "std.math": list(module_members("std.math")),
            "std.list": list(module_members("std.list")),
            "std.map": list(module_members("std.map")),
            "std.set": list(module_members("std.set")),
            "std.mutable": list(module_members("std.mutable")),
            "std.text": list(module_members("std.text")),
            "std.file": list(module_members("std.file")),
            "std.clock": ["now", "monotonic"],
            "std.random": list(module_members("std.random")),
            "std.env": ["args", "get"],
            "std.testing": ["approx"],
            "std.json": ["parse", "stringify"],
        }.items():
            bucket: dict[str, Binding] = {}
            exported = module_members(module)
            for name in names:
                found = exported.get(name)
                if found is None:
                    found = next(
                        item
                        for item in BY_ID.values()
                        if item.module == module and item.name == name
                    )
                bucket[name] = Binding(
                    name,
                    "builtin",
                    self._builtin_fn_type(found),
                    payload=found,
                    effects=found.effects,
                )
            if module == "std.file":
                bucket["File"] = Binding("File", "type", t("File"))
                bucket["FileError"] = Binding("FileError", "type", t("FileError"))
                for case in ("NotFound", "Denied", "Io"):
                    bucket[case] = self.scope.names[case]
            if module == "std.text":
                bucket["Utf8Error"] = Binding("Utf8Error", "type", t("Utf8Error"))
                bucket["Invalid"] = self.scope.names["Invalid"]
            if module == "std.json":
                bucket["Json"] = Binding("Json", "type", t("Json"))
                bucket["JsonError"] = Binding("JsonError", "type", t("JsonError"))
                bucket.update(self._namespaces["Json"])
            self._namespaces[module] = bucket

    def _check_module_name(self) -> None:
        path = self.module.path
        filename = self.module.span.file
        stem = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        if stem.endswith(".tersa"):
            stem = stem[: -len(".tersa")]
        if "/" not in filename and "\\" not in filename:
            if path != [stem]:
                self._error(
                    "E2001",
                    f"module `{'.'.join(path)}` does not match the file name `{stem}`",
                    self.module.span,
                    fix=f"write `module {stem}`",
                )
        elif path[-1] != stem:
            self._error(
                "E2001",
                f"module `{'.'.join(path)}` does not match the file name `{stem}`",
                self.module.span,
            )

    def _declare_types(self) -> None:
        for decl in self.module.decls:
            if isinstance(decl, (RecordDecl, ChoiceDecl)) and any(
                param.constraints for param in decl.type_params
            ):
                self.type_constraints[decl.name] = tuple(
                    (param.name, frozenset(item.name for item in param.constraints))
                    for param in decl.type_params
                )
            if isinstance(decl, RecordDecl):
                self._define_top(
                    decl.name,
                    Binding(decl.name, "record", t(decl.name), span=decl.span, payload=decl),
                )
            elif isinstance(decl, ChoiceDecl):
                self._define_top(
                    decl.name,
                    Binding(decl.name, "choice", t(decl.name), span=decl.span, payload=decl),
                )
                params = tuple(param.name for param in decl.type_params)
                env = {name: var(name) for name in params}
                cases: dict[str, tuple[tuple[str, Type], ...]] = {}
                for case in decl.cases:
                    fields = tuple(
                        (param.name, self._resolve_type(param.ty, env)) for param in case.params
                    )
                    cases[case.name] = fields
                    existing = self.scope.lookup(case.name)
                    if existing is not None and existing.kind == "case":
                        self.scope.names.pop(case.name, None)
                        self._note_ambiguous(case.name, case.span)
                    else:
                        self._define_top(
                            case.name,
                            Binding(
                                case.name,
                                "case",
                                t(decl.name),
                                payload=(decl.name, tuple(name for name, _ in fields)),
                                span=case.span,
                            ),
                        )
                self.choices[decl.name] = ChoiceInfo(
                    decl.name, params, cases, decl.span, ".".join(self.module.path)
                )
            elif isinstance(decl, InterfaceDecl):
                self._define_top(
                    decl.name,
                    Binding(decl.name, "interface", t(decl.name), span=decl.span, payload=decl),
                )
                self.interfaces.setdefault(decl.name, decl)

    def _declare_headers(self) -> None:
        for decl in self.module.decls:
            if isinstance(decl, FunctionDecl):
                self.functions.append(decl)
                ty = self._function_type(decl)
                self._define_top(
                    decl.sig.name,
                    Binding(
                        decl.sig.name,
                        "function",
                        ty,
                        payload=decl,
                        effects=frozenset(name for name, _ in decl.sig.effects),
                        span=decl.span,
                    ),
                )
            elif isinstance(decl, ConstDecl):
                ty = self._resolve_type(decl.ty)
                self._define_top(
                    decl.name, Binding(decl.name, "const", ty, payload=decl, span=decl.span)
                )
            elif isinstance(decl, ForeignDecl):
                env = {param.name: var(param.name) for param in decl.sig.type_params}
                params = tuple(self._resolve_type(param.ty, env) for param in decl.sig.params)
                ret = self._resolve_type(decl.sig.ret, env)
                effects = frozenset(name for name, _span in decl.sig.effects)
                self._define_top(
                    decl.sig.name,
                    Binding(
                        decl.sig.name,
                        "foreign",
                        fn_type(params, ret),
                        payload=decl,
                        effects=effects,
                        span=decl.span,
                    ),
                )
            elif isinstance(decl, ImplementsDecl):
                key = (decl.interface.name, _impl_owner(decl))
                self.impls.setdefault(key, decl)
        for iface in reversed(list(self.interfaces.values())):
            type_param = iface.type_params[0].name if iface.type_params else None
            for header in iface.headers:
                env = {param.name: var(param.name) for param in iface.type_params}
                env.update({param.name: var(param.name) for param in header.type_params})
                self.iface_fns.setdefault(header.name, []).insert(
                    0,
                    IfaceFn(
                        iface.name,
                        type_param,
                        header.name,
                        tuple(
                            (param.name, self._resolve_type(param.ty, env))
                            for param in header.params
                        ),
                        self._resolve_type(header.ret, env),
                        frozenset(name for name, _span in header.effects),
                        tuple(header.contracts),
                    ),
                )

    def _check_imports(self) -> None:
        seen: dict[str, Span] = {}
        module_key = ".".join(self.module.path)
        for imported in self.module.imports:
            key = ".".join(imported.path)
            if key == module_key:
                self._error("E2002", f"import cycle {key} -> {key}", imported.span)
                continue
            if not key.startswith("std."):
                self._error(
                    "E2000",
                    f"unknown module `{key}`",
                    imported.span,
                    fix="this interpreter loads std modules and a single file",
                )
                continue
            if key not in self._namespaces and key != "std.core":
                self._error("E4013", f"unknown standard library module `{key}`", imported.span)
                continue
            qualifier = imported.alias or imported.path[-1]
            if qualifier in seen or self.scope.lookup(qualifier) is not None:
                self._error(
                    "E2004",
                    f"import qualifier `{qualifier}` clashes with another name",
                    imported.span,
                    fix="rename it with `as`",
                )
            else:
                seen[qualifier] = imported.span
                self.scope.names[qualifier] = Binding(
                    qualifier, "namespace", t(qualifier), payload=key
                )
            if imported.exposing is not None:
                for name, span in imported.exposing:
                    member = self._namespaces.get(key, {}).get(name)
                    if member is None:
                        self._error("E2005", f"`{key}` has no public member `{name}`", span)
                        continue
                    self._define_top(
                        name,
                        Binding(
                            name,
                            member.kind,
                            member.ty,
                            payload=member.payload,
                            effects=member.effects,
                            span=span,
                        ),
                    )
                    if member.kind == "type" and name in self._namespaces:
                        for child_name, child in self._namespaces[name].items():
                            if child.kind == "case":
                                self._define_top(child_name, child)

    def _check_type_decl_body(self, decl: RecordDecl | ChoiceDecl) -> None:
        previous_constraints = self.constraints
        self.constraints = {
            param.name: self._constraint_names(param.constraints) for param in decl.type_params
        }
        try:
            self._check_type_decl_fields(decl)
        finally:
            self.constraints = previous_constraints

    def _check_type_decl_fields(self, decl: RecordDecl | ChoiceDecl) -> None:
        env = {param.name: var(param.name) for param in decl.type_params}
        if isinstance(decl, RecordDecl):
            fields = tuple((param.name, self._resolve_type(param.ty, env)) for param in decl.fields)
            for _, ty in fields:
                if contains_mutable(ty):
                    self._error(
                        "E3070", "a mutable collection cannot be stored in a record", decl.span
                    )
            info = RecordInfo(
                decl.name,
                tuple(env),
                fields,
                decl.invariants,
                decl.span,
                ".".join(self.module.path),
            )
            self.records[decl.name] = info
            child = Scope(parent=self.scope)
            # A harness-namespaced record (`Name@hidden`) keeps its field names,
            # so they may coincide with a candidate's top-level names.
            namespaced = "@" in decl.name
            for name, ty in fields:
                if not namespaced and child.lookup(name) is not None and name not in child.names:
                    self._error("E2020", f"`{name}` is already defined", decl.span)
                child.names[name] = Binding(name, "local", ty)
            previous = self.scope
            self.scope = child
            for invariant in decl.invariants:
                got = self.check_expr(invariant, BOOL)
                if got.name not in {"Bool", "<error>"}:
                    self._error("E3022", "invariant must be Bool", invariant.span)
            self.scope = previous

    def _check_function(
        self, decl: FunctionDecl, inherited: tuple[IfaceFn, dict[str, Type]] | None = None
    ) -> None:
        previous_constraints = self.constraints
        self.constraints = {
            param.name: self._constraint_names(param.constraints) for param in decl.sig.type_params
        }
        try:
            self._check_function_body(decl, inherited)
        finally:
            self.constraints = previous_constraints

    def _constraint_names(self, constraints: Sequence[TypeExpr]) -> frozenset[str]:
        names: set[str] = set()
        for constraint in constraints:
            if constraint.name not in BUILTIN_INTERFACES and constraint.name not in self.interfaces:
                self._error("E3008", f"unknown interface `{constraint.name}`", constraint.span)
                continue
            names.add(constraint.name)
        return frozenset(names)

    def _check_function_body(
        self, decl: FunctionDecl, inherited: tuple[IfaceFn, dict[str, Type]] | None
    ) -> None:
        self._check_signature_effects(decl.sig.effects)
        if self.mode == "rl":
            for name, span in decl.sig.effects:
                if name == "Python":
                    self._error("E4012", "`Python` cannot be used in RL mode", span)
        ret = self._resolve_type(
            decl.sig.ret, {param.name: var(param.name) for param in decl.sig.type_params}
        )
        if decl.public and contains_mutable(ret):
            self._error(
                "E3070", "a public function cannot return a mutable collection", decl.sig.ret.span
            )
        self.fn_ret = ret
        self.fn_effects = frozenset(name for name, _ in decl.sig.effects)
        child = Scope(parent=self.scope)
        env = {type_param.name: var(type_param.name) for type_param in decl.sig.type_params}
        for type_param in decl.sig.type_params:
            child.names[type_param.name] = Binding(
                type_param.name, "type_param", var(type_param.name)
            )
        for param in decl.sig.params:
            ty = self._resolve_type(param.ty, env)
            self._define(child, param.name, Binding(param.name, "param", ty, span=param.span))
            if contains_mutable(ty):
                pass
        for contract in decl.sig.contracts:
            self._check_contract(contract.kind, contract.expr, child, ret)
        if inherited is not None:
            header, owner_env = inherited
            aliases = Scope(parent=child)
            for name, ty in header.params:
                if name not in child.names:
                    aliases.names[name] = Binding(name, "param", substitute(ty, owner_env))
            before = len(self.diagnostics)
            for contract in header.contracts:
                self._check_contract(contract.kind, contract.expr, aliases, ret)
            # One interface contract is checked once per implementation; report a
            # mistake in it once.
            seen = {(d.code, d.span, d.message) for d in self.diagnostics[:before]}
            fresh = [
                d for d in self.diagnostics[before:] if (d.code, d.span, d.message) not in seen
            ]
            self.diagnostics[before:] = fresh
        previous = self.scope
        self.scope = child
        returns = self._check_block(decl.body)
        self.scope = previous
        if ret.name != "Unit" and not returns:
            self._error("E3032", "a path through this function does not return or fail", decl.span)
        self.fn_ret = None

    def _check_const(self, decl: ConstDecl) -> None:
        expected = self._resolve_type(decl.ty)
        self.fn_effects = frozenset()
        self.fn_ret = None
        got = self.check_expr(decl.expr, expected)
        self._assignable(expected, got, decl.expr.span)
        self._reject_effects_in(decl.expr, decl.span)

    def _check_foreign(self, decl: ForeignDecl) -> None:
        if self.mode != "host":
            self._error(
                "E4012",
                "foreign declarations require host mode",
                decl.span,
                fix="run with --mode host",
            )
        effects = frozenset(name for name, _ in decl.sig.effects)
        if "Python" not in effects:
            self._error("E4001", "a foreign function must declare `uses Python`", decl.span)
        self._check_signature_effects(decl.sig.effects)
        if self.mode != "host" or "Python" not in effects:
            return
        if not _python_target(decl.target):
            self._error(
                "E4020",
                "foreign target must look like `python:module.name`",
                decl.span,
            )
            return
        binding = self.scope.lookup(decl.sig.name)
        if binding is None or binding.kind != "foreign":
            return
        for param, ty in zip(decl.sig.params, binding.ty.params, strict=False):
            self._reject_python_type(ty, f"parameter `{param.name}`", param.span, as_return=False)
        if binding.ty.ret is not None:
            self._reject_python_type(
                binding.ty.ret, "the return type", decl.sig.ret.span, as_return=True
            )

    def _check_interface(self, decl: InterfaceDecl) -> None:
        for header in decl.headers:
            self._check_signature_effects(header.effects)

    def _check_implements(self, decl: ImplementsDecl) -> None:
        iface_name = decl.interface.name
        if iface_name in {"Equatable", "Hashable", "Showable"}:
            self._error("E3041", f"`{iface_name}` is derived and cannot be implemented", decl.span)
            return
        type_arg = decl.interface.args[0] if decl.interface.args else None
        owner = type_arg.name if type_arg is not None else ""
        defines_iface = any(
            isinstance(item, InterfaceDecl) and item.name == iface_name
            for item in self.module.decls
        )
        defines_type = owner in self.records or owner in self.choices
        if not defines_iface and not defines_type:
            self._error(
                "E3040", "an implements block must live with the interface or the type", decl.span
            )
        pair = (iface_name, owner)
        label = f"{iface_name}[{owner}]" if owner else iface_name
        first = self._implementations.get(pair)
        if first is not None:
            self._error(
                "E3043",
                f"{label} is already implemented (first at {first.file}:{first.start_line})",
                decl.span,
            )
        else:
            self._implementations[pair] = decl.span
        iface = self.interfaces.get(iface_name)
        if iface is None and iface_name != "Comparable":
            self._error("E3008", f"unknown interface `{iface_name}`", decl.interface.span)
        arity = 1 if iface is None else len(iface.type_params)
        if (iface is not None or iface_name == "Comparable") and len(decl.interface.args) != arity:
            if arity == 0:
                names = ", ".join(f"`{fn.name}`" for fn in self._iface_headers(iface_name))
                self._error(
                    "E3007",
                    f"`{iface_name}` takes no type parameter, so no implements block can supply it",
                    decl.interface.span,
                    fix=f"define top-level functions {names} instead" if names else None,
                )
                for fn in decl.functions:
                    self._check_function(fn)
                return
            self._error(
                "E3007",
                f"`{iface_name}` expects {arity} type argument{'' if arity == 1 else 's'}",
                decl.interface.span,
            )
        headers = {fn.name: fn for fn in self._iface_headers(iface_name)}
        owner_env: dict[str, Type] = {}
        if type_arg is not None:
            type_param = (
                "T" if iface is None else (iface.type_params[0].name if iface.type_params else "")
            )
            owner_env[type_param] = self._resolve_type(type_arg)
        found = {fn.sig.name for fn in decl.functions}
        for name in headers:
            if name not in found:
                self._error("E3044", f"missing `{name}` for {label}", decl.span)
        for fn in decl.functions:
            for contract in fn.sig.contracts:
                if contract.kind == "requires":
                    self._error("E5010", "an implementation cannot add `requires`", contract.span)
            header = headers.get(fn.sig.name)
            if header is None:
                if iface is not None or iface_name == "Comparable":
                    self._error(
                        "E3004", f"`{iface_name}` declares no function `{fn.sig.name}`", fn.span
                    )
                self._check_function(fn)
                continue
            if self._match_header(fn, header, owner_env):
                self._check_function(fn, (header, owner_env))
            else:
                self._check_function(fn)

    def _iface_headers(self, iface_name: str) -> list[IfaceFn]:
        if iface_name == "Comparable":
            return [COMPARABLE_COMPARE]
        return [fn for fns in self.iface_fns.values() for fn in fns if fn.iface == iface_name]

    def _match_header(self, fn: FunctionDecl, header: IfaceFn, owner_env: dict[str, Type]) -> bool:
        """Report an implementation whose type differs from the interface's."""
        if fn.sig.type_params:
            return True
        params = tuple(self._resolve_type(param.ty) for param in fn.sig.params)
        wanted = fn_type(
            tuple(substitute(ty, owner_env) for _name, ty in header.params),
            substitute(header.ret, owner_env),
        )
        got = fn_type(params, self._resolve_type(fn.sig.ret))
        if _has_var(wanted) or types_equal(wanted, got):
            return True
        self._error(
            "E3000",
            f"`{fn.sig.name}` must have type {wanted.display()} to implement "
            f"`{header.iface}`, found {got.display()}",
            fn.span,
        )
        return False

    def _check_test(self, decl: TestDecl) -> None:
        self.in_test = True
        self.fn_ret = UNIT
        self.fn_effects = EFFECTS
        child = Scope(parent=self.scope)
        if decl.property_params:
            for param in decl.property_params:
                ty = self._resolve_type(param.ty)
                if not self._generatable(ty):
                    self._error("E3013", f"no generator for `{ty.display()}`", param.span)
                self._define(child, param.name, Binding(param.name, "param", ty, span=param.span))
        previous = self.scope
        self.scope = child
        self._check_block(decl.body)
        self.scope = previous
        self.in_test = False
        self.fn_effects = frozenset()

    def _check_doc_examples(self) -> None:
        for decl in self.module.decls:
            doc = getattr(decl, "doc", None)
            if not isinstance(doc, str):
                continue
            for line in doc.splitlines():
                if line.startswith("Example:"):
                    text = line[len("Example:") :].strip()
                    from tersalang.lexer import lex_text
                    from tersalang.parser import parse_expression

                    source, tokens, diagnostics = lex_text(self.module.span.file, text)
                    expr = parse_expression(source, tokens, diagnostics)
                    for diagnostic in diagnostics:
                        self.diagnostics.append(diagnostic)
                    if expr is None:
                        continue
                    self.fn_effects = frozenset()
                    self.fn_ret = BOOL
                    got = self.check_expr(expr, BOOL)
                    if got.name not in {"Bool", "<error>"}:
                        self._error("E3022", "a doc example must be Bool", decl.span)

    def _check_const_cycles(self) -> None:
        consts = {decl.name: decl for decl in self.module.decls if isinstance(decl, ConstDecl)}
        graph: dict[str, set[str]] = {}
        for name, decl in consts.items():
            graph[name] = _const_refs(decl.expr) & set(consts)
        visiting: set[str] = set()
        visited: set[str] = set()

        def walk(name: str) -> bool:
            if name in visiting:
                return True
            if name in visited:
                return False
            visiting.add(name)
            cyclic = any(walk(other) for other in graph.get(name, ()))
            visiting.remove(name)
            visited.add(name)
            return cyclic

        reported: set[str] = set()
        for name, decl in consts.items():
            if walk(name) and name not in reported:
                reported.add(name)
                self._error("E2003", f"constant `{name}` is part of a cycle", decl.span)

    def _check_block(self, block: Block) -> bool:
        returns = False
        for stmt in block.stmts:
            if self._check_stmt(stmt):
                returns = True
        return returns

    def _check_stmt(self, stmt: object) -> bool:
        if isinstance(stmt, LetStmt):
            expected = self._resolve_type(stmt.ty) if stmt.ty is not None else None
            got = self.check_expr(stmt.expr, expected)
            ty = expected if expected is not None else got
            if expected is not None:
                self._assignable(expected, got, stmt.expr.span, literal=stmt.expr)
            if not stmt.discard:
                self._define(
                    self.scope,
                    stmt.name,
                    Binding(
                        stmt.name,
                        "var" if stmt.mutable else "local",
                        ty,
                        mutable=stmt.mutable,
                        span=stmt.span,
                    ),
                )
            return False
        if isinstance(stmt, SetStmt):
            self._check_set(stmt)
            return False
        if isinstance(stmt, ReturnStmt):
            if self.fn_ret is None:
                return True
            if stmt.expr is None:
                if self.fn_ret.name != "Unit":
                    self._error("E3032", "this function must return a value", stmt.span)
            else:
                got = self.check_expr(stmt.expr, self.fn_ret)
                self._assignable(self.fn_ret, got, stmt.expr.span, literal=stmt.expr, code="E3033")
            return True
        if isinstance(stmt, FailStmt):
            got = self.check_expr(stmt.expr, TEXT)
            self._assignable(TEXT, got, stmt.expr.span)
            return True
        if isinstance(stmt, ExpectStmt):
            if not self.in_test:
                self._error(
                    "E2011",
                    "`expect` is only allowed inside a test",
                    stmt.span,
                    fix="use `requires`, `ensures`, or `fail`",
                )
            got = self.check_expr(stmt.expr, BOOL)
            if got.name not in {"Bool", "<error>"}:
                self._error("E3022", "expect condition must be Bool", stmt.expr.span)
            return False
        if isinstance(stmt, (BreakStmt, ContinueStmt)):
            if self.loop_depth == 0:
                self._error(
                    "E2010", "`break` and `continue` are only allowed inside a loop", stmt.span
                )
            return False
        if isinstance(stmt, IfStmt):
            arm_returns = []
            for arm in stmt.arms:
                cond = self.check_expr(arm.cond, BOOL)
                if cond.name not in {"Bool", "<error>"}:
                    self._error("E3022", "condition must be Bool", arm.cond.span)
                saved_bounds = self._bounds_ok
                self._bounds_ok = saved_bounds | self._proven_indexes(arm.cond)
                arm_returns.append(self._check_block(arm.block))
                self._bounds_ok = saved_bounds
            else_returns = False
            if stmt.else_block is not None:
                else_returns = self._check_block(stmt.else_block)
            return (
                bool(arm_returns)
                and all(arm_returns)
                and stmt.else_block is not None
                and else_returns
            )
        if isinstance(stmt, MatchStmt):
            ty = self.check_expr(stmt.expr, None)
            arm_returns = []
            for match_arm in stmt.arms:
                child = Scope(parent=self.scope)
                previous = self.scope
                self.scope = child
                self._check_pattern(match_arm.pattern, ty)
                if match_arm.guard is not None:
                    guard_ty = self.check_expr(match_arm.guard, BOOL)
                    if guard_ty.name not in {"Bool", "<error>"}:
                        self._error("E3022", "match guard must be Bool", match_arm.guard.span)
                arm_returns.append(self._check_block(match_arm.block))
                self.scope = previous
            self._exhaustiveness(stmt, ty)
            return bool(stmt.arms) and all(arm_returns)
        if isinstance(stmt, WhileStmt):
            cond = self.check_expr(stmt.cond, BOOL)
            if cond.name not in {"Bool", "<error>"}:
                self._error("E3022", "condition must be Bool", stmt.cond.span)
            self.loop_depth += 1
            self._check_block(stmt.body)
            self.loop_depth -= 1
            return False
        if isinstance(stmt, ForStmt):
            iter_ty = self.check_expr(stmt.expr, None)
            elem = self._iter_element(iter_ty, stmt.expr.span)
            child = Scope(parent=self.scope)
            self._define(child, stmt.name, Binding(stmt.name, "local", elem, span=stmt.span))
            previous = self.scope
            self.scope = child
            self.loop_depth += 1
            self._check_block(stmt.body)
            self.loop_depth -= 1
            self.scope = previous
            return False
        if isinstance(stmt, UsingStmt):
            ty = self.check_expr(stmt.expr, None)
            if not is_resource(ty) and ty.name != "<error>":
                self._error("E3072", "`using` binds a resource", stmt.expr.span)
            child = Scope(parent=self.scope)
            self._define(child, stmt.name, Binding(stmt.name, "local", ty, span=stmt.span))
            previous = self.scope
            self.scope = child
            returned = self._check_block(stmt.body)
            self.scope = previous
            return returned
        if isinstance(stmt, ExprStmt):
            self._check_expr_stmt(stmt)
            return False
        return False

    def _check_set(self, stmt: SetStmt) -> None:
        binding = self.scope.lookup(stmt.place[0])
        if binding is None or not binding.mutable:
            self._error(
                "E2030", f"`set` requires a `var`, and `{stmt.place[0]}` is not one", stmt.span
            )
            return
        ty = binding.ty
        for name in stmt.place[1:]:
            info = self.records.get(ty.name)
            if info is None:
                self._error("E3004", f"`{ty.display()}` has no field `{name}`", stmt.span)
                return
            env = dict(zip(info.type_params, ty.args, strict=False))
            found = None
            for field_name, field_ty in info.fields:
                if field_name == name:
                    found = substitute(field_ty, env)
            if found is None:
                self._error("E3082", f"record `{ty.name}` has no field `{name}`", stmt.span)
                return
            ty = found
        got = self.check_expr(stmt.expr, ty)
        self._assignable(ty, got, stmt.expr.span, literal=stmt.expr)

    def _check_expr_stmt(self, stmt: ExprStmt) -> None:
        if not isinstance(stmt.expr, CallExpr):
            self._error("E3005", "an expression statement must be a function call", stmt.span)
            self.check_expr(stmt.expr, None)
            return
        ty = self.check_expr(stmt.expr, None)
        if ty.name == "Result":
            self._error(
                "E3002",
                "a Result cannot be ignored",
                stmt.span,
                fix="handle it, use `try`, or write `let _ = ...`",
            )
        elif ty.name not in {"Unit", "<error>"}:
            self._error(
                "W3001",
                f"the value `{ty.display()}` is ignored",
                stmt.span,
                fix="use the value or discard it with `let _ = ...`",
            )

    def check_expr(self, expr: Expr, expected: Type | None) -> Type:
        """The type of `expr`, reporting any errors in it.

        `expected` is the type the context wants, or `None`, and steers inference, for
        example of `None` and lambdas. `POISON` stands for a type that could not be determined.
        """
        if isinstance(expr, LiteralExpr):
            return self._check_literal(expr, expected)
        if isinstance(expr, NameExpr):
            return self._check_name(expr, expected)
        if isinstance(expr, GroupExpr):
            return self.check_expr(expr.expr, expected)
        if isinstance(expr, UnaryExpr):
            return self._check_unary(expr, expected)
        if isinstance(expr, BinaryExpr):
            return self._check_binary(expr)
        if isinstance(expr, CallExpr):
            return self._check_call(expr, expected)
        if isinstance(expr, FieldExpr):
            return self._check_field(expr, expected, called=False)
        if isinstance(expr, WithExpr):
            return self._check_with(expr)
        if isinstance(expr, ListExpr):
            return self._check_list(expr, expected)
        if isinstance(expr, MapExpr):
            return self._check_map(expr, expected)
        if isinstance(expr, LambdaExpr):
            return self._check_lambda(expr, expected)
        if isinstance(expr, ResultExpr):
            if not self.in_ensures or self.fn_ret is None:
                self._error("E5001", "`result` is only allowed inside `ensures`", expr.span)
                return POISON
            return self.fn_ret
        if isinstance(expr, OldExpr):
            if not self.in_ensures:
                self._error("E5001", "`old` is only allowed inside `ensures`", expr.span)
                return POISON
            return self.check_expr(expr.expr, None)
        return POISON

    def _check_literal(self, expr: LiteralExpr, expected: Type | None) -> Type:
        if expr.kind == "int":
            if expected is not None and expected.name == "Int64":
                self._error(
                    "E3023",
                    "integer literals are always Int",
                    expr.span,
                    fix='convert with Int64.from_int(...).expect_some("fits")',
                )
            return INT
        if expr.kind == "float":
            return FLOAT
        if expr.kind == "text":
            return TEXT
        if expr.kind == "bool":
            return BOOL
        return POISON

    def _check_name(self, expr: NameExpr, expected: Type | None) -> Type:
        binding = self.scope.lookup(expr.name)
        if binding is None and expr.name in self.iface_fns:
            return self._iface_value(expr, expected)
        if binding is None:
            self._error("E2000", f"unknown name `{expr.name}`", expr.span)
            return POISON
        if binding.kind == "ambiguous":
            self._error(
                "E2022",
                f"`{expr.name}` is ambiguous",
                expr.span,
                fix="qualify the case with its choice name",
            )
            return POISON
        if binding.kind == "type":
            if expr.name == "Unit":
                return UNIT
            self._error("E3000", f"`{expr.name}` is a type, not a value", expr.span)
            return POISON
        if binding.kind == "case":
            payload = binding.payload
            fields: tuple[str, ...] = ()
            if isinstance(payload, tuple):
                fields = payload[1]
            if fields:
                self._error("E3006", f"case `{expr.name}` needs arguments", expr.span)
                return POISON
            return self._case_type(expr.name, binding, expected, expr.span)
        if (
            binding.kind in {"builtin", "function"}
            and expected is not None
            and expected.name == "function"
        ):
            return binding.ty
        if binding.kind == "var" and self._inside_lambda:
            self._error("E3071", "a lambda cannot capture a `var`", expr.span)
        return binding.ty

    def _case_type(self, name: str, binding: Binding, expected: Type | None, span: Span) -> Type:
        payload = binding.payload
        type_name = payload[0] if isinstance(payload, tuple) else binding.ty.name
        if type_name == "Option":
            if expected is not None and expected.name == "Option":
                return expected
            self._error("E3010", "`None` needs a known Option type", span)
            return opt_unknown()
        if type_name == "Json":
            return t("Json")
        if type_name == "Ordering":
            return ORDERING
        info = self.choices.get(type_name)
        if info is None:
            return t(type_name)
        if expected is not None and expected.name == type_name:
            return expected
        if info.type_params:
            self._error("E3010", f"`{name}` needs a known type", span)
        return t(type_name, *(var(param) for param in info.type_params))

    def _check_unary(self, expr: UnaryExpr, expected: Type | None) -> Type:
        if expr.op == "not":
            got = self.check_expr(expr.expr, BOOL)
            if got.name not in {"Bool", "<error>"}:
                self._error("E3022", "`not` needs a Bool", expr.span)
            return BOOL
        if expr.op == "-":
            operand_expected = (
                expected if expected is not None and expected.name in NUMERIC else None
            )
            got = self.check_expr(expr.expr, operand_expected)
            if _is_int_literal(expr) and expected is not None and expected.name == "Int64":
                self._error(
                    "E3023",
                    "integer literals are always Int",
                    expr.span,
                    fix="convert with Int64.from_int",
                )
                return INT64
            if got.name not in NUMERIC and got.name != "<error>":
                self._error("E3000", f"unary `-` is not defined on `{got.display()}`", expr.span)
                return POISON
            return got
        if expr.op == "try":
            got = self.check_expr(expr.expr, None)
            return self._check_try(got, expr.span)
        return POISON

    def _check_try(self, got: Type, span: Span) -> Type:
        ret = self.fn_ret
        if got.name == "Option" and got.args:
            if ret is None or ret.name != "Option":
                self._error("E3060", "`try` on Option requires the function to return Option", span)
            return got.args[0]
        if got.name == "Result" and len(got.args) == 2:
            if ret is None or ret.name != "Result" or not types_equal(ret.args[1], got.args[1]):
                self._error(
                    "E3060",
                    "`try` error type does not match the function's Result",
                    span,
                    fix="convert the error with map_error",
                )
            return got.args[0]
        self._error("E3060", "`try` expects Option or Result", span)
        return POISON

    def _needs_context(self, expr: Expr) -> bool:
        """`None`, a payload-free case, or an empty list: its type comes from the other operand."""
        if isinstance(expr, GroupExpr):
            return self._needs_context(expr.expr)
        if isinstance(expr, ListExpr):
            return not expr.elements
        if isinstance(expr, NameExpr):
            binding = self.scope.lookup(expr.name)
            return binding is not None and binding.kind == "case"
        return False

    def _check_binary(self, expr: BinaryExpr) -> Type:
        if expr.op in {"and", "or"}:
            for side in (expr.left, expr.right):
                got = self.check_expr(side, BOOL)
                if got.name not in {"Bool", "<error>"}:
                    self._error("E3022", f"`{expr.op}` needs Bool", side.span)
            return BOOL
        if (
            expr.op in {"==", "!="}
            and self._needs_context(expr.left)
            and not self._needs_context(expr.right)
        ):
            right = self.check_expr(expr.right, None)
            left = self.check_expr(expr.left, _context(right))
        else:
            left = self.check_expr(expr.left, None)
            context = (
                _context(left)
                if expr.op in {"==", "!="} and self._needs_context(expr.right)
                else None
            )
            right = self.check_expr(expr.right, context)
        if _has_error(left) or _has_error(right):
            return BOOL if expr.op in {"==", "!=", "<", "<=", ">", ">="} else POISON
        if expr.op in {"==", "!="}:
            if not types_equal(left, right):
                self._error(
                    "E3000", f"cannot compare `{left.display()}` and `{right.display()}`", expr.span
                )
                return BOOL
            if not self._equatable(left):
                self._error(
                    "E3026", f"`{left.display()}` cannot be compared with `{expr.op}`", expr.span
                )
            return BOOL
        if expr.op in {"<", "<=", ">", ">="}:
            if not types_equal(left, right) or left.name not in {"Int", "Int64", "Float", "Text"}:
                self._error(
                    "E3025",
                    "ordering operators are only defined for Int, Int64, Float, and Text",
                    expr.span,
                    fix="use `compare` for other Comparable types",
                )
            return BOOL
        if not types_equal(left, right):
            if {left.name, right.name} == {"Int", "Int64"}:
                self._error(
                    "E3024",
                    "Int and Int64 cannot be mixed",
                    expr.span,
                    fix="convert with Int64.from_int or Int64.to_int",
                )
            else:
                self._error("E3000", f"`{expr.op}` needs two values of the same type", expr.span)
            return POISON
        if expr.op == "+" and left.name == "Text":
            self._error(
                "E3020", "`+` is not defined on Text", expr.span, fix="use Text.concat or Text.join"
            )
            return POISON
        if expr.op == "/" and left.name != "Float":
            self._error(
                "E3021", "`/` is only defined on Float", expr.span, fix="use `div` for integers"
            )
            return POISON
        if expr.op in {"div", "mod"} and left.name not in {"Int", "Int64"}:
            self._error("E3000", f"`{expr.op}` is only defined on Int and Int64", expr.span)
            return POISON
        if expr.op in {"+", "-", "*"} and left.name not in NUMERIC:
            self._error("E3000", f"`{expr.op}` is not defined on `{left.display()}`", expr.span)
            return POISON
        return left

    def _check_call(self, expr: CallExpr, expected: Type | None) -> Type:
        if isinstance(expr.func, FieldExpr):
            return self._check_field(
                expr.func, expected, called=True, args=expr.args, call_span=expr.span
            )
        binding = self.scope.lookup(expr.func.name) if isinstance(expr.func, NameExpr) else None
        if binding is not None and binding.kind == "case":
            return self._construct_case(binding, expr, expected)
        if binding is not None and binding.kind == "record":
            return self._construct_record(str(binding.name), expr, expected)
        if isinstance(expr.func, NameExpr) and binding is None and expr.func.name in self.iface_fns:
            return self._call_interface(
                expr.func, self.iface_fns[expr.func.name], expr.args, expected, expr.span
            )
        ty = self.check_expr(expr.func, None)
        if (
            binding is not None
            and binding.kind == "builtin"
            and isinstance(binding.payload, Builtin)
        ):
            return self._call_builtin(
                binding.payload, expr.args, expected, expr.span, receiver=None
            )
        if (
            binding is not None
            and binding.kind == "function"
            and isinstance(binding.payload, FunctionDecl)
        ):
            return self._call_function(binding.payload, expr.args, expected, expr.span)
        if (
            binding is not None
            and binding.kind == "foreign"
            and isinstance(binding.payload, ForeignDecl)
        ):
            return self._call_foreign(binding.payload, expr.args, expected, expr.span)
        if ty.name == "function" and ty.ret is not None:
            self._check_args_against(ty.params, expr.args, expr.span)
            return ty.ret
        if ty.name != "<error>":
            self._error("E3000", "this value cannot be called", expr.span)
        return POISON

    def _check_field(
        self,
        expr: FieldExpr,
        expected: Type | None,
        *,
        called: bool,
        args: Sequence[Arg] | None = None,
        call_span: Span | None = None,
    ) -> Type:
        if isinstance(expr.recv, NameExpr):
            binding = self.scope.lookup(expr.recv.name)
            if binding is not None and binding.kind in {"namespace", "type", "record", "choice"}:
                return self._check_namespace_field(
                    binding, expr, expected, called, args, call_span or expr.span
                )
        recv_ty = self.check_expr(expr.recv, None)
        if recv_ty.name == "<error>":
            return POISON
        info = self.records.get(recv_ty.name)
        if info is not None and not called:
            env = dict(zip(info.type_params, recv_ty.args, strict=False))
            for name, field_ty in info.fields:
                if name == expr.name:
                    return substitute(field_ty, env)
        method = methods_of(recv_ty.name).get(public_name(expr.name))
        user_method = None if method is not None else self._user_method(recv_ty, expr.name)
        if not called:
            if info is not None:
                self._error(
                    "E3082", f"record `{recv_ty.name}` has no field `{expr.name}`", expr.span
                )
            else:
                self._error("E3004", f"`{recv_ty.display()}` has no field `{expr.name}`", expr.span)
            return POISON
        assert args is not None
        if method is not None:
            if method.name == "at":
                self._maybe_warn_at(expr, args, call_span or expr.span)
            return self._call_builtin(
                method, args, expected, call_span or expr.span, receiver=recv_ty
            )
        if user_method is not None:
            return self._call_function(
                user_method, args, expected, call_span or expr.span, receiver=recv_ty
            )
        candidates = self._impl_methods(recv_ty, expr.name)
        if candidates:
            return self._call_interface(
                None, candidates, args, expected, call_span or expr.span, receiver=recv_ty
            )
        self._error("E3004", f"`{recv_ty.display()}` has no method `{expr.name}`", expr.span)
        return POISON

    def _impl_methods(self, recv_ty: Type, name: str) -> list[IfaceFn]:
        """Interface functions `recv.name(...)` can mean, per §5.13."""
        return [
            fn
            for fn in self.iface_fns.get(name, [])
            if fn.type_param is not None
            and fn.dispatch == 0
            and self._implements(recv_ty, fn.iface)
        ]

    def _implements(self, ty: Type, iface: str) -> bool:
        if ty.name == "<error>":
            return True
        if ty.is_var:
            return iface in self.constraints.get(ty.name, frozenset())
        if iface == "Equatable":
            return self._equatable(ty)
        if iface == "Hashable":
            return self._hashable(ty)
        if iface == "Showable":
            return self._showable(ty)
        if iface == "Comparable" and ty.name in COMPARABLE:
            return True
        return (iface, ty.name) in self.impls

    def _require_constraint(self, ty: Type, iface: str, span: Span) -> None:
        if self._implements(ty, iface):
            return
        shown = ty.display()
        if iface == "Showable":
            self._error("E3045", f"`{shown}` is not Showable", span)
        elif iface == "Hashable":
            self._error("E3042", f"`{shown}` is not Hashable", span)
        elif ty.is_var:
            self._error(
                "E3046",
                f"`{shown}` is not known to implement `{iface}`",
                span,
                fix=f"add the constraint `{shown}: {iface}`",
            )
        else:
            user_type = ty.name in self.records or ty.name in self.choices
            fix = (
                f"add `implements {iface}[{shown}]`" if user_type and iface != "Equatable" else None
            )
            self._error("E3046", f"`{shown}` does not implement `{iface}`", span, fix=fix)

    def _call_interface(
        self,
        node: NameExpr | None,
        candidates: list[IfaceFn],
        args: Sequence[Arg],
        expected: Type | None,
        span: Span,
        receiver: Type | None = None,
    ) -> Type:
        typed_args = [arg for arg in args if isinstance(arg, Arg)]
        if any(arg.name is not None for arg in typed_args):
            self._error(
                "E3081", "named arguments are only allowed when constructing a record", span
            )
        arity = len(typed_args) + (0 if receiver is None else 1)
        fn = next((item for item in candidates if len(item.params) == arity), candidates[0])
        if len(fn.params) != arity:
            self._error("E3003", f"`{fn.name}` expects {len(fn.params)} arguments", span)
            return POISON
        env: dict[str, Type] = {}
        params = [ty for _name, ty in fn.params]
        if receiver is not None:
            unify(params[0], receiver, env)
            params = params[1:]
        if expected is not None:
            unify(fn.ret, expected, env)
        for pattern, arg in zip(params, typed_args, strict=False):
            wanted = substitute(pattern, env)
            got = self.check_expr(arg.expr, None if _has_var(wanted) else wanted)
            unify(pattern, got, env)
            self._assignable(substitute(pattern, env), got, arg.span, literal=arg.expr)
        self._require_effects(fn.effects, span, fn.name)
        ret = substitute(fn.ret, env)
        resolved = self._resolve_impl(fn, env, span)
        if node is not None and resolved is not None:
            node.resolved = resolved
        return ret

    def _iface_value(self, expr: NameExpr, expected: Type | None) -> Type:
        """An interface function used as a value takes its types from the context."""
        candidates = self.iface_fns[expr.name]
        if expected is None or expected.ret is None:
            self._error(
                "E3010",
                f"cannot infer which implementation of `{expr.name}` to use",
                expr.span,
                fix="call it, or use it where a function type is expected",
            )
            return POISON
        fn = next((item for item in candidates if len(item.params) == len(expected.params)), None)
        if fn is None:
            self._error(
                "E3000", f"`{expr.name}` does not have type {expected.display()}", expr.span
            )
            return POISON
        env: dict[str, Type] = {}
        own = fn_type(tuple(ty for _name, ty in fn.params), fn.ret)
        unify(own, expected, env)
        if fn.effects:
            self._error("E4002", "an effectful function cannot be used as a value", expr.span)
        expr.resolved = self._resolve_impl(fn, env, expr.span)
        return substitute(own, env)

    def _resolve_impl(
        self, fn: IfaceFn, env: dict[str, Type], span: Span
    ) -> tuple[str, str | None, int | None] | None:
        """Which implementation a call to an interface function runs."""
        if fn.type_param is None:
            self._error(
                "E3046",
                f"`{fn.iface}` takes no type, so no implements block can supply `{fn.name}`",
                span,
                fix=f"define a top-level function `{fn.name}`",
            )
            return None
        chosen = env.get(fn.type_param)
        if chosen is None:
            self._error("E3010", f"cannot infer which implementation of `{fn.name}` to call", span)
            return None
        if chosen.name == "<error>":
            return None
        if not self._implements(chosen, fn.iface):
            self._require_constraint(chosen, fn.iface, span)
            return None
        if chosen.is_var:
            if fn.dispatch is None:
                self._error(
                    "E3010",
                    f"cannot pick an implementation of `{fn.name}` for type parameter "
                    f"{chosen.name}: none of its parameters has type {fn.type_param}, and "
                    "types are not available at run time",
                    span,
                    fix=f"call `{fn.name}` where {fn.type_param} is a concrete type, or give it "
                    f"a parameter of type {fn.type_param}",
                )
                return None
            return (fn.iface, None, fn.dispatch)
        return (fn.iface, chosen.name, None)

    def _check_namespace_field(
        self,
        binding: Binding,
        expr: FieldExpr,
        expected: Type | None,
        called: bool,
        args: Sequence[Arg] | None,
        span: Span,
    ) -> Type:
        members = self._namespace_members(binding)
        member = members.get(expr.name)
        if member is None:
            if binding.kind == "namespace":
                module_name = binding.payload if isinstance(binding.payload, str) else binding.name
                self._error(
                    "E2005", f"`{module_name}` has no public member `{expr.name}`", expr.span
                )
            else:
                self._error("E3004", f"`{binding.name}` has no member `{expr.name}`", expr.span)
            return POISON
        if member.kind == "const":
            if called:
                self._error("E3000", f"`{expr.name}` is not a function", expr.span)
                return POISON
            return member.ty
        if member.kind == "case":
            if not called:
                return self._case_type(expr.name, member, expected, expr.span)
            assert args is not None
            return self._construct_case(member, _fake_call(expr.span, args), expected)
        if member.kind == "builtin" and isinstance(member.payload, Builtin):
            builtin = member.payload
            if not called:
                if builtin.effects:
                    self._error(
                        "E4002", "an effectful function cannot be used as a value", expr.span
                    )
                return self._builtin_fn_type(builtin)
            assert args is not None
            return self._call_builtin(builtin, args, expected, span, receiver=None)
        if member.kind == "type":
            return member.ty
        self._error("E3004", f"`{binding.name}` has no member `{expr.name}`", expr.span)
        return POISON

    def _namespace_members(self, binding: Binding) -> dict[str, Binding]:
        if binding.kind == "namespace" and isinstance(binding.payload, str):
            return self._namespaces.get(binding.payload, {})
        if binding.name in self._namespaces:
            return self._namespaces[binding.name]
        if binding.kind == "record" and isinstance(binding.payload, RecordDecl):
            return {}
        if binding.kind == "choice":
            info = self.choices.get(binding.name)
            if info is None:
                return {}
            return {
                case: Binding(
                    case,
                    "case",
                    t(info.name),
                    payload=(info.name, tuple(name for name, _ in fields)),
                )
                for case, fields in info.cases.items()
            }
        return {}

    def _call_builtin(
        self,
        builtin: Builtin,
        args: Sequence[Arg],
        expected: Type | None,
        span: Span,
        receiver: Type | None,
    ) -> Type:
        from tersalang.ast import Arg

        typed_args = [arg for arg in args if isinstance(arg, Arg)]
        if any(arg.name is not None for arg in typed_args):
            self._error(
                "E3081", "named arguments are only allowed when constructing a record", span
            )
        if builtin.rl_forbidden and self.mode == "rl":
            self._error("E4011", f"`{builtin.name}` is not available in RL mode", span)
        if builtin.name in TRANSCENDENTAL and self.mode == "rl":
            self._error("E4011", f"`{builtin.name}` is not available in RL mode", span)
        params = list(builtin.params)
        if receiver is not None and params:
            params = params[1:]
        if builtin.id == "list.sort" and len(typed_args) == 1 and receiver is not None:
            params = params[:1]
        if len(typed_args) != len(params):
            self._error(
                "E3003",
                f"`{builtin.name}` expects {len(params)} arguments, found {len(typed_args)}",
                span,
            )
            return POISON
        env: dict[str, Type] = {}
        if receiver is not None and builtin.params:
            unify(builtin.params[0][1], receiver, env)
        if expected is not None:
            unify(builtin.ret, expected, env)
        for param, arg in zip(params, typed_args, strict=False):
            wanted = substitute(param[1], env)
            if wanted.is_var and expected is not None and builtin.ret.is_var:
                wanted = expected
            got = self.check_expr(arg.expr, None if wanted.is_var else wanted)
            if not unify(param[1], got, env) and wanted.name != "<error>":
                concrete = substitute(param[1], env)
                if concrete.is_var:
                    self._error("E3010", f"cannot infer the type of `{builtin.name}`", arg.span)
                elif not types_equal(concrete, got):
                    self._assignable(concrete, got, arg.span, literal=arg.expr)
        missing = [name for name in builtin.type_params if name not in env]
        if missing and builtin.id not in {"list.sort"}:
            # Not bound by the receiver, the expected type, or any argument.
            self._error("E3010", f"cannot infer type parameter {missing[0]}", span)
            for name in missing:
                env.setdefault(name, POISON)
        if builtin.type_params and builtin.id in {"math.min", "math.max", "math.abs", "math.clamp"}:
            chosen = env.get("T", POISON)
            if chosen.name not in NUMERIC:
                self._error("E3027", f"`{builtin.name}` only accepts Int, Int64, or Float", span)
        if builtin.id == "show":
            chosen = env.get("T", POISON)
            if not self._showable(chosen):
                self._error("E3045", f"`{chosen.display()}` is not Showable", span)
        ret = substitute(builtin.ret, env)
        if expected is None or expected.name != ret.name:
            self._require_hashable_key(ret, span)
        self._require_effects(builtin.effects, span, builtin.name)
        return ret

    def _call_function(
        self,
        decl: FunctionDecl,
        args: Sequence[Arg],
        expected: Type | None,
        span: Span,
        receiver: Type | None = None,
    ) -> Type:
        from tersalang.ast import Arg

        typed_args = [arg for arg in args if isinstance(arg, Arg)]
        if any(arg.name is not None for arg in typed_args):
            self._error(
                "E3081", "named arguments are only allowed when constructing a record", span
            )
        params = list(decl.sig.params)
        type_env = {param.name: var(param.name) for param in decl.sig.type_params}
        env: dict[str, Type] = {}
        if receiver is not None and params:
            unify(self._resolve_type(params[0].ty, type_env), receiver, env)
            params = params[1:]
        if len(typed_args) != len(params):
            self._error("E3003", f"`{decl.sig.name}` expects {len(params)} arguments", span)
            return POISON
        ret = self._resolve_type(decl.sig.ret, type_env)
        if type_env and expected is not None:
            unify(ret, expected, env)
        for param, arg in zip(params, typed_args, strict=False):
            pattern = self._resolve_type(param.ty, type_env)
            wanted = substitute(pattern, env)
            got = self.check_expr(arg.expr, None if wanted.is_var else wanted)
            if type_env:
                unify(pattern, got, env)
                wanted = substitute(pattern, env)
            self._assignable(wanted, got, arg.span, literal=arg.expr)
        for type_param in decl.sig.type_params:
            chosen = env.get(type_param.name)
            if chosen is None:
                continue
            for constraint in type_param.constraints:
                if constraint.name in self.interfaces or constraint.name in BUILTIN_INTERFACES:
                    self._require_constraint(chosen, constraint.name, span)
        effects = frozenset(name for name, _ in decl.sig.effects)
        self._require_effects(effects, span, decl.sig.name)
        return substitute(ret, env)

    def _call_foreign(
        self,
        decl: ForeignDecl,
        args: Sequence[Arg],
        expected: Type | None,
        span: Span,
    ) -> Type:
        typed_args = [arg for arg in args if isinstance(arg, Arg)]
        if any(arg.name is not None for arg in typed_args):
            self._error(
                "E3081", "named arguments are only allowed when constructing a record", span
            )
        params = list(decl.sig.params)
        if len(typed_args) != len(params):
            self._error("E3003", f"`{decl.sig.name}` expects {len(params)} arguments", span)
            return POISON
        env = {param.name: var(param.name) for param in decl.sig.type_params}
        for param, arg in zip(params, typed_args, strict=False):
            wanted = self._resolve_type(param.ty, env)
            got = self.check_expr(arg.expr, wanted)
            self._assignable(wanted, got, arg.span, literal=arg.expr)
        self._require_effects(
            frozenset(name for name, _span in decl.sig.effects), span, decl.sig.name
        )
        ret = self._resolve_type(decl.sig.ret, env)
        if expected is not None:
            self._assignable(expected, ret, span)
        return ret

    def _reject_python_type(self, ty: Type, role: str, span: Span, *, as_return: bool) -> None:
        if as_return and _is_python_result(ty):
            obstacle = self._python_obstacle(ty.args[0])
            if obstacle is not None:
                self._error(
                    "E4020",
                    f"{role} contains {obstacle}, which can't cross the Python boundary",
                    span,
                )
            return
        obstacle = self._python_obstacle(ty)
        if obstacle is not None:
            self._error(
                "E4020",
                f"{role} has {obstacle}, which can't cross the Python boundary",
                span,
            )

    def _python_obstacle(self, ty: Type) -> str | None:
        if ty.name == "<error>" or ty.is_var:
            return None
        if ty.name == "function" or ty.ret is not None:
            return "a function type"
        if ty.name == "File":
            return "a resource type"
        if ty.name in {"Set", "MutableList", "MutableMap"}:
            return f"`{ty.name}`"
        if ty.name == "Map":
            if len(ty.args) < 2 or ty.args[0].name != "Text":
                return "a Map whose keys aren't Text"
            nested = self._python_obstacle(ty.args[1]) if len(ty.args) == 2 else None
            return None if nested is None else f"a Map containing {nested}"
        if ty.name in {"List", "Option"} and ty.args:
            nested = self._python_obstacle(ty.args[0])
            return None if nested is None else f"a {ty.name} containing {nested}"
        if ty.name == "Result":
            return "`Result`"
        if ty.name in {"Int", "Int64", "Float", "Bool", "Text", "Bytes", "Unit"}:
            return None
        if ty.name in self.records:
            for _name, field_ty in self.records[ty.name].fields:
                nested = self._python_obstacle(field_ty)
                if nested is not None:
                    return nested
            return None
        if ty.name in self.choices:
            for fields in self.choices[ty.name].cases.values():
                for _name, field_ty in fields:
                    nested = self._python_obstacle(field_ty)
                    if nested is not None:
                        return nested
            return None
        if ty.name in {
            "Ordering",
            "FileError",
            "Utf8Error",
            "Json",
            "JsonError",
            "PythonError",
            "Entry",
        }:
            return None
        return f"`{ty.display()}`"

    def _construct_case(self, binding: Binding, expr: CallExpr, expected: Type | None) -> Type:
        if any(arg.name is not None for arg in expr.args):
            self._error(
                "E3081", "choice cases are constructed with positional arguments", expr.span
            )
        payload = binding.payload
        type_name = payload[0] if isinstance(payload, tuple) else binding.ty.name
        field_names = payload[1] if isinstance(payload, tuple) else ()
        if len(expr.args) != len(field_names):
            self._error(
                "E3003", f"case `{binding.name}` expects {len(field_names)} arguments", expr.span
            )
            return POISON
        info = self.choices.get(type_name)
        if type_name == "Option":
            inner = (
                self.check_expr(
                    expr.args[0].expr,
                    expected.args[0]
                    if expected and expected.name == "Option" and expected.args
                    else None,
                )
                if expr.args
                else UNIT
            )
            return opt(inner) if type_name == "Option" and expr.args else t("Option", inner)
        if type_name == "Result":
            if binding.name == "Ok":
                err = (
                    expected.args[1]
                    if expected is not None
                    and expected.name == "Result"
                    and len(expected.args) == 2
                    else None
                )
                value_ty = self.check_expr(
                    expr.args[0].expr, expected.args[0] if expected and expected.args else None
                )
                if err is None:
                    self._error("E3010", "cannot infer the error type of Ok", expr.span)
                    err = POISON
                return res(value_ty, err)
            ok_ty = (
                expected.args[0]
                if expected is not None and expected.name == "Result" and expected.args
                else None
            )
            err_ty = self.check_expr(expr.args[0].expr, None)
            if ok_ty is None:
                self._error("E3010", "cannot infer the Ok type of Error", expr.span)
                ok_ty = POISON
            return res(ok_ty, err_ty)
        if type_name == "Json":
            for arg, _field in zip(expr.args, field_names, strict=False):
                self.check_expr(arg.expr, None)
            return t("Json")
        if info is None:
            for arg in expr.args:
                self.check_expr(arg.expr, None)
            return t(type_name)
        env: dict[str, Type] = {}
        if expected is not None and expected.name == type_name:
            env = dict(zip(info.type_params, expected.args, strict=False))
        fields = info.cases.get(binding.name, ())
        for arg, (_name, field_ty) in zip(expr.args, fields, strict=False):
            wanted = substitute(field_ty, env)
            got = self.check_expr(arg.expr, None if wanted.is_var else wanted)
            unify(field_ty, got, env)
        if any(name not in env for name in info.type_params):
            self._error("E3010", f"cannot infer the type arguments of `{type_name}`", expr.span)
        built = t(type_name, *(env.get(name, POISON) for name in info.type_params))
        self._require_type_constraints(built, expr.span, type_vars=True)
        return built

    def _construct_record(self, name: str, expr: CallExpr, expected: Type | None) -> Type:
        info = self.records.get(name)
        if info is None:
            self._error("E3008", f"unknown record `{name}`", expr.span)
            return POISON
        if any(arg.name is None for arg in expr.args):
            self._error(
                "E3080",
                "records are constructed with named fields",
                expr.span,
                fix=f"write {name}(field = value)",
            )
        seen: set[str] = set()
        env: dict[str, Type] = {}
        if expected is not None and expected.name == name:
            env = dict(zip(info.type_params, expected.args, strict=False))
        values: dict[str, Type] = {}
        for arg in expr.args:
            if arg.name is None:
                self.check_expr(arg.expr, None)
                continue
            if arg.name in seen:
                self._error("E3082", f"field `{arg.name}` is duplicated", arg.span)
            seen.add(arg.name)
            field_ty = next((ty for field_name, ty in info.fields if field_name == arg.name), None)
            if field_ty is None:
                self._error("E3082", f"record `{name}` has no field `{arg.name}`", arg.span)
                self.check_expr(arg.expr, None)
                continue
            wanted = substitute(field_ty, env)
            got = self.check_expr(arg.expr, None if wanted.is_var else wanted)
            values[arg.name] = got
            unify(field_ty, got, env)
        for field_name, _ty in info.fields:
            if field_name not in seen:
                self._error("E3082", f"missing field `{field_name}`", expr.span)
        if any(param not in env for param in info.type_params):
            self._error("E3010", f"cannot infer the type arguments of `{name}`", expr.span)
        built = t(name, *(env.get(param, POISON) for param in info.type_params))
        self._require_type_constraints(built, expr.span, type_vars=True)
        return built

    def _check_with(self, expr: WithExpr) -> Type:
        ty = self.check_expr(expr.recv, None)
        info = self.records.get(ty.name)
        if info is None:
            if ty.name != "<error>":
                self._error("E3000", "`with` updates a record", expr.span)
            return POISON
        env = dict(zip(info.type_params, ty.args, strict=False))
        seen: set[str] = set()
        for init in expr.fields:
            if init.name in seen:
                self._error("E3082", f"field `{init.name}` is duplicated", init.span)
            seen.add(init.name)
            field_ty = next((item for name, item in info.fields if name == init.name), None)
            if field_ty is None:
                self._error("E3082", f"record `{ty.name}` has no field `{init.name}`", init.span)
                continue
            got = self.check_expr(init.expr, substitute(field_ty, env))
            self._assignable(substitute(field_ty, env), got, init.span, literal=init.expr)
        return ty

    def _check_list(self, expr: ListExpr, expected: Type | None) -> Type:
        elem_expected = (
            expected.args[0]
            if expected is not None and expected.name == "List" and expected.args
            else None
        )
        if not expr.elements:
            if elem_expected is None:
                self._error("E3010", "an empty list needs a known element type", expr.span)
                return lst(POISON)
            return lst(elem_expected)
        if elem_expected is not None and elem_expected.is_var:
            elem_expected = None
        types = [self.check_expr(element, elem_expected) for element in expr.elements]
        head = elem_expected or types[0]
        for element, got in zip(expr.elements, types, strict=False):
            self._assignable(head, got, element.span, literal=element)
        return lst(head)

    def _check_map(self, expr: MapExpr, expected: Type | None) -> Type:
        key_expected = (
            expected.args[0]
            if expected is not None and expected.name == "Map" and len(expected.args) == 2
            else None
        )
        val_expected = (
            expected.args[1]
            if expected is not None and expected.name == "Map" and len(expected.args) == 2
            else None
        )
        if not expr.entries:
            if key_expected is None or val_expected is None:
                self._error("E3010", "an empty map needs a known key and value type", expr.span)
                return mp(POISON, POISON)
            return mp(key_expected, val_expected)
        if key_expected is not None and key_expected.is_var:
            key_expected = None
        if val_expected is not None and val_expected.is_var:
            val_expected = None
        key_types = []
        val_types = []
        for key, value in expr.entries:
            key_types.append(self.check_expr(key, key_expected))
            val_types.append(self.check_expr(value, val_expected))
        key_ty = key_expected or key_types[0]
        val_ty = val_expected or val_types[0]
        if not self._hashable(key_ty):
            self._error("E3042", f"`{key_ty.display()}` cannot be a map key", expr.span)
        return mp(key_ty, val_ty)

    def _check_lambda(self, expr: LambdaExpr, expected: Type | None) -> Type:
        child = Scope(parent=self.scope)
        params: list[Type] = []
        for param in expr.params:
            ty = self._resolve_type(param.ty)
            params.append(ty)
            self._define(child, param.name, Binding(param.name, "param", ty, span=param.span))
            if contains_mutable(ty):
                self._error(
                    "E3070", "a lambda cannot capture or take a mutable collection", param.span
                )
        ret = self._resolve_type(expr.ret)
        previous_ret = self.fn_ret
        previous_effects = self.fn_effects
        previous_scope = self.scope
        previous_lambda = self._inside_lambda
        self.fn_ret = ret
        self.fn_effects = frozenset()
        self.scope = child
        self._inside_lambda = True
        got = self.check_expr(expr.body, ret)
        self._assignable(ret, got, expr.body.span, literal=expr.body, code="E3033")
        self._inside_lambda = previous_lambda
        self.scope = previous_scope
        self.fn_ret = previous_ret
        self.fn_effects = previous_effects
        _ = expected
        return fn_type(tuple(params), ret)

    def _check_pattern(self, pattern: object, ty: Type) -> None:
        if isinstance(pattern, WildPat):
            return
        if isinstance(pattern, BindPat):
            self._define(
                self.scope, pattern.name, Binding(pattern.name, "local", ty, span=pattern.span)
            )
            return
        if isinstance(pattern, LitPat):
            if pattern.kind == "int" and ty.name == "Int64":
                self._error("E3023", "integer literals are always Int", pattern.span)
            return
        if isinstance(pattern, CtorPat):
            info = self._choice_for_type(ty)
            case_name = pattern.name
            if info is None or case_name not in info.cases:
                self._error(
                    "E3000", f"`{case_name}` is not a case of `{ty.display()}`", pattern.span
                )
                return
            fields = info.cases[case_name]
            sub = pattern.fields or []
            if len(sub) != len(fields):
                self._error(
                    "E3003", f"case `{case_name}` expects {len(fields)} fields", pattern.span
                )
                return
            env = dict(zip(info.type_params, ty.args, strict=False))
            for sub_pattern, (_name, field_ty) in zip(sub, fields, strict=False):
                self._check_pattern(sub_pattern, substitute(field_ty, env))

    def _exhaustiveness(self, stmt: MatchStmt, ty: Type) -> None:
        if ty.name == "<error>":
            return
        covered_all = False
        covered: set[str] = set()
        info = self._choice_for_type(ty)
        for index, arm in enumerate(stmt.arms):
            if arm.guard is not None:
                continue
            kind = self._cover_kind(arm.pattern, ty)
            if kind == "all":
                if covered_all:
                    self._error("W3031", "this match arm is unreachable", arm.pattern.span)
                covered_all = True
            elif kind.startswith("case:"):
                case = kind.split(":", 1)[1]
                if case in covered:
                    self._error("W3031", "this match arm is unreachable", arm.pattern.span)
                covered.add(case)
            elif covered_all:
                self._error("W3031", "this match arm is unreachable", arm.pattern.span)
            _ = index
        if covered_all:
            return
        if ty.name == "Bool" and {"true", "false"} <= covered:
            return
        if info is not None:
            missing = [case for case in info.cases if case not in covered]
            if missing:
                self._error(
                    "E3030",
                    f"match on {ty.name} is not exhaustive",
                    stmt.span,
                    fix="add the missing cases, or `case _ then`",
                    extra=f"missing cases: {', '.join(missing)}",
                )
            return
        if ty.name == "Bool":
            self._error(
                "E3030", "match on Bool is not exhaustive", stmt.span, fix="add `case _ then`"
            )
            return
        self._error(
            "E3030",
            f"match on {ty.display()} is not exhaustive",
            stmt.span,
            fix="add `case _ then`",
        )

    def _cover_kind(self, pattern: object, ty: Type) -> str:
        if isinstance(pattern, (WildPat, BindPat)):
            return "all"
        if isinstance(pattern, LitPat) and ty.name == "Bool":
            return "case:true" if pattern.value is True else "case:false"
        if isinstance(pattern, CtorPat):
            info = self._choice_for_type(ty)
            if info is None or pattern.name not in info.cases:
                return "none"
            fields = info.cases[pattern.name]
            sub = pattern.fields or []
            if len(sub) != len(fields):
                return "none"
            env = dict(zip(info.type_params, ty.args, strict=False))
            for sub_pattern, (_name, field_ty) in zip(sub, fields, strict=False):
                if self._cover_kind(sub_pattern, substitute(field_ty, env)) != "all":
                    return "none"
            return f"case:{pattern.name}"
        return "none"

    def _choice_for_type(self, ty: Type) -> ChoiceInfo | None:
        if ty.name in self.choices:
            return self.choices[ty.name]
        builtin = _builtin_choice(ty.name)
        if builtin is None:
            return None
        return builtin

    def _iter_element(self, ty: Type, span: Span) -> Type:
        if ty.name in {"List", "Set", "MutableList"} and ty.args:
            return ty.args[0]
        if ty.name != "<error>":
            self._error(
                "E3000",
                "`for` iterates a List, Set, or MutableList",
                span,
                fix="use keys() or entries() for a map",
            )
        return POISON

    def _user_method(self, recv_ty: Type, name: str) -> FunctionDecl | None:
        for decl in self.functions:
            if decl.sig.name != name or not decl.sig.params:
                continue
            env = {param.name: var(param.name) for param in decl.sig.type_params}
            first = self._resolve_type(decl.sig.params[0].ty, env)
            trial: dict[str, Type] = {}
            if unify(first, recv_ty, trial):
                return decl
        return None

    def _maybe_warn_at(self, expr: FieldExpr, args: Sequence[Arg], span: Span) -> None:
        if (
            isinstance(expr.recv, NameExpr)
            and len(args) == 1
            and args[0].name is None
            and isinstance(args[0].expr, NameExpr)
            and (expr.recv.name, args[0].expr.name) in self._bounds_ok
        ):
            return
        self._error(
            "W3050",
            "`at` can trap when the index is out of range",
            span,
            fix="use `get`, which returns Option",
        )

    def _proven_indexes(self, expr: Expr) -> set[tuple[str, str]]:
        """Names proved in range by a dominating `if` condition.

        Both `index >= 0` (also `index > 0` or `0 <= index`) and
        `index < receiver.length()` must be present. The receiver and the
        index must be names. A literal index is not suppressed.
        """
        nonneg: set[str] = set()
        below: dict[str, set[str]] = {}

        def walk(node: Expr) -> None:
            if isinstance(node, GroupExpr):
                walk(node.expr)
                return
            if isinstance(node, BinaryExpr) and node.op == "and":
                walk(node.left)
                walk(node.right)
                return
            if (
                isinstance(node, BinaryExpr)
                and node.op in {">=", ">"}
                and isinstance(node.left, NameExpr)
                and _is_zero(node.right)
            ):
                nonneg.add(node.left.name)
                return
            if (
                isinstance(node, BinaryExpr)
                and node.op == "<="
                and _is_zero(node.left)
                and isinstance(node.right, NameExpr)
            ):
                nonneg.add(node.right.name)
                return
            if isinstance(node, BinaryExpr) and node.op == "<":
                receiver = _length_receiver(node.right)
                if isinstance(node.left, NameExpr) and receiver is not None:
                    below.setdefault(node.left.name, set()).add(receiver)
                return
            if isinstance(node, BinaryExpr) and node.op == ">":
                receiver = _length_receiver(node.left)
                if receiver is not None and isinstance(node.right, NameExpr):
                    below.setdefault(node.right.name, set()).add(receiver)

        walk(expr)
        proven: set[tuple[str, str]] = set()
        for index in nonneg:
            for receiver in below.get(index, ()):
                proven.add((receiver, index))
        return proven

    def _check_contract(self, kind: str, expr: Expr, scope: Scope, ret: Type) -> None:
        previous = self.scope
        previous_flag = self.in_ensures
        previous_ret = self.fn_ret
        self.scope = scope
        self.in_ensures = kind == "ensures"
        self.fn_ret = ret
        got = self.check_expr(expr, BOOL)
        if got.name not in {"Bool", "<error>"}:
            self._error("E3022", "a contract must be Bool", expr.span)
        self._reject_effects_in(expr, expr.span)
        self.scope = previous
        self.in_ensures = previous_flag
        self.fn_ret = previous_ret

    def _reject_effects_in(self, expr: Expr, span: Span) -> None:
        if isinstance(expr, CallExpr) and isinstance(expr.func, NameExpr):
            binding = self.scope.lookup(expr.func.name)
            if binding is not None and binding.effects:
                self._error("E5002", "a contract cannot perform effects", span)

    def _require_effects(self, effects: frozenset[str], span: Span, name: str) -> None:
        if self.in_test:
            return
        missing = effects - self.fn_effects
        if missing and self._inside_lambda:
            self._error("E4002", "a lambda cannot perform effects", span)
            return
        for effect in sorted(missing):
            self._error(
                "E4001",
                f"`{name}` uses {effect}, which is not declared",
                span,
                fix=f"add `uses {effect}`",
            )

    def _assignable(
        self,
        expected: Type,
        got: Type,
        span: Span,
        literal: Expr | None = None,
        *,
        code: str = "E3000",
    ) -> None:
        if expected.name == "<error>" or got.name == "<error>":
            return
        if literal is not None and _is_int_literal(literal) and expected.name == "Int64":
            self._error(
                "E3023", "integer literals are always Int", span, fix="convert with Int64.from_int"
            )
            return
        if not types_equal(expected, got):
            if {expected.name, got.name} <= {"Int", "Int64"} and expected.name != got.name:
                self._error("E3024", f"expected {expected.display()}, found {got.display()}", span)
            else:
                self._error(code, f"expected {expected.display()}, found {got.display()}", span)

    def _resolve_type(self, expr: TypeExpr, env: dict[str, Type] | None = None) -> Type:
        env = env or {}
        if expr.kind == "function":
            params = tuple(self._resolve_type(param, env) for param in expr.params)
            ret = UNIT if expr.ret is None else self._resolve_type(expr.ret, env)
            return fn_type(params, ret)
        if expr.name in env:
            return env[expr.name]
        if expr.path:
            qualifier = ".".join(expr.path)
            namespace = self.scope.lookup(expr.path[0] if len(expr.path) == 1 else "")
            key = qualifier
            if (
                namespace is not None
                and namespace.kind == "namespace"
                and isinstance(namespace.payload, str)
            ):
                key = namespace.payload
            members = self._namespaces.get(key, {})
            member = members.get(expr.name)
            if (
                member is None
                and expr.name not in self.records
                and expr.name not in self.choices
                and self.scope.lookup(expr.name) is None
            ):
                self._error("E3008", f"unknown type `{expr.name}`", expr.span)
                return POISON
        known = (
            expr.name
            in {
                "Int",
                "Int64",
                "Float",
                "Bool",
                "Text",
                "Bytes",
                "Unit",
                "List",
                "Map",
                "Set",
                "Option",
                "Result",
                "Ordering",
                "MutableList",
                "MutableMap",
                "Entry",
                "File",
                "FileError",
                "Utf8Error",
                "Json",
                "JsonError",
                "PythonError",
            }
            or expr.name in self.records
            or expr.name in self.choices
            or expr.name in env
        )
        if not known and self.scope.lookup(expr.name) is None:
            self._error("E3008", f"unknown type `{expr.name}`", expr.span)
            return POISON
        args = tuple(self._resolve_type(arg, env) for arg in expr.args)
        expected_arity = {
            "List": 1,
            "Set": 1,
            "Option": 1,
            "MutableList": 1,
            "Map": 2,
            "Result": 2,
            "MutableMap": 2,
            "Entry": 2,
        }.get(
            expr.name,
            len(self.records[expr.name].type_params)
            if expr.name in self.records
            else len(self.choices[expr.name].type_params)
            if expr.name in self.choices
            else 0,
        )
        if expected_arity and len(args) != expected_arity:
            self._error(
                "E3007", f"`{expr.name}` expects {expected_arity} type arguments", expr.span
            )
        resolved = t(expr.name, *args)
        self._require_hashable_key(resolved, expr.span)
        self._require_type_constraints(resolved, expr.span, type_vars=False)
        return resolved

    def _require_type_constraints(self, ty: Type, span: Span, *, type_vars: bool) -> None:
        """Type arguments of a record or choice must meet its parameters' constraints.

        A written type checks concrete arguments only, like a `Set` element: a
        signature is resolved before its own constraints are in scope. A
        construction also checks type variables against the enclosing constraints.
        """
        for (_param, names), arg in zip(
            self.type_constraints.get(ty.name, ()), ty.args, strict=False
        ):
            if _has_error(arg) or (_has_var(arg) and not type_vars):
                continue
            for iface in sorted(names):
                known = iface in BUILTIN_INTERFACES or iface in self.interfaces
                if not known or (span, iface) in self._constraint_reported:
                    continue
                if not self._implements(arg, iface):
                    self._constraint_reported.add((span, iface))
                    self._require_constraint(arg, iface, span)

    def _require_hashable_key(self, ty: Type, span: Span) -> None:
        if ty.name not in {"Set", "Map", "MutableMap"} or not ty.args:
            return
        key = ty.args[0]
        if key.name == "<error>" or _has_var(key) or self._hashable(key):
            return
        if span in self._unhashable_reported:
            return
        self._unhashable_reported.add(span)
        role = "a set element" if ty.name == "Set" else "a map key"
        self._error("E3042", f"`{key.display()}` cannot be {role}", span)

    def _function_type(self, decl: FunctionDecl) -> Type:
        env = {param.name: var(param.name) for param in decl.sig.type_params}
        params = tuple(self._resolve_type(param.ty, env) for param in decl.sig.params)
        ret = self._resolve_type(decl.sig.ret, env)
        return fn_type(params, ret)

    def _builtin_fn_type(self, builtin: Builtin) -> Type:
        return fn_type(tuple(ty for _name, ty in builtin.params), builtin.ret)

    def _define_top(self, name: str, binding: Binding) -> None:
        if name in self.scope.names:
            self._error(
                "E2021",
                f"`{name}` is already defined in this module",
                binding.span or self.module.span,
            )
            return
        self.scope.names[name] = binding

    def _define(self, scope: Scope, name: str, binding: Binding) -> None:
        existing = scope.lookup(name)
        if existing is not None:
            self._error(
                "E2020",
                f"`{name}` is already defined",
                binding.span or self.module.span,
                fix="choose a new name",
            )
            return
        scope.names[name] = binding

    def _note_ambiguous(self, name: str, span: Span) -> None:
        self._error(
            "E2022",
            f"`{name}` names more than one case",
            span,
            fix="qualify the case with its choice name",
        )
        self.scope.names[name] = Binding(name, "ambiguous", POISON, span=span)

    def _check_signature_effects(self, effects: list[tuple[str, Span]]) -> None:
        for name, span in effects:
            if name not in EFFECTS:
                self._error("E4003", f"unknown effect `{name}`", span)

    def _equatable(self, ty: Type) -> bool:
        if ty.is_var:
            return bool({"Equatable", "Hashable"} & self.constraints.get(ty.name, frozenset()))
        if ty.name in {"Int", "Int64", "Float", "Bool", "Text", "Bytes", "Unit", "Ordering"}:
            return True
        if ty.name in {"List", "Set", "Option"} and ty.args:
            return self._equatable(ty.args[0])
        if ty.name in {"Map", "Result", "Entry"} and len(ty.args) == 2:
            return self._equatable(ty.args[0]) and self._equatable(ty.args[1])
        info = self.records.get(ty.name)
        if info is not None:
            env = dict(zip(info.type_params, ty.args, strict=False))
            return all(
                self._equatable(substitute(field_ty, env)) for _name, field_ty in info.fields
            )
        choice = self.choices.get(ty.name)
        if choice is not None:
            env = dict(zip(choice.type_params, ty.args, strict=False))
            return all(
                self._equatable(substitute(field_ty, env))
                for fields in choice.cases.values()
                for _name, field_ty in fields
            )
        return ty.name in {"FileError", "Utf8Error", "Json", "JsonError"}

    def _showable(self, ty: Type, seen: frozenset[str] | None = None) -> bool:
        """True when every part of the type can be shown."""
        if ty.name == "<error>":
            return True
        if ty.is_var:
            return "Showable" in self.constraints.get(ty.name, frozenset())
        if ty.name == "function" or ty.ret is not None:
            return False
        if is_resource(ty) or contains_mutable(ty):
            return False
        if ty.name in {"Int", "Int64", "Float", "Bool", "Text", "Bytes", "Unit", "Ordering"}:
            return True
        visiting = frozenset() if seen is None else seen
        key = ty.display()
        if key in visiting:
            return True
        visiting = visiting | {key}
        if ty.name in {"List", "Set", "Option"} and len(ty.args) == 1:
            return self._showable(ty.args[0], visiting)
        if ty.name in {"Map", "Result", "Entry"} and len(ty.args) == 2:
            return self._showable(ty.args[0], visiting) and self._showable(ty.args[1], visiting)
        info = self.records.get(ty.name)
        if info is not None:
            env = dict(zip(info.type_params, ty.args, strict=False))
            return all(
                self._showable(substitute(field_ty, env), visiting)
                for _name, field_ty in info.fields
            )
        choice = self.choices.get(ty.name) or _builtin_choice(ty.name)
        if choice is not None:
            env = dict(zip(choice.type_params, ty.args, strict=False))
            return all(
                self._showable(substitute(field_ty, env), visiting)
                for fields in choice.cases.values()
                for _name, field_ty in fields
            )
        return False

    def _hashable(self, ty: Type) -> bool:
        if ty.is_var:
            return "Hashable" in self.constraints.get(ty.name, frozenset())
        if ty.name == "Float" or contains_float(ty):
            return False
        if ty.name in {"function"} or is_resource(ty) or contains_mutable(ty):
            return False
        if ty.name in {"Int", "Int64", "Bool", "Text", "Bytes", "Unit", "Ordering"}:
            return True
        if not self._equatable(ty):
            return False
        return ty.name != "Float"

    def _generatable(self, ty: Type) -> bool:
        if contains_mutable(ty) or is_resource(ty) or ty.name == "function":
            return False
        return True

    def _check_args_against(
        self, params: tuple[Type, ...], args: Sequence[Arg], span: Span
    ) -> None:
        from tersalang.ast import Arg

        typed = [arg for arg in args if isinstance(arg, Arg)]
        if len(typed) != len(params):
            self._error("E3003", "wrong number of arguments", span)
            return
        for param, arg in zip(params, typed, strict=False):
            got = self.check_expr(arg.expr, param)
            self._assignable(param, got, arg.span, literal=arg.expr)

    def _error(
        self,
        code: str,
        message: str,
        span: Span,
        *,
        fix: str | None = None,
        extra: str | None = None,
    ) -> None:
        related = []
        if extra:
            from tersalang.diagnostics import Related

            related.append(Related(extra, span.file, span))
        self.diagnostics.append(
            Diagnostic(
                code=code,
                message=message,
                file=span.file,
                span=span,
                related=related,
                fix=None if fix is None else Fix(fix),
            )
        )


def opt_unknown() -> Type:
    """`Option[<error>]`, for a `None` whose element type is unknown."""
    return t("Option", POISON)


def _context(other: Type) -> Type | None:
    return None if _has_error(other) else other


def _has_error(ty: Type) -> bool:
    return ty.name == "<error>" or any(_has_error(arg) for arg in ty.args)


def _is_int_literal(expr: Expr) -> bool:
    if isinstance(expr, LiteralExpr):
        return expr.kind == "int"
    if isinstance(expr, UnaryExpr) and expr.op == "-":
        return isinstance(expr.expr, LiteralExpr) and expr.expr.kind == "int"
    if isinstance(expr, GroupExpr):
        return _is_int_literal(expr.expr)
    return False


def _const_refs(expr: Expr) -> set[str]:
    found: set[str] = set()
    if isinstance(expr, NameExpr):
        found.add(expr.name)
    elif isinstance(expr, UnaryExpr):
        found |= _const_refs(expr.expr)
    elif isinstance(expr, BinaryExpr):
        found |= _const_refs(expr.left) | _const_refs(expr.right)
    elif isinstance(expr, CallExpr):
        if not isinstance(expr.func, NameExpr):
            found |= (
                _const_refs(expr.func)
                if isinstance(expr.func, (FieldExpr, CallExpr, UnaryExpr, BinaryExpr))
                else set()
            )
        for arg in expr.args:
            found |= _const_refs(arg.expr)
    elif isinstance(expr, ListExpr):
        for element in expr.elements:
            found |= _const_refs(element)
    return found


def _impl_owner(decl: ImplementsDecl) -> str:
    """The type an `implements` block is for, or "" when the interface takes none."""
    return decl.interface.args[0].name if decl.interface.args else ""


def _python_target(target: str) -> bool:
    if not target.startswith("python:"):
        return False
    parts = target[len("python:") :].split(".")
    if len(parts) < 2:
        return False
    return all(part.isascii() and part.isidentifier() for part in parts)


def _has_var(ty: Type) -> bool:
    if ty.is_var:
        return True
    if ty.ret is not None and _has_var(ty.ret):
        return True
    return any(_has_var(item) for item in (*ty.args, *ty.params))


def _is_python_result(ty: Type) -> bool:
    return ty.name == "Result" and len(ty.args) == 2 and ty.args[1].name == "PythonError"


def _builtin_choice(name: str) -> ChoiceInfo | None:
    table: dict[str, tuple[tuple[str, ...], dict[str, tuple[tuple[str, Type], ...]]]] = {
        "Option": (("T",), {"Some": (("value", var("T")),), "None": ()}),
        "Result": (("T", "E"), {"Ok": (("value", var("T")),), "Error": (("error", var("E")),)}),
        "Ordering": ((), {"Less": (), "Equal": (), "Greater": ()}),
        "FileError": (
            (),
            {
                "NotFound": (("path", TEXT),),
                "Denied": (("path", TEXT),),
                "Io": (("message", TEXT),),
            },
        ),
        "Utf8Error": ((), {"Invalid": (("index", INT),)}),
        "JsonError": ((), {"Invalid": (("index", INT), ("message", TEXT))}),
        "Json": (
            (),
            {
                "Null": (),
                "Bool": (("value", BOOL),),
                "Number": (("literal", TEXT),),
                "String": (("value", TEXT),),
                "Array": (("items", lst(t("Json"))),),
                "Object": (("entries", mp(TEXT, t("Json"))),),
            },
        ),
    }
    if name not in table:
        return None
    params, cases = table[name]
    return ChoiceInfo(name, params, cases, Span("", 0, 0, 1, 1, 1, 1), "std")


def _fake_call(span: Span, args: Sequence[Arg]) -> CallExpr:
    return CallExpr(span, NameExpr(span, ""), list(args))


def _is_zero(expr: Expr) -> bool:
    return isinstance(expr, LiteralExpr) and expr.kind == "int" and expr.value == 0


def _length_receiver(expr: Expr) -> str | None:
    if not isinstance(expr, CallExpr) or not isinstance(expr.func, FieldExpr):
        return None
    if expr.func.name != "length" or expr.args:
        return None
    if isinstance(expr.func.recv, NameExpr):
        return expr.func.recv.name
    return None


def check_module(module: Module, *, mode: str = "dev") -> list[Diagnostic]:
    """Every diagnostic from checking `module` in `mode` (see `Checker`)."""
    return Checker(module, mode=mode).check()
