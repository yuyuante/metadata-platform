"""Split SQL deployment scripts without interpreting SQL semantics."""

import re

_DOLLAR_TAG = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")
_GO_BATCH = re.compile(r"(?im)^[ \t]*GO[ \t]*(?:--[^\r\n]*)?(?:\r?\n|$)")


class ScriptSplitter:
    """Split a SQL script at semicolons outside quoted or commented regions."""

    def split(self, script: str) -> list[str]:
        """Return non-empty SQL statements in source order."""

        batches = _GO_BATCH.split(script)
        if len(batches) > 1:
            split_statements: list[str] = []
            for batch in batches:
                split_statements.extend(self.split(batch))
            return split_statements

        statements: list[str] = []
        start = 0
        index = 0
        length = len(script)
        quote: str | None = None
        dollar_tag: str | None = None
        line_comment = False
        block_comment = False

        while index < length:
            current = script[index]
            following = script[index + 1] if index + 1 < length else ""

            if line_comment:
                if current in "\r\n":
                    line_comment = False
                index += 1
                continue

            if block_comment:
                if current == "*" and following == "/":
                    block_comment = False
                    index += 2
                else:
                    index += 1
                continue

            if dollar_tag is not None:
                if script.startswith(dollar_tag, index):
                    index += len(dollar_tag)
                    dollar_tag = None
                else:
                    index += 1
                continue

            if quote is not None:
                if current == quote:
                    if following == quote:
                        index += 2
                    else:
                        quote = None
                        index += 1
                elif current == "\\" and quote == "'":
                    index += 2
                else:
                    index += 1
                continue

            if current == "-" and following == "-":
                line_comment = True
                index += 2
                continue
            if current == "/" and following == "*":
                block_comment = True
                index += 2
                continue
            if current in ("'", '"'):
                quote = current
                index += 1
                continue
            if current == "$":
                match = _DOLLAR_TAG.match(script, index)
                if match is not None:
                    dollar_tag = match.group(0)
                    index = match.end()
                    continue
            if current == ";":
                statement = script[start : index + 1].lstrip("\ufeff").strip()
                if statement:
                    statements.append(statement)
                start = index + 1
            index += 1

        statement = script[start:].lstrip("\ufeff").strip()
        if statement:
            statements.append(statement)
        return statements
