import argparse
import ast
import json
import re
import yaml
from pathlib import Path
from typing import Any


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--docs-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "website" / "content" / "docs"
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    docs_root = args.docs_root.resolve()
    paths = sorted(docs_root.rglob("*.mdx"))
    assert paths, "No documentation pages found"
    pages = {}
    snippet_count = 0
    for path in paths:
        metadata, body = read_page(path)
        assert metadata["title"] and metadata["description"], str(path)
        assert metadata["sources"], "Missing sources in %s" % (path,)
        for source in metadata["sources"]:
            assert (root / source).is_file(), "Missing source %s in %s" % (source, path)
        pages[path] = body
        for snippet in re.findall(r"```python[^\n]*\n(.*?)```", body, flags=re.DOTALL):
            ast.parse(snippet, filename=str(path))
            snippet_count += 1
    linked_documents = pages | {
        root / name: (root / name).read_text()
        for name in ["README.md", "BYOB.md", "EXAMPLES.md"]
    }
    for path, body in linked_documents.items():
        for link in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", body):
            if link.startswith(("https://", "http://", "mailto:")):
                continue
            target, _, anchor = link.partition("#")
            if path.suffix == ".mdx" and target.endswith(".mdx"):
                assert target.startswith(("./", "../")), "Use ./ or ../ for Fumadocs links in %s" % (path,)
            if target.startswith("/"):
                destination = root / "website" / "public" / target.lstrip("/")
            else:
                destination = (path.parent / target).resolve() if target else path
            assert destination.is_file(), "Broken link %s in %s" % (link, path)
            if anchor and destination.suffix == ".mdx":
                assert anchor in heading_ids(pages[destination]), "Missing anchor %s in %s" % (anchor, destination)
    for path in sorted(docs_root.rglob("meta.json")):
        metadata = json.loads(path.read_text())
        expected = {
            candidate.stem for candidate in path.parent.glob("*.mdx")
        } | {
            candidate.name for candidate in path.parent.iterdir()
            if candidate.is_dir()
        }
        assert set(metadata["pages"]) == expected, "Navigation differs from files in %s" % (path,)
        assert len(metadata["pages"]) == len(set(metadata["pages"])), str(path)
    api_text = pages[docs_root / "reference" / "public-python-api.mdx"]
    export_tree = ast.parse((root / "harness" / "__init__.py").read_text())
    exports = next(
        ast.literal_eval(node.value) for node in export_tree.body
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        )
    )
    for name in exports:
        assert "`%s`" % (name,) in api_text, "Undocumented public export %s" % (name,)
    hook_text = pages[docs_root / "reference" / "intervention-hooks-and-transforms.mdx"]
    hook_tree = ast.parse((root / "harness" / "interventions.py").read_text())
    hook_class = next(node for node in hook_tree.body if isinstance(node, ast.ClassDef) and node.name == "InterventionHook")
    for node in hook_class.body:
        if isinstance(node, ast.Assign):
            assert "`%s`" % (ast.literal_eval(node.value),) in hook_text, "Undocumented hook"
    catalog = pages[docs_root / "reference" / "example-catalog.mdx"]
    for path in (root / "conf" / "task").rglob("*.yaml"):
        name = path.relative_to(root / "conf" / "task").with_suffix("").as_posix()
        assert "`%s`" % (name,) in catalog, "Undocumented task %s" % (name,)
    commands = pages[docs_root / "reference" / "commands.mdx"]
    command_paths = [
        "inspect_run.py",
        "replay_run.py",
        "harness/trace_viewer.py",
        "harness/integration.py",
        "scripts/generate_experiments.py",
        "scripts/check_documentation.py",
        "scripts/check_documentation_examples.py",
        "integrations/native_desktop/setup.py",
        "integrations/native_desktop/state.py",
        "integrations/native_desktop/report.py"
    ]
    for path in command_paths:
        tree = ast.parse((root / path).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument":
                for argument in node.args:
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str) and argument.value.startswith("--"):
                        assert argument.value in commands, "Undocumented argument %s in %s" % (argument.value, path)
    schemas = pages[docs_root / "reference" / "artifacts-and-schemas.mdx"]
    for filename in ["harness/schema.py", "harness/artifacts.py", "harness/evaluators.py", "harness/replay.py", "harness/environments/driver.py"]:
        for model in ast.parse((root / filename).read_text()).body:
            if not isinstance(model, ast.ClassDef):
                continue
            fields = [node for node in model.body if isinstance(node, ast.AnnAssign)]
            if not fields:
                continue
            assert "### %s\n" % (model.name,) in schemas, "Missing model %s" % (model.name,)
            section = schemas.split("### %s\n" % (model.name,), maxsplit=1)[1].split("\n### ", maxsplit=1)[0]
            for field in fields:
                assert "`%s`" % (field.target.id,) in section, "Missing field %s.%s" % (model.name, field.target.id)
    print("Checked %d pages, %d public exports, internal links, navigation, hooks, tasks, CLI options, and %d Python snippets." % (
        len(paths),
        len(exports),
        snippet_count
    ))


def read_page(path: Path) -> tuple[dict[str, Any], str]:
    _, frontmatter, body = path.read_text().split("---", maxsplit=2)
    return yaml.safe_load(frontmatter), body


def heading_ids(body: str) -> set[str]:
    prose = re.sub(r"```.*?```", "", body, flags=re.DOTALL)
    headings = re.findall(r"^#{1,6} (.+)$", prose, flags=re.MULTILINE)
    return {
        re.sub(r"[^\w\s-]", "", heading.lower()).replace(" ", "-") for heading in headings
    }


if __name__ == "__main__":
    main()
