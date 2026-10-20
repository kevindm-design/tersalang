# Diagnostic codes

<!-- Generated from spec/diagnostics.yaml and conformance/ by scripts/gen_diagnostics_doc.py. Do not edit. -->

Schema `tersa.diagnostic/0.1`. 128 codes. The `docs_url` of every diagnostic points at its heading here.

A wrong example is a conformance program that produces the code (106 codes). A fixed example is that program after the edits in its `# fixed:` header lines (94 codes); `tests/test_conformance.py` checks that each one is clean. Codes with neither say why.

### E0001

Source is not valid UTF-8 or starts with a byte-order mark

Severity `error`, category `lexical`.

Wrong ([`conformance/lex/bom.tersa`](../conformance/lex/bom.tersa), `tersa check` reports it):

The program contains a byte-order mark, so it is not shown here. Open the file.

No fixed example: delete the byte-order mark before the first `#`.

### E0002

Non-ASCII character outside a text literal or comment

Severity `error`, category `lexical`.

Wrong ([`conformance/lex/non_ascii.tersa`](../conformance/lex/non_ascii.tersa), `tersa check` reports it):

```tersa
module non_ascii

function main() returns Unit
do
  let café = 1
  return
end
```

Fixed:

```tersa
module non_ascii

function main() returns Unit
do
  let cafe = 1
  return
end
```

### E0003

Tab character outside a text literal or comment

Severity `error`, category `lexical`.

Wrong ([`conformance/lex/tab_bad.tersa`](../conformance/lex/tab_bad.tersa), `tersa check` reports it):

The program contains a tab, so it is not shown here. Open the file.

No fixed example: replace the tab with a space.

### E0004

Lone carriage return

Severity `error`, category `lexical`.

Wrong ([`conformance/lex/lone_cr.tersa`](../conformance/lex/lone_cr.tersa), `tersa check` reports it):

The program contains a carriage return, so it is not shown here. Open the file.

No fixed example: end each line with LF or CRLF instead of a lone CR.

### E0010

Identifier is not lower_snake_case

Severity `error`, category `lexical`.

Wrong ([`conformance/lex/ident_lower.tersa`](../conformance/lex/ident_lower.tersa), `tersa check` reports it):

```tersa
module ident_lower

function main() returns Unit
do
  let bad_name_ = 1
  return
end
```

Fixed:

```tersa
module ident_lower

function main() returns Unit
do
  let bad_name = 1
  return
end
```

### E0011

Type name is not PascalCase

Severity `error`, category `lexical`.

Wrong ([`conformance/lex/ident_upper.tersa`](../conformance/lex/ident_upper.tersa), `tersa check` reports it):

```tersa
module ident_upper

record Bad_Name
  value: Int
end
```

Fixed:

```tersa
module ident_upper

record BadName
  value: Int
end
```

### E0012

Name is longer than 64 characters

Severity `error`, category `lexical`.

Wrong ([`conformance/lex/ident_long.tersa`](../conformance/lex/ident_long.tersa), `tersa check` reports it):

```tersa
module ident_long

function main() returns Unit
do
  let aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa = 1
  return
end
```

Fixed:

```tersa
module ident_long

function main() returns Unit
do
  let a = 1
  return
end
```

### E0020

Integer literal exceeds the lexical bit cap

Severity `error`, category `lexical`.

Wrong ([`conformance/lex/int_cap.tersa`](../conformance/lex/int_cap.tersa), `tersa check` reports it):

The program is 16584 bytes, so it is not shown here. Open the file.

No fixed example: use a literal under the 65,536-bit cap, or compute the value.

### E0021

Integer literal has a leading zero or a bad underscore

Severity `error`, category `lexical`.

Wrong ([`conformance/lex/leading_zero.tersa`](../conformance/lex/leading_zero.tersa), `tersa check` reports it):

```tersa
module leading_zero

function main() returns Unit
do
  let n = 01
  return
end
```

Fixed:

```tersa
module leading_zero

function main() returns Unit
do
  let n = 1
  return
end
```

### E0022

Float literal needs digits on both sides of the dot

Severity `error`, category `lexical`.

Wrong ([`conformance/lex/float_dot.tersa`](../conformance/lex/float_dot.tersa), `tersa check` reports it):

```tersa
module float_dot

function main() returns Unit
do
  let f = .5
  return
end
```

Fixed:

```tersa
module float_dot

function main() returns Unit
do
  let f = 0.5
  return
end
```

### E0023

Text literal contains a raw newline

Severity `error`, category `lexical`.

Wrong ([`conformance/lex/raw_newline.tersa`](../conformance/lex/raw_newline.tersa), `tersa check` reports it):

```tersa
module raw_newline

function main() returns Unit
do
  let t: Text = "a
b"
  return
end
```

Fixed:

```tersa
module raw_newline

function main() returns Unit
do
  let t: Text = "a\nb"
  return
end
```

### E0024

Text escape is not a Unicode scalar

Severity `error`, category `lexical`.

Wrong ([`conformance/lex/bad_unicode.tersa`](../conformance/lex/bad_unicode.tersa), `tersa check` reports it):

```tersa
module bad_unicode

function main() returns Unit
do
  let t: Text = "\u{D800}"
  return
end
```

Fixed:

```tersa
module bad_unicode

function main() returns Unit
do
  let t: Text = "\u{E9}"
  return
end
```

### E0025

Hex or binary literal is malformed

Severity `error`, category `lexical`.

No digits after 0x or 0b, or a digit outside that base. A leading zero or a bad underscore is E0021. A bad float shape is E0022.

Wrong ([`conformance/lex/bad_hex.tersa`](../conformance/lex/bad_hex.tersa), `tersa check` reports it):

```tersa
module bad_hex

function main() returns Unit
do
  let n = 0x
  return
end
```

Fixed:

```tersa
module bad_hex

function main() returns Unit
do
  let n = 0x1F
  return
end
```

### E0026

Unterminated text literal

Severity `error`, category `lexical`.

Wrong ([`conformance/lex/unterminated.tersa`](../conformance/lex/unterminated.tersa), `tersa check` reports it):

```tersa
module unterminated

function main() returns Unit
do
  let t: Text = "abc
```

Fixed:

```tersa
module unterminated

function main() returns Unit
do
  let t: Text = "abc"
  return
end
```

### E0027

Unknown text escape

Severity `error`, category `lexical`.

Wrong ([`conformance/lex/bad_escape.tersa`](../conformance/lex/bad_escape.tersa), `tersa check` reports it):

```tersa
module bad_escape

function main() returns Unit
do
  let t: Text = "\q"
  return
end
```

Fixed:

```tersa
module bad_escape

function main() returns Unit
do
  let t: Text = "\t"
  return
end
```

### E0030

This symbol is not an operator

Severity `error`, category `lexical`.

Wrong ([`conformance/lex/bad_symbol.tersa`](../conformance/lex/bad_symbol.tersa), `tersa check` reports it):

```tersa
module bad_symbol

function main() returns Unit
do
  let n = 1 % 2
  return
end
```

Fixed:

```tersa
module bad_symbol

function main() returns Unit
do
  let n = 1 mod 2
  return
end
```

### E1000

Syntax error

Severity `error`, category `syntax`.

