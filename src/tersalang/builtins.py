# SPDX-License-Identifier: Apache-2.0
"""Standard-library signatures. Behavior lives in the evaluator."""

from __future__ import annotations

from dataclasses import dataclass

from tersalang.typesys import (
    BOOL,
    BYTES,
    FLOAT,
    INT,
    INT64,
    ORDERING,
    TEXT,
    UNIT,
    Type,
    fn_type,
    lst,
    mp,
    opt,
    res,
    t,
    var,
)

T = var("T")
U = var("U")
E = var("E")
F = var("F")
K = var("K")
V = var("V")
ACC = var("Acc")
R = var("R")


@dataclass(frozen=True)
class Builtin:
    """One standard-library signature.

    `id` is unique, e.g. `list.map`; `name` is the source spelling. `method_of` and
    `static_of` name the type it is called on as `value.name` or `Type.name`. `module` is
    the `std` module that exports it. An `rl_forbidden` builtin is rejected in RL mode
    (`E4011`).
    """

    id: str
    name: str
    type_params: tuple[str, ...]
    params: tuple[tuple[str, Type], ...]
    ret: Type
    effects: frozenset[str] = frozenset()
    method_of: str | None = None
    static_of: str | None = None
    module: str = "std.core"
    rl_forbidden: bool = False


def _b(
    ident: str,
    name: str,
    params: list[tuple[str, Type]],
    ret: Type,
    *,
    type_params: tuple[str, ...] = (),
    effects: frozenset[str] = frozenset(),
    method_of: str | None = None,
    static_of: str | None = None,
    module: str = "std.core",
    rl_forbidden: bool = False,
) -> Builtin:
    return Builtin(
        ident,
        name,
        type_params,
        tuple(params),
        ret,
        effects,
        method_of,
        static_of,
        module,
        rl_forbidden,
    )


def _methods(
    module: str,
    type_name: str,
    rows: list[tuple[str, list[tuple[str, Type]], Type, tuple[str, ...]]],
) -> list[Builtin]:
    built: list[Builtin] = []
    for name, params, ret, tparams in rows:
        built.append(
            _b(
                f"{module}.{type_name}.{name}",
                name,
                params,
                ret,
                type_params=tparams,
                method_of=type_name,
                static_of=type_name,
                module=module,
            )
        )
    return built


_LIST_SELF = lst(T)
_MAP_SELF = mp(K, V)
_SET_SELF = t("Set", T)
_ML_SELF = t("MutableList", T)
_MM_SELF = t("MutableMap", K, V)

