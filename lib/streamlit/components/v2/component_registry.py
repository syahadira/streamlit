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

import inspect
import os
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from streamlit.components.v2.component_path_utils import ComponentPathUtils
from streamlit.errors import StreamlitComponentRegistryError
from streamlit.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import MutableMapping
    from types import FrameType


_LOGGER: Final = get_logger(__name__)


def _get_caller_path() -> str:
    """Return the absolute filesystem path of the external caller's file.

    The helper walks back the Python stack to find the first frame that does
    not originate from this module and returns its file path. This is used to
    resolve relative paths passed by callers against the location of their
    source file.

    Returns
    -------
    str
        Absolute path to the caller's source file.

    Raises
    ------
    RuntimeError
        If the current frame or caller frame cannot be determined.
    """
    # Get our stack frame.
    current_frame: FrameType | None = inspect.currentframe()
    if current_frame is None:
        raise RuntimeError("Unable to inspect current frame")
    # Get the stack frame of our calling function.
    caller_frame = current_frame.f_back
    # The caller of this function might itself be a helper function.
    # We want to find the actual user code that's calling.
    while caller_frame is not None:
        module = inspect.getmodule(caller_frame)
        if module is not None and module.__name__ == __name__:
            # Still in our module, go up one more level
            caller_frame = caller_frame.f_back
        else:
            break

    if caller_frame is None:
        raise RuntimeError("Unable to find caller frame")
    file_path = inspect.getfile(caller_frame)
    return file_path