The single general syntax-error code. The message names what was expected, for example "expected `do` on its own line". A reserved keyword where a name is required is also E1000: the lexer always emits a keyword as a keyword token, and the parser reports "expected a ... name, found the keyword `x` (keywords are reserved and cannot be names)".

Wrong ([`conformance/syntax/do_with_body.tersa`](../conformance/syntax/do_with_body.tersa), `tersa check` reports it):

```tersa
module do_with_body

function main() returns Unit
do return
end
```

Fixed:

```tersa
module do_with_body

function main() returns Unit
do
  return
end
```

### E1101

Only one with update is allowed

Severity `error`, category `syntax`.

Wrong ([`conformance/syntax/double_with.tersa`](../conformance/syntax/double_with.tersa), `tersa check` reports it):

```tersa
module double_with

record Box
  value: Int
end

function main() returns Box
do
  let box = Box(value = 1)
  return box with (value = 2) with (value = 3)
end
```

Fixed:

```tersa
module double_with

record Box
  value: Int
end

function main() returns Box
do
  let box = Box(value = 1)
  return (box with (value = 2)) with (value = 3)
end
```

### E1102

Comparison operators are not associative

Severity `error`, category `syntax`.

Wrong ([`conformance/syntax/chained_compare.tersa`](../conformance/syntax/chained_compare.tersa), `tersa check` reports it):

```tersa
module chained_compare

function main() returns Bool
do
  return 1 < 2 < 3
end
```

Fixed:

```tersa
module chained_compare

function main() returns Bool
do
  return 1 < 2 and 2 < 3
end
```

### E2000

Unknown name

Severity `error`, category `name`.

A value name that is not declared, imported, or in the prelude. An unknown type name is E3008. This single-file tool also uses E2000 for a user module it cannot load.

Wrong ([`conformance/names/e2000.tersa`](../conformance/names/e2000.tersa), `tersa check` reports it):

```tersa
module e2000

function main() returns Unit
do
  let _ = missing
  return
end
```

Fixed:

```tersa
module e2000

function main() returns Unit
do
  let _ = 1
  return
end
```

### E2001

Module name does not match the file name

Severity `error`, category `name`.

Wrong ([`conformance/names/e2001.tersa`](../conformance/names/e2001.tersa), `tersa check` reports it):

```tersa
module not_the_stem

function main() returns Unit
do
  return
end
```

Fixed:

```tersa
module e2001

function main() returns Unit
do
  return
end
```

### E2002

Import cycle

Severity `error`, category `name`.

Wrong ([`conformance/names/e2002.tersa`](../conformance/names/e2002.tersa), `tersa check` reports it):

```tersa
module e2002

import e2002

function main() returns Unit
do
  return
end
```

Fixed:

```tersa
module e2002

function main() returns Unit
do
  return
end
```

### E2003

Constant cycle

Severity `error`, category `name`.

Wrong ([`conformance/names/e2003.tersa`](../conformance/names/e2003.tersa), `tersa check` reports it):

```tersa
module e2003

let a: Int = b

let b: Int = a
```

Fixed:

```tersa
module e2003

let a: Int = b

let b: Int = 1
```

### E2004

Import qualifier clashes with another name

Severity `error`, category `name`.

Wrong ([`conformance/names/e2004.tersa`](../conformance/names/e2004.tersa), `tersa check` reports it):

```tersa
module e2004

import std.console as math
import std.math
```

Fixed:

```tersa
module e2004

import std.console as console
import std.math
```

### E2005

Unknown module member

Severity `error`, category `name`.

Wrong ([`conformance/names/e2005.tersa`](../conformance/names/e2005.tersa), `tersa check` reports it):

```tersa
module e2005

import std.math exposing nope

function main() returns Unit
do
  let _ = math.also_missing(1)
  return
end
```

Fixed:

```tersa
module e2005

import std.math

function main() returns Unit
do
  let _ = math.abs(1)
  return
end
```

### E2010

break and continue are only allowed inside a loop

Severity `error`, category `name`.

Wrong ([`conformance/names/e2010.tersa`](../conformance/names/e2010.tersa), `tersa check` reports it):

```tersa
module e2010

function main() returns Unit
do
  break
end
```

Fixed:

```tersa
module e2010

function main() returns Unit
do
  return
end
```

### E2011

expect is only allowed inside a test

Severity `error`, category `name`.

Wrong ([`conformance/names/e2011.tersa`](../conformance/names/e2011.tersa), `tersa check` reports it):

```tersa
module e2011

function main() returns Unit
do
  expect true
  return
end
```

Fixed:

```tersa
module e2011

function main() returns Unit
do
  return
end

test "truth"
do
  expect true
end
```

### E2020

Name is already defined in this scope

Severity `error`, category `name`.

Wrong ([`conformance/names/e2020.tersa`](../conformance/names/e2020.tersa), `tersa check` reports it):

```tersa
module e2020

function main() returns Unit
do
  let x = 1
  let x = 2
  return
end
```

Fixed:

```tersa
module e2020

function main() returns Unit
do
  let x = 1
  let y = 2
  return
end
```

### E2021

Duplicate name

Severity `error`, category `name`.

Two top-level declarations with the same name, or an import that exposes a name already in scope, including a prelude name.

Wrong ([`conformance/names/e2021.tersa`](../conformance/names/e2021.tersa), `tersa check` reports it):

```tersa
module e2021

function f() returns Unit
do
  return
end

function f() returns Unit
do
  return
end
```

Fixed:

```tersa
module e2021

function f() returns Unit
do
  return
end

function g() returns Unit
do
  return
end
```

### E2022

Ambiguous name

Severity `error`, category `name`.

Wrong ([`conformance/names/e2022.tersa`](../conformance/names/e2022.tersa), `tersa check` reports it):

```tersa
module e2022

choice Left
  case Overlap(value: Int)
end

choice Right
  case Overlap(value: Text)
end

function main() returns Unit
do
  let _ = Overlap(1)
  return
end
```

Fixed:

```tersa
module e2022

choice Left
  case Overlap(value: Int)
end

choice Right
  case Other(value: Text)
end

function main() returns Unit
do
  let _ = Overlap(1)
  return
end
```

### E2030

`set` target is not a `var`

Severity `error`, category `name`.

Wrong ([`conformance/names/e2030.tersa`](../conformance/names/e2030.tersa), `tersa check` reports it):

```tersa
module e2030

function main() returns Unit
do
  let x = 1
  set x = 2
  return
end
```

Fixed:

```tersa
module e2030

function main() returns Unit
do
  var x = 1
  set x = 2
  return
end
```

### E2101

Dependency content hash does not match tersa.lock

Severity `error`, category `name`.

Not implemented. Nothing reads tersa.lock.

No wrong or fixed example: no conformance program produces it.

### E3000

Type mismatch

Severity `error`, category `type`.

Fallback type error, used only when no more specific code applies.

Wrong ([`conformance/types/e3000.tersa`](../conformance/types/e3000.tersa), `tersa check` reports it):

```tersa
module e3000

function main() returns Unit
do
  let x: Int = true
  return
end
```

Fixed:

```tersa
module e3000

function main() returns Unit
do
  let x: Int = 1
  return
end
```

### E3002

A Result value is ignored

Severity `error`, category `type`.

Wrong ([`conformance/types/e3002.tersa`](../conformance/types/e3002.tersa), `tersa check` reports it):

