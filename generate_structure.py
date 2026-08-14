import re
from pathlib import Path


# Equivalent to the PowerShell filter:
# $_.Name -notmatch "venv|__pycache__|\.git|\.idea"
EXCLUDED_NAME_PATTERN = re.compile(
    r"venv|__pycache__|\.git|\.idea",
    re.IGNORECASE,
)


def show_tree(path: Path, indent: str = "") -> list[str]:
    """
    Build a textual tree of the given directory.

    This mirrors the original PowerShell function:
    - Scans the current directory and all subdirectories.
    - Excludes names matching:
      venv, __pycache__, .git, or .idea.
    - Writes each item using the same tree prefixes.
    """
    lines: list[str] = []

    try:
        items = sorted(path.iterdir(), key=lambda item: item.name.lower())
    except (PermissionError, OSError):
        return lines

    for item in items:
        if EXCLUDED_NAME_PATTERN.search(item.name):
            continue

        lines.append(f"{indent}├── {item.name}")

        if item.is_dir():
            lines.extend(show_tree(item, f"{indent}│   "))

    return lines


def main() -> None:
    project_path = Path.cwd()
    output_path = project_path / "structure.txt"

    # Create or overwrite structure.txt before scanning, matching:
    # Show-Tree . > structure.txt
    output_path.write_text("", encoding="utf-8")

    tree_lines = show_tree(project_path)

    output_path.write_text(
        "\n".join(tree_lines) + ("\n" if tree_lines else ""),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
