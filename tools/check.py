"""Rychlá lokální kontrola YAML a testů, bez přístupu k domácnosti."""

from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
HA_TAGS = (
    "!include", "!include_dir_list", "!include_dir_named",
    "!include_dir_merge_list", "!include_dir_merge_named", "!secret", "!env_var",
)


@dataclass(frozen=True)
class Reference:
    tag: str
    value: str


class HALoader(yaml.SafeLoader):
    """Značky HA uchová jako odkazy; nikdy nenačítá tajné hodnoty."""

    def construct_mapping(self, node, deep=False):
        # Duplicitní explicitní klíče jsou chyba; přepsání YAML kotvy je platné.
        keys = set()
        for key_node, _ in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                continue
            key = self.construct_object(key_node, deep=deep)
            try:
                if key in keys:
                    raise yaml.constructor.ConstructorError(
                        None, None, "Duplicate key", key_node.start_mark
                    )
                keys.add(key)
            except TypeError:
                raise yaml.constructor.ConstructorError(
                    None, None, "Invalid mapping key", key_node.start_mark
                ) from None
        return super().construct_mapping(node, deep=deep)


def reference(loader, node):
    return Reference(node.tag, loader.construct_scalar(node))


for tag in HA_TAGS:
    HALoader.add_constructor(tag, reference)


def load_yaml(path):
    return yaml.load(path.read_text(encoding="utf-8-sig"), Loader=HALoader)


def yaml_paths(root):
    # Git vymezuje projekt; neprocházíme cizí worktrees ani lokální tajné soubory.
    output = subprocess.check_output(
        ["git", "-c", f"safe.directory={root.as_posix()}", "ls-files",
         "--cached", "--others", "--exclude-standard", "-z"], cwd=root,
    ).decode("utf-8")
    return sorted({
        root / name for name in output.split("\0")
        if name and Path(name).suffix.lower() in (".yaml", ".yml")
        and Path(name).name.lower() != "secrets.yaml"
        and not {".worktrees", ".venv"}.intersection(Path(name).parts)
        and (root / name).is_file()
    })


def references(value):
    if isinstance(value, Reference):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from references(item)
    elif isinstance(value, list):
        for item in value:
            yield from references(item)


def main():
    failures = 0
    paths = yaml_paths(ROOT)
    if not paths:
        print("CHYBA: nebyly nalezeny zadne YAML soubory.")
        return 1
    for path in paths:
        name = path.relative_to(ROOT).as_posix()
        try:
            data = load_yaml(path)
        except (yaml.YAMLError, OSError, UnicodeError) as error:
            # Výpis parseru může obsahovat hodnoty z konfigurace: uvádíme jen místo.
            mark = getattr(error, "problem_mark", None)
            location = f"radek {mark.line + 1}, sloupec {mark.column + 1}" if mark else ""
            print(f"CHYBA YAML: {name}: {type(error).__name__} {location}")
            failures += 1
            continue
        print(f"OK YAML: {name}")
        for ref in references(data):
            if ref.tag.startswith("!include") and not (path.parent / ref.value).exists():
                print(f"UPOZORNENI: {name}: chybi lokalni include {ref.value}")
    if failures:
        # Testy znovu načítají konfiguraci; při chybě YAML by mohly vypsat její obsah.
        print(f"YAML: {len(paths)} souboru, {failures} chyb. Testy neprovedeny.")
        return 1
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    passed = failures == 0 and result.wasSuccessful() and result.testsRun > 0
    print(f"YAML: {len(paths)} souboru, {failures} chyb. Testy: {result.testsRun}.")
    print("Kontrola schemat integraci a behu Home Assistanta nebyla provedena.")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