```tersa
module e3002

function main() returns Unit
  uses FileRead
do
  File.read_text("a.txt")
  return
end
```

Fixed:

```tersa
module e3002

function main() returns Unit
  uses FileRead
do
  let _ = File.read_text("a.txt")
  return
end
```

### E3003

Wrong number of arguments

Severity `error`, category `type`.

A call, case constructor, or case pattern whose argument list has the wrong length. A case that has fields and is written with no argument list is E3006.

Wrong ([`conformance/types/e3003.tersa`](../conformance/types/e3003.tersa), `tersa check` reports it):

```tersa
module e3003

function f(a: Int) returns Int
do
  return a
end

function main() returns Int
do
  return f()
end
```

Fixed:

```tersa
module e3003

function f(a: Int) returns Int
do
  return a
end

function main() returns Int
do
  return f(1)
end
```

### E3004

Unknown field or method

Severity `error`, category `type`.

A field or method a non-record type does not have, or an unknown member of a type. An unknown record field is E3082. An unknown module member is E2005.

Wrong ([`conformance/types/e3004.tersa`](../conformance/types/e3004.tersa), `tersa check` reports it):

```tersa
module e3004

function main() returns Unit
do
  let xs = [1]
  let _ = xs.missing
  return
end
```

Fixed:

```tersa
module e3004

function main() returns Unit
do
  let xs = [1]
  let _ = xs.length()
  return
end
```

### E3005

Expression statement must be a function call

Severity `error`, category `type`.

Wrong ([`conformance/types/e3005.tersa`](../conformance/types/e3005.tersa), `tersa check` reports it):

```tersa
module e3005

function main() returns Unit
do
  1
  return
end
```

Fixed:

```tersa
module e3005

function main() returns Unit
do
  let _ = 1
  return
end
```

### E3006

Case constructor is missing its arguments

Severity `error`, category `type`.

A case that has fields, used as a bare name. The wrong number of arguments on a call or pattern is E3003.

Wrong ([`conformance/types/e3006.tersa`](../conformance/types/e3006.tersa), `tersa check` reports it):

```tersa
module e3006

function main() returns Unit
do
  let _ = Some
  return
end
```

Fixed:

```tersa
module e3006

function main() returns Unit
do
  let _ = Some(1)
  return
end
```

### E3007

Wrong number of type arguments

Severity `error`, category `type`.

Wrong ([`conformance/types/e3007.tersa`](../conformance/types/e3007.tersa), `tersa check` reports it):

```tersa
module e3007

function main() returns Unit
do
  let x: Option = None
  return
end
```

Fixed:

```tersa
module e3007

function main() returns Unit
do
  let x: Option[Int] = None
  return
end
```

### E3008

Unknown type

Severity `error`, category `type`.

A type name, or a record name in a construction. An unknown value name is E2000.

Wrong ([`conformance/types/e3008.tersa`](../conformance/types/e3008.tersa), `tersa check` reports it):

```tersa
module e3008

function main() returns Unit
do
  let x: MissingType = 1
  return
end
```

Fixed:

```tersa
module e3008

function main() returns Unit
do
  let x: Int = 1
  return
end
```

### E3010

Cannot infer this type

Severity `error`, category `type`.

Wrong ([`conformance/types/e3010.tersa`](../conformance/types/e3010.tersa), `tersa check` reports it):

```tersa
module e3010

function main() returns Unit
do
  let x = None
  return
end
```

Fixed:

```tersa
module e3010

function main() returns Unit
do
  let x: Option[Int] = None
  return
end
```

### E3013

No property-test generator for this type

Severity `error`, category `type`.

Wrong ([`conformance/types/e3013.tersa`](../conformance/types/e3013.tersa), `tersa check` reports it):

```tersa
module e3013

test "no function generator" for all f: function(Int) returns Int
do
  expect true
end
```

Fixed:

```tersa
module e3013

test "no function generator" for all n: Int
do
  expect true
end
```

### E3020

Operator is not defined on Text

Severity `error`, category `type`.

Wrong ([`conformance/types/e3020.tersa`](../conformance/types/e3020.tersa), `tersa check` reports it):

```tersa
module e3020

function main() returns Text
do
  return "a" + "b"
end
```

Fixed:

```tersa
module e3020

function main() returns Text
do
  return Text.concat("a", "b")
end
```

### E3021

Division operator is not defined on this type

Severity `error`, category `type`.

Wrong ([`conformance/types/e3021.tersa`](../conformance/types/e3021.tersa), `tersa check` reports it):

```tersa
module e3021

function main() returns Int
do
  return 1 / 2
end
```

Fixed:

```tersa
module e3021

function main() returns Int
do
  return 1 div 2
end
```

### E3022

Condition must be Bool

Severity `error`, category `type`.

Wrong ([`conformance/types/e3022.tersa`](../conformance/types/e3022.tersa), `tersa check` reports it):

```tersa
module e3022

function main() returns Unit
do
  if 1 then
    return
  end
  return
end
```

Fixed:

```tersa
module e3022

function main() returns Unit
do
  if 1 > 0 then
    return
  end
  return
end
```

### E3023

Integer literals are always Int

Severity `error`, category `type`.

Wrong ([`conformance/types/int_literal.tersa`](../conformance/types/int_literal.tersa), `tersa check` reports it):

```tersa
module int_literal

public function main() returns Unit
do
  let n: Int64 = 1
end
```

Fixed:

```tersa
module int_literal

public function main() returns Unit
do
  let n: Int64 = Int64.from_int(1).expect_some("1 fits in Int64")
end
```

### E3024

Int and Int64 cannot be mixed

Severity `error`, category `type`.

Wrong ([`conformance/types/e3024.tersa`](../conformance/types/e3024.tersa), `tersa check` reports it):

```tersa
module e3024

function main() returns Int
do
  return 1 + Int64.max
end
```

Fixed:

```tersa
module e3024

function main() returns Int
do
  return 1 + Int64.to_int(Int64.max)
end
```

### E3025

Ordering operator is not defined for this type

Severity `error`, category `type`.

Wrong ([`conformance/types/e3025.tersa`](../conformance/types/e3025.tersa), `tersa check` reports it):

```tersa
module e3025

function main() returns Bool
do
  return true < false
end
```

Fixed:

```tersa
module e3025

function main() returns Bool
do
  return true != false
end
```

### E3026

Type cannot be compared with ==

Severity `error`, category `type`.

Wrong ([`conformance/types/e3026.tersa`](../conformance/types/e3026.tersa), `tersa check` reports it):

```tersa
module e3026

function main() returns Bool
do
  let f = function (x: Int) returns Int
    do
      x
    end
  let g = function (x: Int) returns Int
    do
      x
    end
  return f == g
end
```

Fixed:

```tersa
module e3026

function main() returns Bool
do
  let f = function (x: Int) returns Int
    do
      x
    end
  let g = function (x: Int) returns Int
    do
      x
    end
  return f(1) == g(1)
end
```

### E3027

Builtin numeric function does not accept this type

Severity `error`, category `type`.

Wrong ([`conformance/types/e3027.tersa`](../conformance/types/e3027.tersa), `tersa check` reports it):

```tersa
module e3027

import std.math

function main() returns Bool
do
  let _ = math.min(true, false)
  return true
end
```

