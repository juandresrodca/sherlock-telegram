"""Manifest loading, validation and the four detection strategies."""

from __future__ import annotations

import json

import pytest

from sherlock_telegram.core.manifest import (
    ManifestError,
    filter_surfaces,
    load_surfaces,
)
from sherlock_telegram.core.models import Status

from .conftest import make_response


def _write(tmp_path, surfaces):
    path = tmp_path / "surfaces.json"
    path.write_text(json.dumps({"surfaces": surfaces}), encoding="utf-8")
    return path


# --- the shipped manifest --------------------------------------------------


def test_shipped_manifest_loads_and_validates():
    surfaces = load_surfaces()
    assert surfaces
    assert all("{}" in s.url for s in surfaces)


def test_every_enabled_surface_declares_selftest_handles():
    """An enabled surface with no test handles can rot without anyone noticing."""
    missing = [
        s.name
        for s in load_surfaces()
        if s.enabled and not (s.username_claimed and s.username_unclaimed)
    ]
    assert missing == []


def test_every_disabled_surface_explains_itself():
    unexplained = [s.name for s in load_surfaces() if not s.enabled and not s.note]
    assert unexplained == []


# --- validation ------------------------------------------------------------


def test_missing_placeholder_is_rejected(tmp_path):
    path = _write(tmp_path, [{"name": "X", "category": "c", "url": "https://x.com/user", "errorType": "status_code"}])
    with pytest.raises(ManifestError, match="placeholder"):
        load_surfaces(path)


def test_unknown_error_type_is_rejected(tmp_path):
    path = _write(tmp_path, [{"name": "X", "category": "c", "url": "https://x.com/{}", "errorType": "vibes"}])
    with pytest.raises(ManifestError, match="errorType"):
        load_surfaces(path)


def test_message_strategy_requires_a_sentinel(tmp_path):
    path = _write(tmp_path, [{"name": "X", "category": "c", "url": "https://x.com/{}", "errorType": "message"}])
    with pytest.raises(ManifestError, match="errorMsg"):
        load_surfaces(path)


def test_invalid_regex_is_rejected_at_load_time(tmp_path):
    path = _write(
        tmp_path,
        [{"name": "X", "category": "c", "url": "https://x.com/{}", "errorType": "regex", "regexFound": "([unclosed"}],
    )
    with pytest.raises(ManifestError, match="invalid regex"):
        load_surfaces(path)


def test_duplicate_names_are_rejected(tmp_path):
    entry = {"name": "X", "category": "c", "url": "https://x.com/{}", "errorType": "status_code"}
    path = _write(tmp_path, [entry, dict(entry)])
    with pytest.raises(ManifestError, match="duplicate"):
        load_surfaces(path)


def test_missing_file_is_reported_clearly(tmp_path):
    with pytest.raises(ManifestError, match="not found"):
        load_surfaces(tmp_path / "nope.json")


# --- detection strategies --------------------------------------------------


def _surface(tmp_path, **overrides):
    entry = {"name": "X", "category": "c", "url": "https://x.com/{}", "errorType": "status_code"}
    entry.update(overrides)
    return load_surfaces(_write(tmp_path, [entry]))[0]


def test_status_code_strategy(tmp_path):
    surface = _surface(tmp_path, errorType="status_code", errorCode=[404])
    assert surface.evaluate(make_response("", 200)) is Status.FOUND
    assert surface.evaluate(make_response("", 404)) is Status.NOT_FOUND
    assert surface.evaluate(make_response("", 403)) is Status.UNKNOWN


def test_message_strategy_ignores_the_status_line(tmp_path):
    """The t.me case: HTTP 200 either way, sentinel decides."""
    surface = _surface(tmp_path, errorType="message", errorMsg=["No such user"])
    assert surface.evaluate(make_response("welcome home", 200)) is Status.FOUND
    assert surface.evaluate(make_response("No such user here", 200)) is Status.NOT_FOUND


def test_message_strategy_will_not_trust_an_error_body(tmp_path):
    surface = _surface(tmp_path, errorType="message", errorMsg=["No such user"])
    assert surface.evaluate(make_response("blocked", 403)) is Status.UNKNOWN


def test_response_url_strategy(tmp_path):
    surface = _surface(
        tmp_path, errorType="response_url", errorUrl="https://x.com/login", errorCode=[404]
    )
    assert surface.evaluate(make_response("", 200, "https://x.com/alice")) is Status.FOUND
    assert surface.evaluate(make_response("", 200, "https://x.com/login")) is Status.NOT_FOUND
    # A trailing slash must not read as a different destination.
    assert surface.evaluate(make_response("", 200, "https://x.com/login/")) is Status.NOT_FOUND


def test_regex_strategy(tmp_path):
    surface = _surface(tmp_path, errorType="regex", regexFound="author-profile")
    assert surface.evaluate(make_response("<div class=author-profile>", 200)) is Status.FOUND
    assert surface.evaluate(make_response("Client Challenge", 200)) is Status.NOT_FOUND


# --- extras ----------------------------------------------------------------


def test_extract_pulls_declared_capture_groups(tmp_path):
    surface = _surface(tmp_path, extract={"title": r"<h1>(.*?)</h1>"})
    assert surface.extract_attributes(make_response("<h1> Alice </h1>")) == {"title": "Alice"}


def test_username_regex_gates_impossible_handles(tmp_path):
    surface = _surface(tmp_path, usernameRegex="^[a-z]{1,16}$")
    assert surface.accepts("alice")
    assert not surface.accepts("a_very_long_handle_indeed")


def test_url_probe_can_differ_from_the_display_url(tmp_path):
    surface = _surface(tmp_path, urlProbe="https://api.x.com/u/{}")
    assert surface.target("alice") == "https://x.com/alice"
    assert surface.probe("alice") == "https://api.x.com/u/alice"


def test_filtering_is_case_insensitive_and_anded():
    surfaces = load_surfaces()
    assert filter_surfaces(surfaces, categories=["CROSS-PLATFORM"])
    assert all(
        s.category == "cross-platform" for s in filter_surfaces(surfaces, categories=["cross-platform"])
    )
    assert len(filter_surfaces(surfaces, names=["github"])) == 1


def test_disabled_surfaces_are_excluded_by_default():
    surfaces = load_surfaces()
    assert any(not s.enabled for s in surfaces), "fixture expects some disabled entries"
    assert all(s.enabled for s in filter_surfaces(surfaces))
    assert len(filter_surfaces(surfaces, include_disabled=True)) == len(surfaces)