BUILTINS: tuple[Builtin, ...] = (
    _b("show", "show", [("value", T)], TEXT, type_params=("T",), module="std.core"),
    _b("int.parse", "parse", [("text", TEXT)], opt(INT), static_of="Int", module="std.core"),
    _b(
        "int.compare",
        "compare",
        [("a", INT), ("b", INT)],
        ORDERING,
        static_of="Int",
        module="std.core",
    ),
    _b(
        "int.from_float",
        "from_float",
        [("value", FLOAT)],
        opt(INT),
        static_of="Int",
        module="std.core",
    ),
    _b(
        "int64.from_int",
        "from_int",
        [("value", INT)],
        opt(INT64),
        static_of="Int64",
        module="std.core",
    ),
    _b("int64.to_int", "to_int", [("value", INT64)], INT, static_of="Int64", module="std.core"),
    _b(
        "int64.checked_add",
        "checked_add",
        [("a", INT64), ("b", INT64)],
        opt(INT64),
        static_of="Int64",
    ),
    _b(
        "int64.checked_sub",
        "checked_sub",
        [("a", INT64), ("b", INT64)],
        opt(INT64),
        static_of="Int64",
    ),
    _b(
        "int64.checked_mul",
        "checked_mul",
        [("a", INT64), ("b", INT64)],
        opt(INT64),
        static_of="Int64",
    ),
    _b("float.from_int", "from_int", [("value", INT)], FLOAT, static_of="Float"),
    _b("float.sqrt", "sqrt", [("value", FLOAT)], FLOAT, static_of="Float"),
    _b("float.fma", "fma", [("x", FLOAT), ("y", FLOAT), ("z", FLOAT)], FLOAT, static_of="Float"),
    _b(
        "float.total_compare",
        "total_compare",
        [("a", FLOAT), ("b", FLOAT)],
        ORDERING,
        static_of="Float",
    ),
    _b("float.same", "same", [("a", FLOAT), ("b", FLOAT)], BOOL, static_of="Float"),
    _b("float.round", "round", [("value", FLOAT)], opt(INT), static_of="Float"),
    _b("float.floor", "floor", [("value", FLOAT)], opt(INT), static_of="Float"),
    _b("float.ceil", "ceil", [("value", FLOAT)], opt(INT), static_of="Float"),
    _b("list.empty", "empty", [], lst(T), type_params=("T",), static_of="List", module="std.list"),
    _b(
        "list.range",
        "range",
        [("start", INT), ("end", INT)],
        lst(INT),
        static_of="List",
        module="std.list",
    ),
    *_methods(
        "std.list",
        "List",
        [
            ("get", [("xs", _LIST_SELF), ("index", INT)], opt(T), ("T",)),
            ("at", [("xs", _LIST_SELF), ("index", INT)], T, ("T",)),
            ("with_appended", [("xs", _LIST_SELF), ("item", T)], _LIST_SELF, ("T",)),
            ("with_item", [("xs", _LIST_SELF), ("index", INT), ("item", T)], _LIST_SELF, ("T",)),
            ("length", [("xs", _LIST_SELF)], INT, ("T",)),
            ("is_empty", [("xs", _LIST_SELF)], BOOL, ("T",)),
            ("contains", [("xs", _LIST_SELF), ("item", T)], BOOL, ("T",)),
            ("map", [("xs", _LIST_SELF), ("fn", fn_type((T,), U))], lst(U), ("T", "U")),
            ("filter", [("xs", _LIST_SELF), ("fn", fn_type((T,), BOOL))], _LIST_SELF, ("T",)),
            (
                "fold",
                [("xs", _LIST_SELF), ("init", ACC), ("fn", fn_type((ACC, T), ACC))],
                ACC,
                ("T", "Acc"),
            ),
            (
                "zip_with",
                [("xs", _LIST_SELF), ("ys", lst(U)), ("fn", fn_type((T, U), R))],
                lst(R),
                ("T", "U", "R"),
            ),
        ],
    ),
    _b(
        "list.sort",
        "sort",
        [("xs", _LIST_SELF), ("compare", fn_type((T, T), ORDERING))],
        _LIST_SELF,
        type_params=("T",),
        method_of="List",
        static_of="List",
        module="std.list",
    ),
    _b(
        "map.empty",
        "empty",
        [],
        _MAP_SELF,
        type_params=("K", "V"),
        static_of="Map",
        module="std.map",
    ),
    *_methods(
        "std.map",
        "Map",
        [
            ("get", [("m", _MAP_SELF), ("key", K)], opt(V), ("K", "V")),
            ("with_entry", [("m", _MAP_SELF), ("key", K), ("value", V)], _MAP_SELF, ("K", "V")),
            ("without_key", [("m", _MAP_SELF), ("key", K)], _MAP_SELF, ("K", "V")),
            ("contains_key", [("m", _MAP_SELF), ("key", K)], BOOL, ("K", "V")),
            ("keys", [("m", _MAP_SELF)], lst(K), ("K", "V")),
            ("entries", [("m", _MAP_SELF)], lst(t("Entry", K, V)), ("K", "V")),
            ("length", [("m", _MAP_SELF)], INT, ("K", "V")),
            ("is_empty", [("m", _MAP_SELF)], BOOL, ("K", "V")),
        ],
    ),
    _b("set.empty", "empty", [], _SET_SELF, type_params=("T",), static_of="Set", module="std.set"),
    _b(
        "set.from_list",
        "from_list",
        [("items", lst(T))],
        _SET_SELF,
        type_params=("T",),
        static_of="Set",
        module="std.set",
    ),
    *_methods(
        "std.set",
        "Set",
        [
            ("contains", [("s", _SET_SELF), ("item", T)], BOOL, ("T",)),
            ("with_element", [("s", _SET_SELF), ("item", T)], _SET_SELF, ("T",)),
            ("without_element", [("s", _SET_SELF), ("item", T)], _SET_SELF, ("T",)),
            ("length", [("s", _SET_SELF)], INT, ("T",)),
            ("is_empty", [("s", _SET_SELF)], BOOL, ("T",)),
        ],
    ),
    _b(
        "mlist.new",
        "new",
        [],
        _ML_SELF,
        type_params=("T",),
        static_of="MutableList",
        module="std.mutable",
    ),
    *_methods(
        "std.mutable",
        "MutableList",
        [
            ("push", [("xs", _ML_SELF), ("item", T)], UNIT, ("T",)),
            ("get", [("xs", _ML_SELF), ("index", INT)], opt(T), ("T",)),
            ("set_at", [("xs", _ML_SELF), ("index", INT), ("item", T)], UNIT, ("T",)),
            ("length", [("xs", _ML_SELF)], INT, ("T",)),
            ("freeze", [("xs", _ML_SELF)], lst(T), ("T",)),
        ],
    ),
    _b(
        "mmap.new",
        "new",
        [],
        _MM_SELF,
        type_params=("K", "V"),
        static_of="MutableMap",
        module="std.mutable",
    ),
    *_methods(
        "std.mutable",
        "MutableMap",
        [
            ("insert", [("m", _MM_SELF), ("key", K), ("value", V)], UNIT, ("K", "V")),
            ("remove", [("m", _MM_SELF), ("key", K)], UNIT, ("K", "V")),
            ("get", [("m", _MM_SELF), ("key", K)], opt(V), ("K", "V")),
            ("keys", [("m", _MM_SELF)], lst(K), ("K", "V")),
            ("entries", [("m", _MM_SELF)], lst(t("Entry", K, V)), ("K", "V")),
            ("length", [("m", _MM_SELF)], INT, ("K", "V")),
            ("freeze", [("m", _MM_SELF)], _MAP_SELF, ("K", "V")),
        ],
    ),
    *_methods(
        "std.text",
        "Text",
        [
            ("concat", [("left", TEXT), ("right", TEXT)], TEXT, ()),
            ("split", [("text", TEXT), ("separator", TEXT)], lst(TEXT), ()),
            ("trim", [("text", TEXT)], TEXT, ()),
            ("find", [("text", TEXT), ("needle", TEXT)], opt(INT), ()),
            ("replace", [("text", TEXT), ("old", TEXT), ("new", TEXT)], TEXT, ()),
            ("slice", [("text", TEXT), ("start", INT), ("end", INT)], TEXT, ()),
            ("try_slice", [("text", TEXT), ("start", INT), ("end", INT)], opt(TEXT), ()),
            ("code_points", [("text", TEXT)], lst(INT), ()),
            ("code_point_count", [("text", TEXT)], INT, ()),
            ("byte_length", [("text", TEXT)], INT, ()),
            ("graphemes", [("text", TEXT)], lst(TEXT), ()),
            ("to_upper", [("text", TEXT)], TEXT, ()),
            ("to_lower", [("text", TEXT)], TEXT, ()),
            ("normalize_nfc", [("text", TEXT)], TEXT, ()),
            ("normalize_nfd", [("text", TEXT)], TEXT, ()),
            ("is_empty", [("text", TEXT)], BOOL, ()),
        ],
    ),
    _b(
        "text.join",
        "join",
        [("parts", lst(TEXT)), ("separator", TEXT)],
        TEXT,
        static_of="Text",
        module="std.text",
    ),
    _b(
        "text.join_lines",
        "join_lines",
        [("parts", lst(TEXT))],
        TEXT,
        static_of="Text",
        module="std.text",
    ),
    _b(
        "text.from_utf8",
        "from_utf8",
        [("bytes", BYTES)],
        res(TEXT, t("Utf8Error")),
        static_of="Text",
        module="std.text",
    ),
    _b(
        "bytes.from_hex",
        "from_hex",
        [("text", TEXT)],
        opt(BYTES),
        static_of="Bytes",
        module="std.core",
    ),
    _b("bytes.of_hex", "of_hex", [("text", TEXT)], BYTES, static_of="Bytes", module="std.core"),
    _b(
        "bytes.from_list",
        "from_list",
        [("items", lst(INT))],
        opt(BYTES),
        static_of="Bytes",
        module="std.core",
    ),
    _b(
        "bytes.of_list",
        "of_list",
        [("items", lst(INT))],
        BYTES,
        static_of="Bytes",
        module="std.core",
    ),
    _b(
        "bytes.get",
        "get",
        [("bytes", BYTES), ("index", INT)],
        opt(INT),
        method_of="Bytes",
        static_of="Bytes",
    ),
    _b("math.min", "min", [("a", T), ("b", T)], T, type_params=("T",), module="std.math"),
    _b("math.max", "max", [("a", T), ("b", T)], T, type_params=("T",), module="std.math"),
    _b("math.abs", "abs", [("value", T)], T, type_params=("T",), module="std.math"),
    _b(
        "math.clamp",
        "clamp",
        [("value", T), ("low", T), ("high", T)],
        T,
        type_params=("T",),
        module="std.math",
    ),
    _b("math.gcd", "gcd", [("a", INT), ("b", INT)], INT, module="std.math"),
    _b("math.pow", "pow", [("base", INT), ("exponent", INT)], INT, module="std.math"),
    _b("math.sqrt", "sqrt", [("value", FLOAT)], FLOAT, module="std.math"),
    _b(
        "console.print",
        "print",
        [("text", TEXT)],
        UNIT,
        effects=frozenset({"Console"}),
        module="std.console",
    ),
    _b(
        "console.print_error",
        "print_error",
        [("text", TEXT)],
        UNIT,
        effects=frozenset({"Console"}),
        module="std.console",
    ),
    _b(
        "console.read_line",
        "read_line",
        [],
        opt(TEXT),
        effects=frozenset({"Console"}),
        module="std.console",
    ),
    _b(
        "file.open",
        "open",
        [("path", TEXT)],
        res(t("File"), t("FileError")),
        effects=frozenset({"FileRead"}),
        static_of="File",
        module="std.file",
    ),
    _b(
        "file.read_text",
        "read_text",
        [("path", TEXT)],
        res(TEXT, t("FileError")),
        effects=frozenset({"FileRead"}),
        static_of="File",
        module="std.file",
    ),
    _b(
        "file.write_text",
        "write_text",
        [("path", TEXT), ("text", TEXT)],
        res(UNIT, t("FileError")),
        effects=frozenset({"FileWrite"}),
        static_of="File",
        module="std.file",
    ),
    _b(
        "file.list_dir",
        "list_dir",
        [("path", TEXT)],
        res(lst(TEXT), t("FileError")),
        effects=frozenset({"FileRead"}),
        static_of="File",
        module="std.file",
    ),
    _b(
        "file.read_line",
        "read_line",
        [("file", t("File"))],
        opt(TEXT),
        effects=frozenset({"FileRead"}),
        method_of="File",
        module="std.file",
    ),
    _b("clock.now", "now", [], INT, effects=frozenset({"Clock"}), module="std.clock"),
    _b("clock.monotonic", "monotonic", [], INT, effects=frozenset({"Clock"}), module="std.clock"),
    _b(
        "random.int",
        "int",
        [("low", INT), ("high", INT)],
        INT,
        effects=frozenset({"Random"}),
        static_of="Random",
        module="std.random",
    ),
    _b(
        "random.float",
        "float",
        [],
        FLOAT,
        effects=frozenset({"Random"}),
        static_of="Random",
        module="std.random",
    ),
    _b(
        "random.shuffle",
        "shuffle",
        [("items", lst(T))],
        lst(T),
        type_params=("T",),
        effects=frozenset({"Random"}),
        module="std.random",
    ),
    _b("env.args", "args", [], lst(TEXT), effects=frozenset({"Env"}), module="std.env"),
    _b("env.get", "get", [("name", TEXT)], opt(TEXT), effects=frozenset({"Env"}), module="std.env"),
    _b(
        "testing.approx",
        "approx",
        [("left", FLOAT), ("right", FLOAT), ("tolerance", FLOAT)],
        BOOL,
        module="std.testing",
    ),
    _b("json.parse", "parse", [("text", TEXT)], res(t("Json"), t("JsonError")), module="std.json"),
    _b("json.stringify", "stringify", [("value", t("Json"))], TEXT, module="std.json"),
    _b(
        "option.map",
        "map",
        [("self", opt(T)), ("fn", fn_type((T,), U))],
        opt(U),
        type_params=("T", "U"),
        method_of="Option",
    ),
    _b(
        "option.and_then",
        "and_then",
        [("self", opt(T)), ("fn", fn_type((T,), opt(U)))],
        opt(U),
        type_params=("T", "U"),
        method_of="Option",
    ),
    _b(
        "option.unwrap_or",
        "unwrap_or",
        [("self", opt(T)), ("default", T)],
        T,
        type_params=("T",),
        method_of="Option",
    ),
    _b(
        "option.expect_some",
        "expect_some",
        [("self", opt(T)), ("message", TEXT)],
        T,
        type_params=("T",),
        method_of="Option",
    ),
    _b(
        "result.map",
        "map",
        [("self", res(T, E)), ("fn", fn_type((T,), U))],
        res(U, E),
        type_params=("T", "E", "U"),
        method_of="Result",
    ),
    _b(
        "result.map_error",
        "map_error",
        [("self", res(T, E)), ("fn", fn_type((E,), F))],
        res(T, F),
        type_params=("T", "E", "F"),
        method_of="Result",
    ),
    _b(
        "result.and_then",
        "and_then",
        [("self", res(T, E)), ("fn", fn_type((T,), res(U, E)))],
        res(U, E),
        type_params=("T", "E", "U"),
        method_of="Result",
    ),
    _b(
        "result.unwrap_or",
        "unwrap_or",
        [("self", res(T, E)), ("default", T)],
        T,
        type_params=("T", "E"),
        method_of="Result",
    ),
)