Fixed:

```tersa
module e3027

import std.math

function main() returns Bool
do
  let _ = math.min(1, 2)
  return true
end
```

### E3030

Match is not exhaustive

Severity `error`, category `type`.

Wrong ([`conformance/types/e3030.tersa`](../conformance/types/e3030.tersa), `tersa check` reports it):

```tersa
module e3030

function main() returns Int
do
  match true
    case true then
      return 1
  end
end
```

Fixed:

```tersa
module e3030

function main() returns Int
do
  match true
    case true then
      return 1
    case false then
      return 0
  end
end
```

### E3032

Function is missing a return

Severity `error`, category `type`.

A path does not return or fail, or a bare return in a function whose return type is not Unit.

Wrong ([`conformance/types/e3032.tersa`](../conformance/types/e3032.tersa), `tersa check` reports it):

```tersa
module e3032

function main() returns Int
do
  let x = 1
end
```

Fixed:

```tersa
module e3032

function main() returns Int
do
  let x = 1
  return x
end
```

### E3033

Return value does not match the function return type

Severity `error`, category `type`.

Wrong ([`conformance/types/e3033.tersa`](../conformance/types/e3033.tersa), `tersa check` reports it):

```tersa
module e3033

function main() returns Int
do
  return true
end
```

Fixed:

```tersa
module e3033

function main() returns Int
do
  return 1
end
```

### E3034

main must return Unit or Result[Unit, E]

Severity `error`, category `type`.

Wrong ([`conformance/types/e3034.tersa`](../conformance/types/e3034.tersa), `tersa run` refuses to start):

```tersa
module e3034

function main() returns Int
do
  return 1
end
```

Fixed:

```tersa
module e3034

function main() returns Unit
do
  return
end
```

### E3040

Orphan interface implementation

Severity `error`, category `type`.

Wrong ([`conformance/types/e3040.tersa`](../conformance/types/e3040.tersa), `tersa check` reports it):

```tersa
module e3040

implements Comparable[Int]
  function compare(a: Int, b: Int) returns Ordering
  do
    return Equal
  end
end
```

Fixed:

```tersa
module e3040

record Score
  value: Int
end

implements Comparable[Score]
  function compare(a: Score, b: Score) returns Ordering
  do
    return Equal
  end
end
```

### E3041

This interface cannot be implemented by user code

Severity `error`, category `type`.

Wrong ([`conformance/types/e3041.tersa`](../conformance/types/e3041.tersa), `tersa check` reports it):

```tersa
module e3041

record Box
  value: Int
end

implements Equatable[Box]
  function equal(a: Box, b: Box) returns Bool
  do
    return true
  end
end
```

Fixed:

```tersa
module e3041

record Box
  value: Int
end
```

### E3042

Type is not Hashable

Severity `error`, category `type`.

Wrong ([`conformance/types/e3042.tersa`](../conformance/types/e3042.tersa), `tersa check` reports it):

```tersa
module e3042

function main() returns Unit
do
  let _ = {1.0: 1}
  return
end
```

Fixed:

```tersa
module e3042

function main() returns Unit
do
  let _ = {1: 1}
  return
end
```

### E3043

Duplicate interface implementation

Severity `error`, category `type`.

Wrong ([`conformance/types/e3043.tersa`](../conformance/types/e3043.tersa), `tersa check` reports it):

```tersa
module e3043

record Rect
  w: Int
  h: Int
end

implements Comparable[Rect]
  function compare(a: Rect, b: Rect) returns Ordering
  do
    return Equal
  end
end

implements Comparable[Rect]
  function compare(a: Rect, b: Rect) returns Ordering
  do
    return Equal
  end
end
```

Fixed:

```tersa
module e3043

record Rect
  w: Int
  h: Int
end

implements Comparable[Rect]
  function compare(a: Rect, b: Rect) returns Ordering
  do
    return Equal
  end
end
```

### E3044

Interface implementation is missing a function

Severity `error`, category `type`.

Wrong ([`conformance/types/e3044.tersa`](../conformance/types/e3044.tersa), `tersa check` reports it):

```tersa
module e3044

record Box
  value: Int
end

implements Comparable[Box]
end
```

Fixed:

```tersa
module e3044

record Box
  value: Int
end

implements Comparable[Box]
  function compare(a: Box, b: Box) returns Ordering
  do
    return Equal
  end
end
```

### E3045

Type is not Showable

Severity `error`, category `type`.

Wrong ([`conformance/types/e3045_resource.tersa`](../conformance/types/e3045_resource.tersa), `tersa check` reports it):

```tersa
module e3045_resource

function present(f: File) returns Text
do
  return show(f)
end

function main() returns Unit
do
  return
end
```

Fixed:

```tersa
module e3045_resource

function present(f: File) returns Text
do
  return "a file"
end

function main() returns Unit
do
  return
end
```

### E3046

Type does not implement the interface

Severity `error`, category `type`.

A type argument that misses a constraint (T: Comparable, T: Describable, T: Equatable), or a call to an interface function for a type with no implements block. A missed Showable is E3045 and a missed Hashable is E3042.

Wrong ([`conformance/types/e3046.tersa`](../conformance/types/e3046.tersa), `tersa check` reports it):

```tersa
module e3046

record Box
  value: Int
end

function smallest[T: Comparable](a: T, b: T) returns T
do
  if compare(a, b) == Greater then
    return b
  end
  return a
end

function main() returns Unit
do
  let box = smallest(Box(value = 1), Box(value = 2))  # ERROR E3046: no Comparable[Box]
  return
end
```

Fixed:

```tersa
module e3046

record Box
  value: Int
end

function smallest[T: Comparable](a: T, b: T) returns T
do
  if compare(a, b) == Greater then
    return b
  end
  return a
end

function main() returns Unit
do
  let box = smallest(1, 2)
  return
end
```

### E3047

Function does not match the task interface

Severity `error`, category `type`.

Harness only. The attempt has no top-level function a task's interface.tersa requires, or declares it with different type parameters (compared by position), constraints, parameter count or types, or return type. Parameter names, public, contracts, and effects are not compared; the task's effects grant governs effects. The episode stops at the check stage with C 0 and reward 0, and the diagnostic keeps full detail in the agent view, because the interface is public. A reference solution that does not match is I9025 when the task loads.

Wrong ([`conformance/harness/e3047.tersa`](../conformance/harness/e3047.tersa), `tersa harness run` reports it against the task interface below):

```tersa
module e3047

function add_one(n: Int) returns Text
do
  return show(n + 1)
end
```

Task interface ([`conformance/harness/e3047_interface.tersa`](../conformance/harness/e3047_interface.tersa)):

```tersa
module e3047_interface

interface Solution
  function add_one(n: Int) returns Int
    ensures result == n + 1
end
```

Fixed:

```tersa
module e3047

function add_one(n: Int) returns Int
do
  return n + 1
end
```

### E3060

try requires Option or Result

Severity `error`, category `type`.

try on a value that is neither, or try in a function that does not return Option or a Result with the same error type.

Wrong ([`conformance/types/e3060.tersa`](../conformance/types/e3060.tersa), `tersa check` reports it):

```tersa
module e3060

function main() returns Unit
do
  let _ = try 1
  return
end
```

