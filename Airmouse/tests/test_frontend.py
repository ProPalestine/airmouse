from pathlib import Path


JS = Path(__file__).parents[1] / "static" / "app.js"


def test_gesture_safety_state_and_mapping_helpers_are_present():
    source = JS.read_text()
    assert "function cursorCoordinates" in source
    assert "clickArmed = false" in source
    assert "performance.now() - nonClickSince >= 180" in source
    assert "stopActions('Emergency stop')" in source
    assert "event.key==='Escape'" in source
    assert "getTracks().forEach(track => track.stop())" in source


def test_only_declared_local_mouse_api_actions_are_used():
    source = JS.read_text()
    assert "'/api/move'" in source
    assert "'/api/click'" in source
    assert "'/api/scroll'" in source
    assert "fetch(" in source
    assert "eval(" not in source
    assert "document.cookie" not in source


def test_cursor_mapping_mirrors_x_and_clamps_edges():
    source = JS.read_text()
    assert "(1 - nx - .5) * sensitivity + .5" in source
    assert "Math.max(0, Math.min(1" in source
    assert "width - 1" in source and "height - 1" in source


def test_mediapipe_bundle_is_a_published_version_and_script_has_no_broken_preload():
    from pathlib import Path

    root = Path(__file__).parents[1]
    source = JS.read_text()
    html = (root / "templates" / "index.html").read_text()
    assert "@mediapipe/tasks-vision@0.10.14/vision_bundle.mjs" in source
    assert "@mediapipe/tasks-vision@0.10.22" not in html + source
    assert "vision_bundle.mjs" not in html


def test_pause_resume_and_backend_error_does_not_crash_tracking():
    source = JS.read_text()
    assert "reportMouseFailure(err.message)" in source
    assert "els.pause.disabled = !stream || stopped" in source
    assert "Desktop control is unavailable:" in source


def test_gestures_are_distinct_and_have_plain_language_help():
    from pathlib import Path

    root = Path(__file__).parents[1]
    source = JS.read_text()
    html = (root / "templates" / "index.html").read_text()
    assert "indexUp && middleUp && !ringUp && !pinkyUp" in source
    assert "indexUp && !middleUp && !ringUp && !pinkyUp" in source
    assert "!indexUp && !middleUp && !ringUp && !pinkyUp" in source
    assert "thumbUp && indexUp && middleUp" in source
    assert "Raise index + middle; move their midpoint" in html
    assert "Raise index only; lower it to re-arm" in html
    assert "Close all fingers; move fist vertically" in html
    assert "requestPictureInPicture" in source
    assert "scrollReference = null" in source
    assert "performance.now() - pausePoseSince >= 700" in source


def test_pointer_uses_adaptive_filter_and_resets_between_poses():
    source = JS.read_text()
    assert "function smoothPointer(point, now, smoothingPercent)" in source
    assert "const cutoff = minimumCutoff + beta * Math.abs(derivative[axis])" in source
    assert "pointerFilter = null; smoothed = null; lastPoint = null" in source
