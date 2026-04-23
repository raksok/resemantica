from __future__ import annotations

from xml.etree import ElementTree as ET

from resemantica.epub.placeholders import build_placeholder_map, restore_from_placeholders


def test_nested_placeholder_map_has_parent_and_closing_order() -> None:
    block = ET.fromstring(
        "<p>你<em>真的</em>以为<b class=\"emphasis\"><i>青云门</i></b>会放过你吗？</p>"
    )
    extracted, entries, _warnings = build_placeholder_map("ch003_blk001", block)

    assert "⟦EM_1⟧真的⟦/EM_1⟧" in extracted
    assert "⟦B_1⟧⟦I_1⟧青云门⟦/I_1⟧⟦/B_1⟧" in extracted

    by_placeholder = {entry.placeholder: entry for entry in entries}
    assert by_placeholder["⟦I_1⟧"].parent_placeholder == "⟦B_1⟧"
    assert by_placeholder["⟦B_1⟧"].closing_order == ["⟦I_1⟧", "⟦B_1⟧"]
    assert by_placeholder["⟦I_1⟧"].closing_order is None


def test_placeholder_restoration_is_reversible() -> None:
    block = ET.fromstring("<p>开始<b class=\"x\"><i>文本</i></b>结束</p>")
    extracted, entries, _warnings = build_placeholder_map("ch001_blk001", block)

    restored, restore_warnings = restore_from_placeholders(extracted, entries)
    assert not restore_warnings
    assert restored == "开始<b class=\"x\"><i>文本</i></b>结束"


def test_restoration_warns_and_recovers_reordered_closings() -> None:
    block = ET.fromstring("<p><b><i>词</i></b></p>")
    _extracted, entries, _warnings = build_placeholder_map("ch001_blk001", block)
    reordered = "⟦B_1⟧⟦I_1⟧word⟦/B_1⟧⟦/I_1⟧"

    restored, restore_warnings = restore_from_placeholders(reordered, entries)

    assert "</i></b>" in restored
    assert any("order mismatch" in warning for warning in restore_warnings)


def test_deep_nesting_flattens_after_depth_three() -> None:
    block = ET.fromstring("<p><b><i><span><u>深层</u></span></i></b></p>")
    extracted, entries, _warnings = build_placeholder_map("ch001_blk001", block)

    assert "⟦U_1⟧" not in extracted
    by_placeholder = {entry.placeholder: entry for entry in entries}
    assert by_placeholder["⟦U_1⟧"].emitted is False
    assert "⟦SPAN_1⟧" in extracted