Fixed:

```tersa
module e3060

function main() returns Unit
do
  let _ = 1
  return
end
```

### E3070

A mutable collection cannot be stored or returned here

Severity `error`, category `type`.

Wrong ([`conformance/types/e3070.tersa`](../conformance/types/e3070.tersa), `tersa check` reports it):

```tersa
module e3070

record Box
  items: MutableList[Int]
end
```

Fixed:

```tersa
module e3070

record Box
  items: List[Int]
end
```

### E3071

A lambda cannot capture a var

Severity `error`, category `type`.

Wrong ([`conformance/types/e3071.tersa`](../conformance/types/e3071.tersa), `tersa check` reports it):

```tersa
module e3071

function main() returns Unit
do
  var n = 1
  let _ = function () returns Int
    do
      n
    end
  return
end
```

Fixed:

```tersa
module e3071

function main() returns Unit
do
  let n = 1
  let _ = function () returns Int
    do
      n
    end
  return
end
```

### E3072

A resource must be bound with using

Severity `error`, category `type`.

Wrong ([`conformance/types/e3072.tersa`](../conformance/types/e3072.tersa), `tersa check` reports it):

```tersa
module e3072

function main() returns Unit
do
  using f = 1
  do
    return
  end
end
```

No fixed example: the fix binds a real resource, such as a `File` from `File.open`.

### E3080

Record is built with positional arguments

Severity `error`, category `type`.

Wrong ([`conformance/types/e3080.tersa`](../conformance/types/e3080.tersa), `tersa check` reports it):

```tersa
module e3080

record Box
  value: Int
end

function main() returns Unit
do
  let _ = Box(1)
  return
end
```

Fixed:

```tersa
module e3080

record Box
  value: Int
end

function main() returns Unit
do
  let _ = Box(value = 1)
  return
end
```

### E3081

Named arguments are only allowed when constructing a record

Severity `error`, category `type`.

Wrong ([`conformance/types/e3081.tersa`](../conformance/types/e3081.tersa), `tersa check` reports it):

```tersa
module e3081

function main() returns Unit
do
  let _ = Some(value = 1)
  return
end
```

Fixed:

```tersa
module e3081

function main() returns Unit
do
  let _ = Some(1)
  return
end
```

### E3082

Unknown or duplicate record field

Severity `error`, category `type`.

Also a missing record field. Covers construction, with, field access, and set. A method a non-record type does not have is E3004.

Wrong ([`conformance/types/e3082.tersa`](../conformance/types/e3082.tersa), `tersa check` reports it):

```tersa
module e3082

record Box
  value: Int
end

function main() returns Unit
do
  let _ = Box(value = 1, extra = 2)
  return
end
```

Fixed:

```tersa
module e3082

record Box
  value: Int
end

function main() returns Unit
do
  let _ = Box(value = 1)
  return
end
```

### E4001

Function is missing an effect

Severity `error`, category `effect`.

Wrong ([`conformance/effects/e4001.tersa`](../conformance/effects/e4001.tersa), `tersa check` reports it):

```tersa
module e4001

import std.console exposing print

function main() returns Unit
do
  print("hi")
  return
end
```

Fixed:

```tersa
module e4001

import std.console exposing print

function main() returns Unit
  uses Console
do
  print("hi")
  return
end
```

### E4002

An effectful function cannot be used as a value

Severity `error`, category `effect`.

Wrong ([`conformance/effects/e4002.tersa`](../conformance/effects/e4002.tersa), `tersa check` reports it):

```tersa
module e4002

import std.console exposing print

function main() returns Unit
  uses Console
do
  let _ = function () returns Unit
    do
      print("hi")
    end
  return
end
```

Fixed:

```tersa
module e4002

import std.console exposing print

function main() returns Unit
  uses Console
do
  print("hi")
  return
end
```

### E4003

Unknown effect

Severity `error`, category `effect`.

Wrong ([`conformance/effects/e4003.tersa`](../conformance/effects/e4003.tersa), `tersa check` reports it):

```tersa
module e4003

function main() returns Unit
  uses NotReal
do
  return
end
```

Fixed:

```tersa
module e4003

function main() returns Unit
  uses Console
do
  return
end
```

### E4010

main uses an effect that was not granted

Severity `error`, category `effect`.

Reported before main runs, when main's declared effects are not in the host grants. A call that reaches an ungranted effect at run time, including inside a test, is T6302.

Wrong ([`conformance/effects/e4010.tersa`](../conformance/effects/e4010.tersa), `tersa run` refuses to start):

```tersa
module e4010

import std.console exposing print

function main() returns Unit
  uses Console
do
  print("hi")
  return
end
```

No fixed example: the fix is the grant, `tersa run --allow Console`.

### E4011

Function is not available in RL mode

Severity `error`, category `effect`.

Wrong ([`conformance/effects/e4011.tersa`](../conformance/effects/e4011.tersa), `tersa check` reports it):

```tersa
# mode: rl
module e4011

import std.math

function main() returns Float
do
  return math.sin(0.0)
end
```

Fixed:

```tersa
# mode: rl
module e4011

import std.math

function main() returns Float
do
  return math.sqrt(0.0)
end
```

### E4012

foreign declarations are only allowed in host mode

Severity `error`, category `effect`.

Wrong ([`conformance/effects/e4012.tersa`](../conformance/effects/e4012.tersa), `tersa check` reports it):

```tersa
module e4012

foreign "python" function ping() returns Unit
  uses Python
```

No fixed example: the fix is `mode = "host"` in the package manifest.

### E4013

Unknown standard-library module

Severity `error`, category `effect`.

Wrong ([`conformance/effects/e4013.tersa`](../conformance/effects/e4013.tersa), `tersa check` reports it):

```tersa
module e4013

import std.missing

function main() returns Unit
do
  return
end
```

Fixed:

```tersa
module e4013

import std.math

function main() returns Unit
do
  return
end
```

### E4020

Value is not convertible at the Python boundary

Severity `error`, category `effect`.

Wrong ([`conformance/effects/e4020.tersa`](../conformance/effects/e4020.tersa), `tersa check` reports it):

```tersa
# mode: host
module e4020

foreign "python:mylib.apply" function apply(f: function(Int) returns Int, x: Int) returns Int
  uses Python
```

Fixed:

```tersa
# mode: host
module e4020

foreign "python:mylib.apply" function apply(x: Int) returns Int
  uses Python
```

### E5001

`result` or `old` is used outside `ensures`

Severity `error`, category `contract`.

Wrong ([`conformance/contracts/e5001.tersa`](../conformance/contracts/e5001.tersa), `tersa check` reports it):

```tersa
module e5001

function main() returns Unit
do
  let n = 1
  let _ = old(n)
  return
end
```

Fixed:

```tersa
module e5001

function main() returns Unit
do
  let n = 1
  let _ = n
  return
end
```

### E5002

Contract uses an effect or a var

Severity `error`, category `contract`.

Wrong ([`conformance/contracts/e5002.tersa`](../conformance/contracts/e5002.tersa), `tersa check` reports it):

```tersa
module e5002

import std.console exposing print

function f() returns Bool
  requires print("x")
do
  return true
end
```

Fixed:

```tersa
module e5002

import std.console exposing print

function f() returns Bool
  requires true
do
  return true
end
```