@dataclass(frozen=True)
class BidiComponentDefinition:
    """Definition of a bidirectional component V2.

    The definition holds inline content or file references for HTML, CSS, and
    JavaScript, plus metadata used by the runtime to serve assets. When CSS/JS
    are provided as file paths, their asset-dir-relative URLs are exposed via
    ``css_url`` and ``js_url`` (or can be overridden with
    ``css_asset_relative_path``/``js_asset_relative_path``).

    Parameters
    ----------
    name : str
        A short, descriptive name for the component.
    html : str or None, optional
        HTML content as a string.
    css : str or None, optional
        Inline CSS content or an absolute/relative path to a ``.css`` file.
        Relative paths are resolved against the external caller's file.
    js : str or None, optional
        Inline JavaScript content or an absolute/relative path to a ``.js`` file.
        Relative paths are resolved against the external caller's file.
    css_asset_relative_path : str or None, optional
        Asset-dir-relative URL path to use when serving the CSS file. If not
        provided, the filename from ``css`` is used when ``css`` is file-backed.
    js_asset_relative_path : str or None, optional
        Asset-dir-relative URL path to use when serving the JS file. If not
        provided, the filename from ``js`` is used when ``js`` is file-backed.
    """

    name: str
    html: str | None = None
    css: str | None = None
    js: str | None = None
    # Store processed content and metadata
    _has_css_path: bool = field(default=False, init=False, repr=False)
    _has_js_path: bool = field(default=False, init=False, repr=False)
    _source_paths: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    # Asset-dir-relative paths used for frontend loading. These represent the
    # URL path segment under the component's declared asset_dir (e.g. "build/index.js")
    # and are independent of the on-disk absolute file path stored in css/js.
    css_asset_relative_path: str | None = None
    js_asset_relative_path: str | None = None

    def __post_init__(self) -> None:
        # Keep track of source paths for content loaded from files
        source_paths = {}

        # Store CSS and JS paths if provided
        is_css_path, css_path = self._is_file_path(self.css)
        is_js_path, js_path = self._is_file_path(self.js)

        if css_path:
            source_paths["css"] = os.path.dirname(css_path)
        if js_path:
            source_paths["js"] = os.path.dirname(js_path)

        object.__setattr__(self, "_has_css_path", is_css_path)
        object.__setattr__(self, "_has_js_path", is_js_path)
        object.__setattr__(self, "_source_paths", source_paths)

        # Allow empty definitions to support manifest-registered components that
        # declare only an asset sandbox (asset_dir) without inline or file-backed
        # entry content. Runtime API calls can later provide js/css/html.

    def _is_file_path(self, content: str | None) -> tuple[bool, str | None]:
        """Determine whether ``content`` is a filesystem path and resolve it.

        For string inputs that look like paths (contain path separators or start
        with a path prefix and do not resemble inline HTML/CSS/JS), this resolves
        relative paths against the external caller's file and verifies existence.

        Parameters
        ----------
        content : str or None
            The potential inline content or path.

        Returns
        -------
        tuple[bool, str | None]
            ``(is_path, abs_path)`` where ``is_path`` indicates whether the input
            was treated as a path and ``abs_path`` is the resolved absolute path
            if a path, otherwise ``None``.

        Raises
        ------
        ValueError
            If ``content`` is treated as a path but the file does not exist.
        RuntimeError
            If the caller frame cannot be determined for relative path resolution.
        """
        if content is None:
            return False, None

        # Determine if it's a file path or inline content for strings
        if isinstance(content, str):
            stripped = content.strip()
            is_likely_path = not ComponentPathUtils.looks_like_inline_content(stripped)

            if is_likely_path:
                try:
                    if os.path.isabs(content):
                        abs_path = content
                    else:
                        # Validate relative path security (reject traversal),
                        # then resolve relative to the caller's file
                        try:
                            ComponentPathUtils.validate_path_security(content)
                        except StreamlitComponentRegistryError:
                            # Preserve existing external API surface
                            raise ValueError(
                                "Parent directory traversal ('..') is not allowed in component asset paths"
                            )

                        caller_dir = os.path.dirname(_get_caller_path())
                        abs_path = os.path.abspath(os.path.join(caller_dir, content))

                    if not os.path.exists(abs_path):
                        raise ValueError(f"File does not exist: {abs_path}")  # noqa: TRY301

                    return True, abs_path
                except Exception:
                    _LOGGER.exception("Failed to process file path %s", content)
                    raise

        # If we get here, it's content, not a path
        return False, None

    @property
    def css_url(self) -> str | None:
        """Return the asset-dir-relative URL path for CSS when file-backed.

        When present, servers construct
        ``/bidi-components/<component>/<css_url>`` using this value. If
        ``css_asset_relative_path`` is specified, it takes precedence over the
        filename derived from ``css``.
        """
        return self._derive_asset_url(
            has_path=self._has_css_path,
            value=self.css,
            override=self.css_asset_relative_path,
        )

    @property
    def js_url(self) -> str | None:
        """Return the asset-dir-relative URL path for JS when file-backed.

        When present, servers construct
        ``/bidi-components/<component>/<js_url>`` using this value. If
        ``js_asset_relative_path`` is specified, it takes precedence over the
        filename derived from ``js``.
        """
        return self._derive_asset_url(
            has_path=self._has_js_path,
            value=self.js,
            override=self.js_asset_relative_path,
        )

    def _derive_asset_url(
        self, *, has_path: bool, value: str | None, override: str | None
    ) -> str | None:
        """Compute asset-dir-relative URL for a file-backed asset.

        Parameters
        ----------
        has_path
            Whether the value refers to a file path.
        value
            The css/js field value (inline string or path).
        override
            Optional explicit asset-dir-relative override.

        Returns
        -------
        str or None
            The derived URL path or ``None`` if not file-backed.
        """
        if not has_path:
            return None
        # Prefer explicit URL override if provided (relative to asset_dir)
        if override:
            return override
        # Fallback: preserve relative subpath if the provided path is relative;
        # otherwise default to the basename for absolute paths. Normalize
        # leading "./" to avoid awkward prefixes in URLs.
        path_str = str(value)
        if os.path.isabs(path_str):
            return os.path.basename(path_str)
        norm = path_str.replace("\\", "/").removeprefix("./")
        # If there's a subpath remaining, preserve it; otherwise use basename
        return norm if "/" in norm else os.path.basename(norm)

    @property
    def css_content(self) -> str | None:
        """Return inline CSS content or ``None`` if file-backed or missing."""
        if self._has_css_path or self.css is None:
            return None
        # Return as string if it's not a path
        return str(self.css)

    @property
    def js_content(self) -> str | None:
        """Return inline JavaScript content or ``None`` if file-backed or missing."""
        if self._has_js_path or self.js is None:
            return None
        # Return as string if it's not a path
        return str(self.js)

    @property
    def html_content(self) -> str | None:
        """Return inline HTML content or ``None`` if not provided."""
        return self.html

    @property
    def source_paths(self) -> dict[str, str]:
        """Return source directories for file-backed CSS/JS content.

        The returned mapping contains keys like ``"js"`` and ``"css"`` with the
        directory path from which each was loaded.
        """
        return self._source_paths


