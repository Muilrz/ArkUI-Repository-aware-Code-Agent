"""Source-reviewed expectations, frozen before the first P2-G query.

External revision: 0096f5bd943ed1f7fa56883aed0e2379f13c2885.
These are annotations, not copied target implementation or graph-derived data.
"""

from pathlib import Path

from tests.fixtures.framework_repository import ROOT, write_repository


REAL_CHECKS = (
    ("button/button_pattern.h", 61, "CreateLayoutAlgorithm() override"),
    ("button/button_pattern.h", 63, "MakeRefPtr<ButtonLayoutAlgorithm>()"),
    ("button/button_layout_algorithm.h", 32, "void Measure(LayoutWrapper* layoutWrapper) override;"),
    ("button/button_layout_algorithm.cpp", 37, "ButtonLayoutAlgorithm::Measure("),
    ("button/button_layout_algorithm.cpp", 44, "DynamicCast<ButtonLayoutProperty>"),
    ("text/text_pattern.cpp", 9080, "TextPattern::CreateLayoutAlgorithm()"),
    ("text/text_pattern.cpp", 9087, "MakeRefPtr<TextLayoutAlgorithm>(spans_"),
    ("text/text_layout_algorithm.h", 73, "MeasureContent("),
    ("text/text_layout_algorithm.cpp", 164, "TextLayoutAlgorithm::MeasureContent("),
    ("text/text_layout_algorithm.cpp", 171, "DynamicCast<TextLayoutProperty>"),
    ("menu/menu_pattern.cpp", 1447, "MenuPattern::CreateLayoutAlgorithm()"),
    ("menu/menu_pattern.cpp", 1452, "MakeRefPtr<MultiMenuLayoutAlgorithm>()"),
    ("menu/menu_pattern.cpp", 1455, "MakeRefPtr<SubMenuLayoutAlgorithm>()"),
    ("menu/menu_pattern.cpp", 1457, "MakeRefPtr<MenuLayoutAlgorithm>(targetId_"),
    ("menu/menu_layout_algorithm.h", 108, "void Measure(LayoutWrapper* layoutWrapper) override;"),
    ("menu/menu_layout_algorithm.h", 110, "void Layout(LayoutWrapper* layoutWrapper) override;"),
    ("menu/menu_layout_algorithm.cpp", 901, "MenuLayoutAlgorithm::Measure("),
    ("menu/menu_layout_algorithm.cpp", 910, "DynamicCast<MenuLayoutProperty>"),
    ("menu/menu_layout_algorithm.cpp", 2105, "MenuLayoutAlgorithm::Layout("),
    ("menu/menu_layout_algorithm.cpp", 2120, "DynamicCast<MenuLayoutProperty>"),
)

REAL_EXPECTED = {
    "Button": ("incomplete", ("pattern", "factory", "algorithm", "measure", "layout_property"),
               ("missing_layout_binding",)),
    "Text": ("incomplete", ("pattern", "factory"), ("unsupported_factory_body",)),
    "Menu": ("ambiguous", ("pattern", "factory"), ("ambiguous_algorithm_identity", "missing_create_binding")),
}
MENU_CANDIDATES = ("MenuLayoutAlgorithm", "MultiMenuLayoutAlgorithm", "SubMenuLayoutAlgorithm")


def write_layout_repository(root: Path) -> None:
    """Original executable C++ with separate operation definitions and references."""
    write_repository(root)
    for name in ("Button", "Text", "Menu"):
        slug = name.lower()
        directory = root / ROOT / slug
        pattern = directory / f"{slug}_pattern.h"
        pattern.write_text(
            f'#pragma once\n#include "{slug}_layout_algorithm.h"\n'
            f'namespace OHOS::Ace::NG {{\nclass {name}Pattern : public Referenced {{\npublic:\n'
            f'    RefPtr<LayoutAlgorithm> CreateLayoutAlgorithm()\n    {{\n'
            f'        return MakeRefPtr<{name}LayoutAlgorithm>();\n    }}\n}};\n}}\n', encoding="utf-8")
        header = directory / f"{slug}_layout_algorithm.h"
        header.write_text(
            f'#pragma once\n#include "{slug}_layout_property.h"\n'
            f'namespace OHOS::Ace::NG {{\nclass {name}LayoutAlgorithm : public LayoutAlgorithm {{\npublic:\n'
            '    void Measure(LayoutWrapper* layoutWrapper) override;\n'
            '    void Layout(LayoutWrapper* layoutWrapper) override;\n};\n}\n', encoding="utf-8")
        (directory / f"{slug}_layout_algorithm.cpp").write_text(
            f'#include "{slug}_layout_algorithm.h"\nnamespace OHOS::Ace::NG {{\n'
            f'void {name}LayoutAlgorithm::Measure(LayoutWrapper* layoutWrapper)\n{{\n'
            f'    auto property = DynamicCast<{name}LayoutProperty>(layoutWrapper->GetLayoutProperty());\n'
            '    property->UpdateFontWeight(1);\n}\n'
            f'void {name}LayoutAlgorithm::Layout(LayoutWrapper* layoutWrapper)\n{{\n'
            f'    auto property = DynamicCast<{name}LayoutProperty>(layoutWrapper->GetLayoutProperty());\n'
            '    property->UpdateFontWeight(2);\n}\n}\n', encoding="utf-8")
    support = root / "support.h"
    support.write_text(support.read_text().replace(
        "struct LayoutWrapper {};", "class LayoutProperty;\nstruct LayoutWrapper { LayoutProperty* GetLayoutProperty(); };\n"
        "template<class T> T* DynamicCast(LayoutProperty* p) { return static_cast<T*>(p); }"), encoding="utf-8")