### E5010

Implementation adds a requires clause

Severity `error`, category `contract`.

Wrong ([`conformance/contracts/e5010.tersa`](../conformance/contracts/e5010.tersa), `tersa check` reports it):

```tersa
module e5010

record Box
  value: Int
end

implements Comparable[Box]
  function compare(a: Box, b: Box) returns Ordering
    requires a.value >= 0
  do
    return Equal
  end
end
```

Fixed:

```tersa
module e5010

record Box
  value: Int
end

implements Comparable[Box]
  function compare(a: Box, b: Box) returns Ordering
  do
    return Equal
  end
end
```

### I9010

Invalid limit or grant configuration

Severity `info`, category `infrastructure`.

Fuel, memory units, the integer cap, call depth, output bytes, wall_ms, and property-test case count, when the field is missing, not positive, or out of range. Also a host grant that names an unknown effect, a scoped effect (FileRead, FileWrite, Net) without its scope, or an unscoped effect with one, and a task.toml effects entry that gives a scope to an unscoped effect (Console=out). A limit field that is present but not an integer is I9022. Other task-load failures use I9014 through I9022.

No wrong or fixed example. It comes from the host, the harness, or the task loader, not from a program, so there is no program example. Unit tests under `tests/unit/` raise it.

### I9011

Unicode version does not match the language pin

Severity `info`, category `infrastructure`.

Not implemented. No Unicode version is pinned (the host unicodedata version is used), so nothing emits this code.

No wrong or fixed example. It comes from the host, the harness, or the task loader, not from a program, so there is no program example. Unit tests under `tests/unit/` raise it.

### I9012

Console output was truncated

Severity `info`, category `infrastructure`. Reserved: never emitted.

Retired. Output truncation is W6205, a reported result, not an infrastructure error. Do not reuse this number.

### I9013

Wall-clock timeout stopped the run

Severity `info`, category `infrastructure`.

Infrastructure only. The message names the backstop: in-process wall-clock backstop reached (N ms), or child process wall-clock backstop reached (N s). tersa sandbox and tersa run use this code and exit 4. A reference stopped during validation or measurement keeps this code on that reference episode. tersa harness validate fails its gate and exits 1. tersa harness run falls back to the declared or limit basis with E_basis_reason reference_did_not_execute. A candidate's own clock is T6208. An OS memory kill is T6206.

No wrong or fixed example. It comes from the host, the harness, or the task loader, not from a program, so there is no program example. Unit tests under `tests/unit/` raise it.

### I9014

task.toml is missing

Severity `info`, category `infrastructure`.

No wrong or fixed example. It comes from the host, the harness, or the task loader, not from a program, so there is no program example. Unit tests under `tests/unit/` raise it.

### I9015

Task language does not match this interpreter

Severity `info`, category `infrastructure`.

No wrong or fixed example. It comes from the host, the harness, or the task loader, not from a program, so there is no program example. Unit tests under `tests/unit/` raise it.

### I9016

Unknown effect

Severity `info`, category `infrastructure`.

No wrong or fixed example. It comes from the host, the harness, or the task loader, not from a program, so there is no program example. Unit tests under `tests/unit/` raise it.

### I9017

Effect cannot be granted in RL mode

Severity `info`, category `infrastructure`.

FileRead, FileWrite, Net, and Python. A task.toml that lists one fails to load, with or without a scope (FileRead=data is refused at load time too, so a task grant never carries a scope). tersa sandbox, tersa run --mode rl, tersa test --mode rl, and run_sandboxed refuse the same grants before anything runs. All exit 4.

No wrong or fixed example. It comes from the host, the harness, or the task loader, not from a program, so there is no program example. Unit tests under `tests/unit/` raise it.

### I9018

Reward weight is outside 0..1

Severity `info`, category `infrastructure`.

check_credit and efficiency_weight are numbers outside 0..1. A reward field that is not a number is I9022.

No wrong or fixed example. It comes from the host, the harness, or the task loader, not from a program, so there is no program example. Unit tests under `tests/unit/` raise it.

### I9019

Unknown property seed policy

Severity `info`, category `infrastructure`.

No wrong or fixed example. It comes from the host, the harness, or the task loader, not from a program, so there is no program example. Unit tests under `tests/unit/` raise it.

### I9020

hidden/ is missing or has no tests

Severity `info`, category `infrastructure`.

No wrong or fixed example. It comes from the host, the harness, or the task loader, not from a program, so there is no program example. Unit tests under `tests/unit/` raise it.

### I9021

A task source file did not parse

Severity `info`, category `infrastructure`.

No wrong or fixed example. It comes from the host, the harness, or the task loader, not from a program, so there is no program example. Unit tests under `tests/unit/` raise it.

### I9022

task.toml field has the wrong type

Severity `info`, category `infrastructure`.

Includes a limit field that is not an integer and a reward weight that is not a number.

No wrong or fixed example. It comes from the host, the harness, or the task loader, not from a program, so there is no program example. Unit tests under `tests/unit/` raise it.

### I9023

OS CPU limit killed the process

Severity `info`, category `infrastructure`. Reserved: never emitted.

Retired Oct 18, 2026. A candidate OS CPU kill is T6207, a scored trap (reward 0), not an infrastructure discard. Do not reuse this number.

### I9024

Isolation backend is not available

Severity `info`, category `infrastructure`.

The message names the backend. nsjail has no launcher. gVisor is not launched because it needs host cgroup access this build does not grant.

No wrong or fixed example. It comes from the host, the harness, or the task loader, not from a program, so there is no program example. Unit tests under `tests/unit/` raise it.

### I9025

Reference solution does not match the task interface

Severity `info`, category `infrastructure`.

The task fails to load (exit 4) when reference/solution.tersa parses but lacks a function interface.tersa requires or declares it differently. The message names the function and the difference, as in E3047.

No wrong or fixed example. It comes from the host, the harness, or the task loader, not from a program, so there is no program example. Unit tests under `tests/unit/` raise it.

### T6001

Int64 overflow

Severity `error`, category `runtime`.

Wrong ([`conformance/runtime/t6001.tersa`](../conformance/runtime/t6001.tersa), `tersa run` traps):

```tersa
module t6001

function main() returns Unit
do
  let _ = Int64.max + Int64.max
  return
end
```

Fixed:

```tersa
module t6001

function main() returns Unit
do
  let _ = Int64.max - Int64.max
  return
end
```

### T6002

Division by zero

Severity `error`, category `runtime`.

Wrong ([`conformance/runtime/t6002.tersa`](../conformance/runtime/t6002.tersa), `tersa run` traps):

```tersa
module t6002

function main() returns Unit
do
  let _ = 1 div 0
  return
end
```

Fixed:

```tersa
module t6002

function main() returns Unit
do
  let _ = 1 div 1
  return
end
```

### T6003

Int is too large for Float

Severity `error`, category `runtime`.

Wrong ([`conformance/runtime/t6003.tersa`](../conformance/runtime/t6003.tersa), `tersa run` traps):

```tersa
module t6003

import std.math

function main() returns Unit
do
  let n = math.pow(2, 20000)
  let _ = Float.from_int(n)
  return
end
```

Fixed:

```tersa
module t6003

import std.math

function main() returns Unit
do
  let n = math.pow(2, 20)
  let _ = Float.from_int(n)
  return
end
```

