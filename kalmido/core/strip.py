"""2.191.0 B (#1824): the client's JavaScript and CSS go out without comments (the files in the repo keep them: they are the
documentation). Pure Python, no extra package, no imports from the app.

Only comments are removed, nothing else is minified. Line breaks stay where they were: a line that held only a comment
stays as an empty line, so the line numbers of an error report match the source, and JavaScript's automatic semicolons
see the same line ends. Strings, template literals (also nested ${...}), regular expression literals and CSS url(...)
are copied unchanged. Whenever the scanner is not sure (unterminated string / comment / template, unbalanced braces,
a line break inside a string or regex), it gives up and the file goes out unchanged: never broken.

strip_js(text) / strip_css(text) return the text without comments or None (= unsure, send the original)."""

# a "/" after one of these is the start of a regex literal, after anything else (a name, a number, ")" or "]") a division
_JS_RE_KEYWORDS = frozenset(("return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "throw", "case", "do",
                             "else", "yield", "await"))
_JS_RE_AFTER = frozenset("(,=:[!&|?{};+-*%<>~^}")


def _word(ch):
    return ch.isalnum() or ch in "_$" or ord(ch) > 127


def _drop_trailing_blanks(out):
    """Removes spaces / tabs at the end of the output (only called at code level, where they are mere separators)."""
    while out and out[-1] in (" ", "\t"):
        out.pop()


def strip_js(src):
    out = []           # list of output pieces (single chars or slices)
    n = len(src)
    i = 0
    stack = []         # one entry per open ${ ... } of a template literal: the brace depth inside that expression
    depth = 0          # brace depth of the current code level
    last = ""          # the last significant token at code level: a punctuator char, "w:<word>" or "x" (string/number/regex)
    removed = False    # a comment was removed on the current line (its trailing blanks go too)
    while i < n:
        c = src[i]
        if c == "\n":
            if removed:
                _drop_trailing_blanks(out)
                removed = False
            out.append(c)
            i += 1
            continue
        if c in " \t\r\f\v﻿ ":
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            if j < 0:
                j = n
            _drop_trailing_blanks(out)
            removed = True
            i = j
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            if j < 0:
                return None
            body = src[i + 2:j]
            i = j + 2
            removed = True
            nl = body.count("\n")
            if nl:  # a comment over several lines ends a line for the semicolon rules: keep its line breaks
                _drop_trailing_blanks(out)
                out.append("\n" * nl)
            elif out and out[-1][-1] not in " \t\n" and i < n and src[i] not in " \t\r\n":
                out.append(" ")  # a/**/b is "a b", never "ab"
            continue
        if c in "'\"":
            j = i + 1
            while j < n:
                d = src[j]
                if d == "\\":
                    j += 2
                    continue
                if d == c:
                    break
                if d == "\n":
                    return None
                j += 1
            if j >= n:
                return None
            out.append(src[i:j + 1])
            i = j + 1
            last = "x"
            continue
        if c == "`" or (c == "}" and stack and depth == stack[-1]):
            # a template literal from its start (or from the end of one ${...} expression) to the next ${ or its end
            if c == "}":
                stack.pop()
                depth -= 1
            j = i + 1
            while j < n:
                d = src[j]
                if d == "\\":
                    j += 2
                    continue
                if d == "`":
                    break
                if d == "$" and j + 1 < n and src[j + 1] == "{":
                    break
                j += 1
            if j >= n:
                return None
            if src[j] == "`":
                out.append(src[i:j + 1])
                i = j + 1
                last = "x"
            else:
                out.append(src[i:j + 2])
                i = j + 2
                depth += 1
                stack.append(depth)
                last = "{"
            continue
        if c == "/":
            regex = (last == "" or last in _JS_RE_AFTER or (last.startswith("w:") and last[2:] in _JS_RE_KEYWORDS))
            if regex:
                j = i + 1
                cls = False
                while j < n:
                    d = src[j]
                    if d == "\\":
                        j += 2
                        continue
                    if d == "\n":
                        return None
                    if cls:
                        if d == "]":
                            cls = False
                    elif d == "[":
                        cls = True
                    elif d == "/":
                        break
                    j += 1
                if j >= n:
                    return None
                j += 1
                while j < n and _word(src[j]):  # flags
                    j += 1
                out.append(src[i:j])
                i = j
                last = "x"
                continue
            out.append(c)
            i += 1
            last = "/"
            continue
        if _word(c) or (c == "." and i + 1 < n and src[i + 1].isdigit()):
            j = i + 1
            while j < n and (_word(src[j]) or (src[j] == "." and src[i].isdigit())):
                j += 1
            w = src[i:j]
            out.append(w)
            i = j
            last = "x" if w[0].isdigit() or w[0] == "." else "w:" + w
            continue
        if c in "+-" and i + 1 < n and src[i + 1] == c:
            # ++ / --: after a name (postfix) a following "/" divides; before a name the next token decides anyway
            out.append(src[i:i + 2])
            i += 2
            last = ")" if last == "x" or last.startswith("w:") or last in (")", "]") else c
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth < 0:
                return None
        out.append(c)
        i += 1
        last = c
    if stack or depth != 0:
        return None
    if removed:
        _drop_trailing_blanks(out)
    return "".join(out)


def strip_css(src):
    out = []
    n = len(src)
    i = 0
    removed = False
    while i < n:
        c = src[i]
        if c == "\n":
            if removed:
                _drop_trailing_blanks(out)
                removed = False
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            if j < 0:
                return None
            nl = src.count("\n", i + 2, j)
            i = j + 2
            removed = True
            prev_blank = not out or out[-1][-1] in " \t\n"
            next_blank = i >= n or src[i] in " \t\r\n"
            if prev_blank or next_blank:
                if nl:
                    _drop_trailing_blanks(out)
                    out.append("\n" * nl)
            elif _word(out[-1][-1]) or out[-1][-1] == "-":
                if i < n and (_word(src[i]) or src[i] == "-"):
                    return None  # a/**/b: two words that the comment keeps apart; leave the file alone
            continue
        if c in "'\"":
            j = i + 1
            while j < n:
                d = src[j]
                if d == "\\":
                    j += 2
                    continue
                if d == c or d == "\n":
                    break
                j += 1
            if j >= n or src[j] == "\n":
                return None
            out.append(src[i:j + 1])
            i = j + 1
            continue
        if c in "uU" and src[i:i + 4].lower() == "url(" and (i == 0 or not (_word(src[i - 1]) or src[i - 1] == "-")):
            k = i + 4
            while k < n and src[k] in " \t":
                k += 1
            if k < n and src[k] not in "'\"":  # unquoted url(...): copied as it is up to ")" (// or /* in it are no comment)
                j = src.find(")", k)
                if j < 0 or "\n" in src[k:j]:
                    return None
                out.append(src[i:j + 1])
                i = j + 1
                continue
            out.append(src[i:k])
            i = k
            continue
        out.append(c)
        i += 1
    if removed:
        _drop_trailing_blanks(out)
    return "".join(out)


def strip_asset(rel, data):
    """The bytes of static/<rel> as they go out: .js / .css without comments (static/vendor/ untouched), None = unchanged
    (another kind of file, not UTF-8, or the scanner was unsure)."""
    if rel.startswith("vendor/") or not rel.endswith((".js", ".css")):
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    res = strip_js(text) if rel.endswith(".js") else strip_css(text)
    if res is None:
        return None
    return res.encode("utf-8")
