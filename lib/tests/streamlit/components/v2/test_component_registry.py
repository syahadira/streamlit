# Copyright (c) Streamlit Inc. (2018-2022) Snowflake Inc. (2022-2025)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import os

import pytest

from streamlit.components.v2.component_registry import (
    BidiComponentDefinition,
    BidiComponentRegistry,
)
from streamlit.errors import StreamlitComponentRegistryError


def _mk_file(path: os.PathLike[str] | str, content: bytes | str = b"x") -> str:
    """Create a file and return its absolute path.

    Parameters
    ----------
    path
        Path to write. Parent directories are created if they don't exist.
    content
        Bytes or text to write to the file. Defaults to a single ``x`` byte.

    Returns
    -------
    str
        Absolute path to the created file.
    """
    p = os.fspath(path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    mode = "wb" if isinstance(content, (bytes, bytearray)) else "w"
    with open(p, mode) as f:
        f.write(content)
    return os.path.abspath(p)


def test_path_classification_and_resolution(tmp_path, monkeypatch):
    """Resolve common relative and absolute file paths against caller.

    - Accepts ``./file``, paths with separators, and bare filenames with known
      extensions.
    - Rejects inline-like content containing ``<``, ``>``, ``{``, ``}``.
    """
    base_dir = tmp_path / "base"
    caller_dir = base_dir / "pkg" / "subpkg"
    caller_file = caller_dir / "fakecaller.py"

    # Files to be resolved relative to caller_dir
    style_css = caller_dir / "style.css"
    assets_js = caller_dir / "assets" / "app.js"
    bare_js = caller_dir / "script.js"
    upper_js = base_dir / "pkg" / "upper.js"  # resolves via ../upper.js from subpkg

    _mk_file(caller_file)
    _mk_file(style_css)
    _mk_file(assets_js)
    _mk_file(bare_js)
    _mk_file(upper_js)

    # Make _get_caller_path return our fake caller file
    from streamlit.components.v2 import component_registry as cr

    monkeypatch.setattr(
        cr, "_get_caller_path", lambda: os.fspath(caller_file), raising=True
    )

    d1 = BidiComponentDefinition(name="c1", css="./style.css")
    assert d1._has_css_path is True
    assert d1.source_paths["css"] == os.path.dirname(os.fspath(style_css))
    assert d1.css_url == "style.css"

    with pytest.raises(
        ValueError, match=r"Parent directory traversal \('\.\.'\) is not allowed"
    ):
        BidiComponentDefinition(name="c_bad", js="../upper.js")

    # Accept: path with separator
    d2 = BidiComponentDefinition(name="c2", js="assets/app.js")
    assert d2._has_js_path is True
    assert d2.source_paths["js"] == os.path.dirname(os.fspath(assets_js))

    # Accept: bare filename with known extension
    d3 = BidiComponentDefinition(name="c3", js="script.js")
    assert d3._has_js_path is True
    assert d3.source_paths["js"] == os.path.dirname(os.fspath(bare_js))

    # Inline-like content is not treated as a path
    d4 = BidiComponentDefinition(
        name="c4",
        html="<div>Hi</div>",
        css=".class { color: red; }",
        js="function f() { return 1; }",
    )
    assert d4._has_css_path is False
    assert d4._has_js_path is False
    assert d4.css_content == ".class { color: red; }"
    assert d4.js_content == "function f() { return 1; }"
    assert d4.html_content == "<div>Hi</div>"


@pytest.mark.parametrize(
    ("overrides", "expected_css_url", "expected_js_url"),
    [
        (
            {
                "css_asset_relative_path": "assets/bundle.css",
                "js_asset_relative_path": "build/main.mjs",
            },
            "assets/bundle.css",
            "build/main.mjs",
        ),
        ({}, "style.css", "main.js"),
    ],
)
def test_asset_url_overrides_and_defaults(
    tmp_path,
    monkeypatch,
    overrides: dict[str, str],
    expected_css_url: str,
    expected_js_url: str,
):
    """Verify overrides take precedence; otherwise default to filenames."""
    caller_dir = tmp_path / "caller"
    caller_file = caller_dir / "fakecaller.py"
    css_file = caller_dir / "style.css"
    js_file = caller_dir / "main.js"
    _mk_file(caller_file)
    _mk_file(css_file)
    _mk_file(js_file)

    from streamlit.components.v2 import component_registry as cr

    monkeypatch.setattr(
        cr, "_get_caller_path", lambda: os.fspath(caller_file), raising=True
    )

    d = BidiComponentDefinition(
        name="c",
        css="./style.css",
        js="./main.js",
        **overrides,
    )
    assert d.css_url == expected_css_url
    assert d.js_url == expected_js_url


@pytest.mark.parametrize(
    ("css_input", "js_input", "expected_css_url", "expected_js_url"),
    [
        (
            "build/static/css/main.css",
            "build/static/js/main.js",
            "build/static/css/main.css",
            "build/static/js/main.js",
        ),
        (
            "styles/bundle.css",
            "main.js",
            "styles/bundle.css",
            "main.js",
        ),
    ],
)
def test_default_asset_url_preserves_subpath(
    tmp_path,
    monkeypatch,
    css_input: str,
    js_input: str,
    expected_css_url: str,
    expected_js_url: str,
):
    """Preserve subpaths in defaults and keep simple filenames unchanged."""
    caller_dir = tmp_path / "caller"
    caller_file = caller_dir / "fakecaller.py"
    css_file = caller_dir / css_input
    js_file = caller_dir / js_input
    _mk_file(caller_file)
    _mk_file(css_file)
    _mk_file(js_file)

    from streamlit.components.v2 import component_registry as cr

    monkeypatch.setattr(
        cr, "_get_caller_path", lambda: os.fspath(caller_file), raising=True
    )

    d = BidiComponentDefinition(name="c", css=css_input, js=js_input)
    assert d.css_url == expected_css_url
    assert d.js_url == expected_js_url


def test_register_components_respects_asset_overrides(tmp_path):
    """Ensure registry preserves asset URL overrides on registration."""
    css_path = _mk_file(tmp_path / "c" / "style.css")
    js_path = _mk_file(tmp_path / "c" / "main.js")

    reg = BidiComponentRegistry()
    reg.register_components_from_definitions(
        {
            "comp": {
                "name": "comp",
                "html": None,
                "css": css_path,
                "js": js_path,
                "css_asset_relative_path": "assets/styles.css",
                "js_asset_relative_path": "build/app.js",
            }
        }
    )

    d = reg.get("comp")
    assert d is not None
    assert d.css_url == "assets/styles.css"
    assert d.js_url == "build/app.js"


def test_update_component_merge_enforcement():
    """Preserve missing fields and enforce stored name to the registry key."""
    reg = BidiComponentRegistry()

    # Initial inline definition
    d0 = BidiComponentDefinition(name="comp", html=None, css="orig-css", js="orig-js")
    reg.register(d0)

    # Attempt to update only js and css override
    d1 = BidiComponentDefinition(
        name="comp",
        html=None,
        css="new-css",
        js="new-js",
    )

    reg.update_component(d1)

    d = reg.get("comp")
    assert d is not None
    assert d.name == "comp"
    assert d.html_content is None
    # css and js are updated
    assert d.css_content == "new-css"
    assert d.js_content == "new-js"


def test_update_component_replaces_definition():
    """update_component should replace the stored definition by name."""
    reg = BidiComponentRegistry()

    # Initial inline definition
    d0 = BidiComponentDefinition(name="comp", html=None, css="orig-css", js="orig-js")
    reg.register(d0)

    # New fully-validated definition (simulating resolver output)
    d1 = BidiComponentDefinition(
        name="comp",
        html="<div></div>",
        css="new-css",
        js="new-js",
        css_asset_relative_path="x.css",
    )

    reg.update_component(d1)

    d = reg.get("comp")
    assert d is not None
    assert d.name == "comp"
    assert d.html_content == "<div></div>"
    assert d.css_content == "new-css"
    assert d.js_content == "new-js"
    assert d.css_asset_relative_path == "x.css"


def test_update_component_can_clear_fields_via_none() -> None:
    """Passing None clears fields; registry does not perform implicit merging."""
    reg = BidiComponentRegistry()

    d0 = BidiComponentDefinition(
        name="comp",
        html="<div>keep?</div>",
        css="inline-css",
        js="inline-js",
    )
    reg.register(d0)

    # Provide a definition that clears css/js and html explicitly via None
    d1 = BidiComponentDefinition(name="comp", html=None, css=None, js=None)
    reg.update_component(d1)

    d = reg.get("comp")
    assert d is not None
    assert d.html_content is None
    assert d.css_content is None
    assert d.js_content is None


def test_update_component_raises_for_unregistered_definition() -> None:
    """Raise when attempting to update a component that is not registered."""
    reg = BidiComponentRegistry()

    d = BidiComponentDefinition(name="unknown", html=None, css=None, js=None)

    with pytest.raises(
        StreamlitComponentRegistryError,
        match=r"^Cannot update unregistered component: unknown$",
    ):
        reg.update_component(d)