### T6010

Text slice is out of range

Severity `error`, category `runtime`.

Wrong ([`conformance/runtime/t6010.tersa`](../conformance/runtime/t6010.tersa), `tersa run` traps):

```tersa
module t6010

function main() returns Unit
do
  let _ = "ab".slice(0, 4)
  return
end
```

Fixed:

```tersa
module t6010

function main() returns Unit
do
  let _ = "ab".slice(0, 2)
  return
end
```

### T6011

Index is out of range

Severity `error`, category `runtime`.

Wrong ([`conformance/runtime/t6011.tersa`](../conformance/runtime/t6011.tersa), `tersa run` traps):

```tersa
module t6011

function main() returns Unit
do
  let xs = [1]
  let _ = xs.at(2)
  return
end
```

Fixed:

```tersa
module t6011

function main() returns Unit
do
  let xs = [1]
  let _ = xs.get(2)
  return
end
```

### T6012

Use of a closed resource

Severity `error`, category `runtime`.

Runtime safety net. A checked program cannot reach a closed resource (E3072, and using closes it after the body), so only a unit test that bypasses the checker produces it.

No wrong or fixed example: no conformance program produces it.

### T6013

Invalid byte data

Severity `error`, category `runtime`.

Wrong ([`conformance/runtime/t6013_hex.tersa`](../conformance/runtime/t6013_hex.tersa), `tersa run` traps):

```tersa
module t6013_hex

function main() returns Unit
do
  let _ = Bytes.of_hex("abc")
  return
end
```

Fixed:

```tersa
module t6013_hex

function main() returns Unit
do
  let _ = Bytes.of_hex("abcd")
  return
end
```

### T6020

expect_some failed

Severity `error`, category `runtime`.

Wrong ([`conformance/runtime/t6020.tersa`](../conformance/runtime/t6020.tersa), `tersa run` traps):

```tersa
module t6020

function main() returns Unit
do
  let n: Option[Int] = None
  let _ = n.expect_some("missing")
  return
end
```

Fixed:

```tersa
module t6020

function main() returns Unit
do
  let n: Option[Int] = None
  let _ = n.unwrap_or(0)
  return
end
```

### T6021

Value is not Showable

Severity `error`, category `runtime`. Reserved: never emitted.

Retired Oct 18, 2026 because show is now checked statically. Calling show on a type that is not Showable is E3045. Do not reuse this number.

### T6030

fail

Severity `error`, category `runtime`.

Wrong ([`conformance/runtime/t6030.tersa`](../conformance/runtime/t6030.tersa), `tersa run` traps):

```tersa
module t6030

function main() returns Unit
do
  fail "stop"
end
```

Fixed:

```tersa
module t6030

function main() returns Unit
do
  return
end
```

### T6031

expect failed

Severity `error`, category `runtime`.

Wrong ([`conformance/runtime/t6031.tersa`](../conformance/runtime/t6031.tersa), `tersa test` fails):

```tersa
module t6031

test "fails"
do
  expect false
end
```

Fixed:

```tersa
module t6031

test "fails"
do
  expect true
end
```

### T6101

requires failed

Severity `error`, category `contract`.

Wrong ([`conformance/contracts/caller.tersa`](../conformance/contracts/caller.tersa), `tersa run` traps):

```tersa
module caller

public function safe_divide(a: Int, b: Int) returns Int
  requires b != 0
do
  return a div b
end

public function main() returns Unit
do
  let n = safe_divide(1, 0)
end
```

Fixed:

```tersa
module caller

public function safe_divide(a: Int, b: Int) returns Int
  requires b != 0
do
  return a div b
end

public function main() returns Unit
do
  let n = safe_divide(1, 1)
end
```

### T6102

ensures failed

Severity `error`, category `contract`.

Wrong ([`conformance/runtime/t6102.tersa`](../conformance/runtime/t6102.tersa), `tersa run` traps):

```tersa
module t6102

function f() returns Int
  ensures result > 0
do
  return 0
end

function main() returns Unit
do
  let _ = f()
  return
end
```

Fixed:

```tersa
module t6102

function f() returns Int
  ensures result > 0
do
  return 1
end

function main() returns Unit
do
  let _ = f()
  return
end
```

### T6103

invariant failed

Severity `error`, category `contract`.

Wrong ([`conformance/runtime/t6103.tersa`](../conformance/runtime/t6103.tersa), `tersa run` traps):

```tersa
module t6103

record Box
  value: Int
  invariant value > 0
end

function main() returns Unit
do
  let _ = Box(value = 0)
  return
end
```

Fixed:

```tersa
module t6103

record Box
  value: Int
  invariant value > 0
end

function main() returns Unit
do
  let _ = Box(value = 1)
  return
end
```

### T6104

Contract trapped

Severity `error`, category `contract`.

Wrong ([`conformance/runtime/t6104.tersa`](../conformance/runtime/t6104.tersa), `tersa run` traps):

```tersa
module t6104

function f(n: Int) returns Int
  requires (1 div n) == 1
do
  return n
end

function main() returns Unit
do
  let _ = f(0)
  return
end
```

Fixed:

```tersa
module t6104

function f(n: Int) returns Int
  requires n != 0
do
  return n
end

function main() returns Unit
do
  let _ = f(1)
  return
end
```

### T6201

Fuel exhausted

Severity `error`, category `limit`.

Wrong ([`conformance/runtime/t6201.tersa`](../conformance/runtime/t6201.tersa), `tersa run` traps):

```tersa
# fuel: 1
module t6201

function main() returns Unit
do
  var n = 0
  while n < 5
  do
    set n = n + 1
  end
  return
end
```

No fixed example: the program is correct; the run grants 1 unit of fuel, and the fix is a larger budget.

### T6202

Memory limit exceeded

Severity `error`, category `limit`.

Wrong ([`conformance/runtime/t6202.tersa`](../conformance/runtime/t6202.tersa), `tersa run` traps):

```tersa
# memory: 1
module t6202

function main() returns Unit
do
  let _ = [1, 2, 3, 4, 5]
  return
end
```

No fixed example: the program is correct; the run grants 1 memory unit, and the fix is a larger budget.

### T6203

Call depth exceeded

Severity `error`, category `limit`.

Wrong ([`conformance/runtime/t6203.tersa`](../conformance/runtime/t6203.tersa), `tersa run` traps):

```tersa
# depth: 4
module t6203

function down(n: Int) returns Int
do
  return down(n)
end

function main() returns Unit
do
  let _ = down(1)
  return
end
```

Fixed:

```tersa
# depth: 4
module t6203

function down(n: Int) returns Int
do
  if n <= 0 then
    return 0
  end
  return down(n - 1)
end

function main() returns Unit
do
  let _ = down(1)
  return
end
```

### T6204

Integer size limit exceeded

Severity `error`, category `limit`.

Wrong ([`conformance/runtime/pow_cap.tersa`](../conformance/runtime/pow_cap.tersa), `tersa run` traps):

```tersa
module pow_cap

import std.math exposing pow

public function main() returns Unit
do
  let n = pow(2, 10000000)
end
```

Fixed:

```tersa
module pow_cap

import std.math exposing pow

public function main() returns Unit
do
  let n = pow(2, 100)
end
```

### T6206

