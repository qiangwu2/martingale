#!/usr/bin/env python3
"""Validate the Lean pages; --live compares the published pages and assets.

This checks source structure, links, metadata and HTTP content. It is not a
browser layout or JavaScript interaction test. The existing x-dc renderer and
stylesheet are intentionally preserved.
"""

import argparse
from html.parser import HTMLParser
from pathlib import Path
import re
import struct
from urllib.parse import unquote, urlsplit
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parent.parent
ORIGIN = "https://qiangwu2.github.io/martingale/"
PAGES = ("LeanFormalization.dc.html", "LeanParisiFormula.dc.html")
VOID = set("area base br col embed hr img input link meta param source track wbr".split())


class Page(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.nodes = []
        self.ids = set()
        self.feed(source)
        assert not self.stack, f"Unclosed elements: {self.stack}"

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.nodes.append((tag, attrs, tuple(self.stack)))
        if "id" in attrs:
            assert attrs["id"] not in self.ids, f"Duplicate ID: {attrs['id']}"
            self.ids.add(attrs["id"])
        if tag == "summary":
            assert self.stack[-1:] == ["details"], "Summary must belong to details"
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        assert self.stack and self.stack.pop() == tag, f"Unbalanced element: {tag}"


def check_page(filename, proof_root):
    source = (ROOT / filename).read_text(encoding="utf-8")
    page = Page(source)
    tags = [tag for tag, _, _ in page.nodes]
    for landmark in ("html", "head", "body", "main", "h1", "x-dc", "helmet"):
        assert tags.count(landmark) == 1, f"Expected one {landmark}"
    scripts = [attrs.get("src") for tag, attrs, _ in page.nodes if tag == "script"]
    assert scripts == ["./support.js"], "Preserve the existing renderer"
    styles = [attrs["href"] for tag, attrs, _ in page.nodes
              if tag == "link" and attrs.get("rel") == "stylesheet"
              and not urlsplit(attrs["href"]).scheme]
    assert styles == ["./lean-formalization.css"], "Preserve the existing stylesheet"
    assets = {filename, "support.js", "lean-formalization.css"}
    for tag, attrs, _ in page.nodes:
        for reference in attrs.get("aria-labelledby", "").split():
            assert reference in page.ids, f"Missing accessible label: {reference}"
        for key in ("href", "src"):
            if key not in attrs:
                continue
            assert attrs[key], "Empty link"
            url = urlsplit(attrs[key])
            if url.scheme or url.netloc:
                prefix = "/qiangwu2/ParisiFormula/blob/main/"
                if proof_root and url.netloc == "github.com" and url.path.startswith(prefix):
                    target = proof_root / unquote(url.path.removeprefix(prefix))
                    assert target.is_file(), f"Missing linked proof source: {target}"
                continue
            target = ROOT / unquote(url.path or filename)
            assert target.is_file(), f"Missing local file: {target}"
            if url.fragment:
                ids = page.ids if target.name == filename else set(
                    re.findall(r'id="([^"]+)"', target.read_text(encoding="utf-8")))
                assert unquote(url.fragment) in ids, f"Missing fragment: {attrs[key]}"
        if tag == "img":
            assert attrs.get("alt"), "Images need descriptive alternative text"
            asset_path = urlsplit(attrs["src"]).path.removeprefix("./")
            with (ROOT / asset_path).open("rb") as asset:
                header = asset.read(24)
            assert header[:8] == b"\x89PNG\r\n\x1a\n"
            assert struct.unpack(">II", header[16:24]) == (int(attrs["width"]), int(attrs["height"]))
            assets.add(asset_path)
    meta = {attrs.get("name", attrs.get("property")): attrs.get("content")
            for tag, attrs, _ in page.nodes if tag == "meta"}
    assert meta["description"] == meta["og:description"] == meta["twitter:description"]
    assert meta["og:title"] == meta["twitter:title"]
    assert meta["og:url"] == ORIGIN + filename
    if filename == PAGES[1]:
        assert tags.count("details") == tags.count("summary") == 7
        assert "The full proof is not yet complete." in source
        assert "Checked implication" in source and "Not yet complete" in source
        assert "Theorem 2.2 remains open." in source
        assert "<i>F</i><sub>N</sub>" in source
        assert "free entropy" not in source.lower() and "parisiValue" not in source
        assert meta["og:image"] == meta["twitter:image"] == ORIGIN + "assets/parisi-landscape.png"
        assert meta["og:image:alt"] == meta["twitter:image:alt"]
    print(f"PASS {filename}: structure, links, labels, illustration, metadata and status")
    return assets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Compare published pages and assets")
    parser.add_argument("--proof-root", type=Path, help="Check linked proof files in a local checkout")
    args = parser.parse_args()
    assets = set()
    for filename in PAGES:
        assets.update(check_page(filename, args.proof_root))
    if args.live:
        for asset in sorted(assets):
            with urlopen(ORIGIN + asset, timeout=30) as response:
                assert response.status == 200, f"HTTP failure: {asset}"
                deployed = response.read()
            assert deployed == (ROOT / asset).read_bytes(), f"Live content differs: {asset}"
            print(f"PASS live content: {asset}")


if __name__ == "__main__":
    main()