class BidiComponentRegistry:
    """Registry for bidirectional components V2.

    The registry stores and updates :class:`BidiComponentDefinition` instances in
    a thread-safe mapping guarded by a lock.
    """

    def __init__(self) -> None:
        """Initialize the component registry with an empty, thread-safe store."""
        self._components: MutableMapping[str, BidiComponentDefinition] = {}
        self._lock = threading.Lock()

    def register_components_from_definitions(
        self, component_definitions: dict[str, dict[str, Any]]
    ) -> None:
        """Register components from processed definition data.

        Parameters
        ----------
        component_definitions : dict[str, dict[str, Any]]
            Mapping from component identifier to definition data.
        """
        with self._lock:
            # Register all component definitions
            for comp_name, comp_def_data in component_definitions.items():
                # Validate required keys and gracefully handle optional ones.
                name = comp_def_data.get("name")
                if not name:
                    raise ValueError(
                        f"Component definition for key '{comp_name}' is missing required 'name' field"
                    )

                definition = BidiComponentDefinition(
                    name=name,
                    js=comp_def_data.get("js"),
                    css=comp_def_data.get("css"),
                    html=comp_def_data.get("html"),
                    css_asset_relative_path=comp_def_data.get(
                        "css_asset_relative_path"
                    ),
                    js_asset_relative_path=comp_def_data.get("js_asset_relative_path"),
                )
                self._components[comp_name] = definition
                _LOGGER.debug(
                    "Registered component %s from processed definitions", comp_name
                )

    def register(self, definition: BidiComponentDefinition) -> None:
        """Register or overwrite a component definition by name.

        If a component with the same name already exists and differs, it is
        overwritten and a warning is logged to indicate potential conflicts
        when multiple modules register the same name.

        Parameters
        ----------
        definition : BidiComponentDefinition
            The component definition to store.
        """

        # Register the definition
        with self._lock:
            name = definition.name
            if name in self._components:
                existing_definition = self._components[name]
                if existing_definition != definition:
                    _LOGGER.warning(
                        "Component %s is already registered. Overwriting "
                        "previous definition. This may lead to unexpected behavior "
                        "if different modules register the same component name with "
                        "different definitions.",
                        name,
                    )
            self._components[name] = definition
            _LOGGER.debug("Registered component %s", name)

    def get(self, name: str) -> BidiComponentDefinition | None:
        """Return a component definition by name, or ``None`` if not found.

        Parameters
        ----------
        name : str
            Component name to retrieve.

        Returns
        -------
        BidiComponentDefinition or None
            The component definition if present, otherwise ``None``.
        """
        with self._lock:
            return self._components.get(name)

    def unregister(self, name: str) -> None:
        """Remove a component definition from the registry.

        Primarily useful for tests and dynamic scenarios.

        Parameters
        ----------
        name : str
            Component name to unregister.
        """
        with self._lock:
            if name in self._components:
                del self._components[name]
                _LOGGER.debug("Unregistered component %s", name)

    def clear(self) -> None:
        """Clear all component definitions from the registry."""
        with self._lock:
            self._components.clear()
            _LOGGER.debug("Cleared all components from registry")

    def update_component(self, definition: BidiComponentDefinition) -> None:
        """Update (replace) a stored component definition by name.

        This method is the singular code path to update existing definitions in
        the registry. Callers must supply a fully validated
        :class:`BidiComponentDefinition` (e.g., from
        ``build_definition_with_validation``). The registry replaces the stored
        definition under ``definition.name`` in a thread-safe manner. If no
        component with ``definition.name`` is currently registered, an
        exception is raised and no changes are made.

        Parameters
        ----------
        definition : BidiComponentDefinition
            The fully-resolved component definition to store.
        """
        with self._lock:
            name = definition.name
            if name not in self._components:
                raise StreamlitComponentRegistryError(
                    f"Cannot update unregistered component: {name}"
                )
            self._components[name] = definition
            _LOGGER.debug("Updated component definition for %s", name)
