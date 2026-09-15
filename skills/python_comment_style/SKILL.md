---
name: python_comment_style
description: "python_comment_style: enforce a strict standardized docstring/function-header format on every Python function an agent creates or changes (typed signature; usage line WITHOUT types; returns/errors lines; Google-style Args; executable example). Can also be forced onto existing files with: apply python_comment_style <path> or enforce python_comment_style <path>."
---

# SKILL: Standardized Python Docstring Enforcement

## TRIGGER
Apply this skill AUTOMATICALLY whenever you are writing a new Python function, modifying an existing Python function, or refactoring Python code - in any Python source file or module you create or change.

## APPLY / ENFORCE ON EXISTING FILES (user command)
When the user says `apply python_comment_style <path>` or `enforce python_comment_style <path>`:
- Target that file; without a path, target every Python file of the current module/project.
- Rewrite each function's docstring to the TEMPLATE below **without changing behavior**:
  - ensure the signature carries type hints; add missing hints only when they can be
    inferred with confidence, otherwise leave the signature and flag the function
  - build the `usage:` line from the current signature (shape only - order,
    required vs optional, arity - never types)
  - add or repair `returns:`, conditional `errors:`, `Args:` and `Example:`
- Preserve all code, comments and blank-line structure; only docstrings (and
  confidently inferred missing type hints) change.
- Report one line per function changed.

## RULES
You must enforce a strict, standardized docstring format for all Python functions.

1. **Type Hints**: Always use standard Python type hints in the function signature.
2. **Short Description**: Begin the docstring with a concise description of what the function does.
3. **Usage Line**:
   - Format: `usage: function_name <REQUIRED_ARG> [OPTIONAL_ARG]`
   - **CRITICAL**: NEVER specify parameter types in the `usage:` line. Types belong ONLY in the function signature and the `Args:` section.
   - Use `< >` for required arguments.
   - Use `[ ]` for optional arguments.
4. **Returns Line**: Format: `returns: <description of successful return value>`
5. **Errors Line (Conditional)**: If the function has distinct failure modes, returns specific error codes, or raises specific exceptions, include an `errors:` line immediately below `returns:`.
   - Format: `errors: <code/exception> on <reason>, <code/exception> on <reason>`
6. **Args Section**: Use standard Google-style `Args:` to document parameter types and descriptions.
7. **Example Section**: Provide at least one concrete, executable example of how to call the function.

## TEMPLATE
```python
def function_name(req_arg: type, opt_arg: type = default) -> return_type:
    """Brief description of what the function does.

    usage: function_name <REQ_ARG> [OPT_ARG]
    returns: Description of what is returned on success.
    errors: Description of failure codes/modes (omit if not applicable).

    Args:
        req_arg (type): Description of the required argument.
        opt_arg (type, optional): Description of the optional argument. Defaults to default.

    Example:
        function_name("input", opt_arg=True)
    """
```

## NEGATIVE EXAMPLE (DO NOT DO THIS)
```python
# BAD: Types in usage line, missing Args section, merged return/error logic
def format_data(data: str, upper: bool = False) -> int:
    """Formats the data.
    usage: format_data <DATA: str> [UPPER: bool]
    returns: 0 on success or 1 if it fails or 2 if data is missing
    """
```

## POSITIVE EXAMPLE (DO THIS)
```python
# GOOD: Clean usage line, distinct returns/errors lines, types in signature and Args
def build_html_render(source: str, output: str, context: str = "") -> int:
    """Render an HTML template, substituting {{ key }} placeholders from a JSON context.

    usage: build_html_render <SOURCE> <OUTPUT> [CONTEXT]
    returns: 0 on success
    errors: 1 on missing source file, 2 on invalid JSON context

    Args:
        source (str): Path to the input HTML template file.
        output (str): Path where the rendered HTML will be saved.
        context (str, optional): A JSON string of key-value pairs. Defaults to "".

    Example:
        build_html_render("page.tpl.html", "page.html", '{"title": "Home"}')
    """
```