OS memory limit exceeded

Severity `error`, category `limit`.

A candidate died from the address cap or a memory fault: MemoryError, SIGKILL, SIGSEGV, SIGBUS, or SIGABRT. The episode scores reward 0 with correctness 0 and efficiency 0, and the harness exits 2. Every hidden test is listed by its real name. One that was running is trapped; tests that never started are failed. The kill diagnostic is on the episode. This applies under every isolation backend, including none.

No wrong or fixed example. It comes from an OS limit or the wall clock on the harness child, not from the program text, so there is no program example. See `docs/harness.md`.

### T6207

OS CPU limit exceeded

Severity `error`, category `limit`.

A candidate died from the CPU cap (SIGXCPU). The episode scores reward 0 with correctness 0 and efficiency 0, and the harness exits 2. Every hidden test is listed by its real name. One that was running is trapped; tests that never started are failed. The kill diagnostic is on the episode. A process-count cap stops new processes with an error instead of this code.

No wrong or fixed example. It comes from an OS limit or the wall clock on the harness child, not from the program text, so there is no program example. See `docs/harness.md`.

### T6208

Wall-clock limit exceeded

Severity `error`, category `limit`.

A candidate's own execution hit the in-process wall clock or the child-process timeout. The message names which clock. The episode scores reward 0 with correctness 0 and efficiency 0, and the harness exits 2, because a slow program must not be discarded. The host cannot be told apart from that program. Every hidden test is listed by its real name. One that was running is trapped; tests that never started are failed. A wall-clock stop while measuring the reference is I9013 on that reference episode. tersa harness validate then fails its gate and exits 1. tersa harness run falls back to the declared or limit basis with E_basis_reason reference_did_not_execute.

No wrong or fixed example. It comes from an OS limit or the wall clock on the harness child, not from the program text, so there is no program example. See `docs/harness.md`.

### T6301

Capability scope violated

Severity `error`, category `capability`.

Wrong ([`conformance/runtime/t6301.tersa`](../conformance/runtime/t6301.tersa), `tersa run` traps):

```tersa
# allow: FileRead=.
module t6301

function main() returns Result[Unit, FileError]
  uses FileRead
do
  let _ = try File.read_text("../outside-the-grant")
  return Ok(Unit)
end
```

No fixed example: the fix is a path inside the grant, and that file must exist.

### T6302

Effect was not granted

Severity `error`, category `capability`.

A runtime trap. main's missing grants are E4010, before any code runs.

Wrong ([`conformance/effects/t6302.tersa`](../conformance/effects/t6302.tersa), `tersa test` fails):

```tersa
module t6302

import std.console exposing print

test "prints"
do
  print("hi")
end
```

No fixed example: the fix is the grant, `tersa test --allow Console`.

### T6401

Foreign call failed

Severity `error`, category `interop`.

Wrong ([`conformance/runtime/t6401.tersa`](../conformance/runtime/t6401.tersa), `tersa run` traps):

```tersa
# mode: host
# allow: Python
module t6401

foreign "python:math.factorial" function factorial(n: Int) returns Int
  uses Python

function main() returns Unit
  uses Python
do
  let _ = factorial(-1)
  return
end
```

Fixed:

```tersa
# mode: host
# allow: Python
module t6401

foreign "python:math.factorial" function factorial(n: Int) returns Int
  uses Python

function main() returns Unit
  uses Python
do
  let _ = factorial(5)
  return
end
```

### T6402

Foreign value cannot be converted

Severity `error`, category `interop`.

Wrong ([`conformance/runtime/t6402.tersa`](../conformance/runtime/t6402.tersa), `tersa run` traps):

```tersa
# mode: host
# allow: Python
module t6402

foreign "python:math.factorial" function factorial(n: Int) returns Int64
  uses Python

function main() returns Unit
  uses Python
do
  let _ = factorial(21)
  return
end
```

Fixed:

```tersa
# mode: host
# allow: Python
module t6402

foreign "python:math.factorial" function factorial(n: Int) returns Int64
  uses Python

function main() returns Unit
  uses Python
do
  let _ = factorial(20)
  return
end
```

### W1103

and and or are mixed without parentheses

Severity `warning`, category `syntax`.

Wrong ([`conformance/syntax/mixed_and_or.tersa`](../conformance/syntax/mixed_and_or.tersa), `tersa check` warns):

```tersa
# fmt: skip
module mixed_and_or

function main() returns Bool
do
  return true and false or true
end
```

Fixed:

```tersa
# fmt: skip
module mixed_and_or

function main() returns Bool
do
  return (true and false) or true
end
```

### W1104

Format-skip comment is not exactly `# fmt: skip`

Severity `warning`, category `syntax`.

A full-line comment that normalizes to #fmt:skip but is not the exact marker `# fmt: skip`. The file is not skipped and is formatted normally. tersa fmt and tersa check (with or without --parse-only) always emit it; tersa run, tersa sandbox, and tersa test emit it only alongside a check error or trap that stops the run; the harness never does.

Wrong ([`conformance/syntax/w1104_fmt_skip.tersa`](../conformance/syntax/w1104_fmt_skip.tersa), `tersa check` warns):

```tersa
#fmt:skip
module w1104_fmt_skip

function main() returns Unit
do
  return
end
```

Fixed:

```tersa
# fmt: skip
module w1104_fmt_skip

function main() returns Unit
do
  return
end
```

### W3001

A non-Unit value is ignored

Severity `warning`, category `type`.

Wrong ([`conformance/types/w3001.tersa`](../conformance/types/w3001.tersa), `tersa check` warns):

```tersa
module w3001

function main() returns Unit
do
  show(1)
  return
end
```

Fixed:

```tersa
module w3001

function main() returns Unit
do
  let _ = show(1)
  return
end
```

### W3031

Match arm is unreachable

Severity `warning`, category `type`.

Wrong ([`conformance/types/w3031.tersa`](../conformance/types/w3031.tersa), `tersa check` warns):

```tersa
module w3031

function main() returns Int
do
  match true
    case true then
      return 1
    case true then
      return 2
    case false then
      return 0
  end
end
```

Fixed:

```tersa
module w3031

function main() returns Int
do
  match true
    case true then
      return 1
    case false then
      return 0
  end
end
```

### W3050

at can trap when the index is out of range

Severity `warning`, category `type`.

Wrong ([`conformance/types/w3050_bare.tersa`](../conformance/types/w3050_bare.tersa), `tersa check` warns):

```tersa
module w3050_bare

function main() returns Unit
do
  let xs = [1, 2, 3]
  let _ = xs.at(0)
  return
end
```

Fixed:

```tersa
module w3050_bare

function main() returns Unit
do
  let xs = [1, 2, 3]
  let _ = xs.get(0)
  return
end
```

### W6205

Console output was truncated

Severity `warning`, category `limit`.

A reported result. The run is kept, and an RL episode is not discarded. This replaced I9012.

Wrong ([`conformance/runtime/w6205.tersa`](../conformance/runtime/w6205.tersa), `tersa run` reports it):

```tersa
# allow: Console
# output-bytes: 0
module w6205

import std.console exposing print

function main() returns Unit
  uses Console
do
  print("hello")
  return
end
```

No fixed example: the program is correct; the run allows 0 output bytes, and the fix is a larger cap.
