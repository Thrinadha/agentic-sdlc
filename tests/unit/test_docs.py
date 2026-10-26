"""Documentation stays truthful: every relative link resolves, and the test count in the README is current."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCS = [ROOT / "README.md", ROOT / "AGENTS.md", *sorted((ROOT / "docs").glob("*.md")),
        ROOT / "examples" / "outputs" / "README.md"]
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def _slug(heading: str) -> str:
    return re.sub(r"[^a-z0-9 -]", "", heading.lower()).strip().replace(" ", "-")


@pytest.mark.parametrize("doc", [d for d in DOCS if d.exists()], ids=lambda p: str(p.relative_to(ROOT)))
def test_relative_links_resolve(doc):
    broken = []
    for target in LINK.findall(doc.read_text(encoding="utf-8")):
        if re.match(r"^[a-z]+:", target) or target.startswith("#"):
            continue
        path, _, anchor = target.partition("#")
        dest = (doc.parent / path).resolve()
        if not dest.exists():
            broken.append(target)
        elif anchor and dest.is_file():
            headings = {_slug(h) for h in re.findall(r"^#+\s+(.*)$", dest.read_text(encoding="utf-8"), re.M)}
            if anchor not in headings:
                broken.append(target)
    assert not broken, f"broken links in {doc.name}: {broken}"


def test_readme_test_count_is_current(request):
    stated = re.search(r"(\d+) (?:automated )?tests", (ROOT / "README.md").read_text(encoding="utf-8"))
    items = request.session.items
    collected = len(items)
    suites = {Path(str(i.fspath)).parent.name for i in items}
    if not {"unit", "integration"} <= suites:  # only meaningful when the whole suite is collected
        pytest.skip("run the full suite (`pytest`) to check the count")
    assert stated and int(stated.group(1)) == collected, f"README says {stated.group(1)}, suite has {collected}"
