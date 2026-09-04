"""Source-reviewed P2-F expectations, fixed before executing any trace query.

Native entries call the FrameNode* overload, which uses ACE_UPDATE_NODE_*
and is outside P2-D v1. The stack overload has an UPDATE_PROPERTY binding but
macro-generated state/accessors are outside the explicit-field reader rule.
These fragments must never be joined by matching SetFontWeight names.
"""

from dataclasses import dataclass
from pathlib import Path

from tests.fixtures.framework_repository import MACROS, ROOT, write_repository


@dataclass(frozen=True)
class PropertyCase:
    component: str
    entry_file: str
    entry: str
    entry_line: int
    call_line: int
    native_line: int
    stack_line: int
    property_line: int
    consumer_file: str
    consumer_line: int


REAL_CASES = (
    PropertyCase("Button", f"{ROOT}/button/bridge/button_dynamic_modifier.cpp",
                 "SetButtonFontWeight", 317, 322, 885, 39, 97,
                 f"{ROOT}/button/button_pattern.cpp", 437),
    PropertyCase("Text", "frameworks/core/interfaces/native/node/node_text_modifier.cpp",
                 "SetFontWeightStr", 627, 631, 250, 286, 150,
                 f"{ROOT}/text/text_layout_property.h", 298),
    PropertyCase("Menu", f"{ROOT}/menu/bridge/menu/menu_dynamic_modifier.cpp",
                 "SetMenuFontWithResource", 177, 191, 505, 315, 139,
                 f"{ROOT}/menu/menu_pattern.cpp", 206),
)

NATIVE_EXPECTED = ("entry", "model")
STACK_EXPECTED = ("model", "layout_property")
NATIVE_GAPS = ("missing_update_binding",)
STACK_GAPS = ("missing_entry_call", "missing_property_writer")


def write_property_repository(root: Path) -> None:
    """Original executable C++; Menu exercises PaintProperty independently."""
    write_repository(root)
    path = root / "support.h"
    text = path.read_text(encoding="utf-8")
    text = text.replace("T* GetLayoutPropertyPtr() { return nullptr; }",
                        "T* GetLayoutPropertyPtr() { return nullptr; } "
                        "template<class T> T* GetPaintPropertyPtr() { return nullptr; }")
    path.write_text(text, encoding="utf-8")
    path = root / MACROS
    text = path.read_text(encoding="utf-8")
    paint = text[text.index("#define ACE_UPDATE_LAYOUT_PROPERTY"):].replace("LAYOUT", "PAINT").replace("Layout", "Paint")
    path.write_text(text + paint, encoding="utf-8")
    for name in ("Button", "Text", "Menu"):
        slug = name.lower()
        kind = "Paint" if name == "Menu" else "Layout"
        filename = f"{slug}_{kind.lower()}_property.h"
        directory = root / ROOT / slug
        (directory / filename).write_text(
            '#pragma once\n#include "support.h"\nnamespace OHOS::Ace::NG {\n' +
            f'class {name}{kind}Property {{\npublic:\n'
            '    int weight = 0;\n'
            '    void UpdateFontWeight(int value) { weight = value; }\n'
            '    int ReadWeight() const { return weight; }\n};\n}\n', encoding="utf-8")
        (directory / f"{slug}_model_ng.h").write_text(
            f'#pragma once\n#include "{filename}"\n#include "{MACROS}"\nnamespace OHOS::Ace::NG {{\n' +
            f'class {name}ModelNG {{\npublic:\n'
            f'    void SetFontWeight(int value) {{ ACE_UPDATE_{kind.upper()}_PROPERTY({name}{kind}Property, FontWeight, value); }}\n'
            '    void SetFontWeight(double value) {}\n};\n}\n', encoding="utf-8")
        (directory / "property_entry.cpp").write_text(
            f'#include "{slug}_model_ng.h"\nnamespace OHOS::Ace::NG {{\n'
            f'void Apply{name}Weight({name}ModelNG& model, int value) {{ model.SetFontWeight(value); }}\n'
            f'int Consume{name}Weight(const {name}{kind}Property& property) {{ return property.ReadWeight(); }}\n}}\n',
            encoding="utf-8")