for _name in (
    "sin",
    "cos",
    "tan",
    "asin",
    "acos",
    "atan",
    "exp",
    "log",
    "log2",
    "log10",
):
    BUILTINS = (
        *BUILTINS,
        _b(
            f"math.{_name}",
            _name,
            [("value", FLOAT)],
            FLOAT,
            module="std.math",
            rl_forbidden=True,
        ),
    )

BUILTINS = (
    *BUILTINS,
    _b(
        "math.atan2",
        "atan2",
        [("y", FLOAT), ("x", FLOAT)],
        FLOAT,
        module="std.math",
        rl_forbidden=True,
    ),
    _b(
        "math.float_pow",
        "float_pow",
        [("base", FLOAT), ("exponent", FLOAT)],
        FLOAT,
        module="std.math",
        rl_forbidden=True,
    ),
)

BY_ID: dict[str, Builtin] = {item.id: item for item in BUILTINS}


def module_members(module: str) -> dict[str, Builtin]:
    """The builtins `module` exports by name; a name shared by several of them is left out."""
    grouped: dict[str, list[Builtin]] = {}
    for item in BUILTINS:
        if item.module == module:
            grouped.setdefault(item.name, []).append(item)
    return {name: items[0] for name, items in grouped.items() if len(items) == 1}


def methods_of(type_name: str) -> dict[str, Builtin]:
    """The builtins callable as methods on `type_name` values, by name."""
    found: dict[str, Builtin] = {}
    for item in BUILTINS:
        if item.method_of == type_name:
            found[item.name] = item
    return found


def statics_of(type_name: str) -> dict[str, Builtin]:
    """The builtins callable as `type_name.name`, by name."""
    found: dict[str, Builtin] = {}
    for item in BUILTINS:
        if item.static_of == type_name:
            found[item.name] = item
    return found
