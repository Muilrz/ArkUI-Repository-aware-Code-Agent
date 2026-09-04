"""Creation expectations frozen from source review BEFORE running the query.

Ace Engine 0096f5bd943ed1f7fa56883aed0e2379f13c2885. Lines are review
anchors, not identities. Runtime symbol selection is still performed by P1.
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CreationCase:
    component: str
    entry_file: str
    entry_name: str
    entry_line: int
    model_line: int
    frame_method: str
    pattern: str
    expected_status: str
    source_evidence: tuple[tuple[str, int, str], ...]
    entry_namespace: str = "OHOS::Ace::NG"


ROOT = "frameworks/core/components_ng/pattern"
FRAME_HEADER = "frameworks/core/components_ng/base/frame_node.h"
CASES = (
    CreationCase("button", f"{ROOT}/button/bridge/button_dynamic_modifier.cpp",
                 "CreateButtonFrameNodeForCustom", 970, 659, "CreateFrameNode", "ButtonPattern", "complete", (
        (f"{ROOT}/button/bridge/button_dynamic_modifier.cpp", 972,
         "auto frameNode = ButtonModelNG::CreateFrameNode(nodeId);"),
        (f"{ROOT}/button/button_model_ng.cpp", 661,
         "auto frameNode = FrameNode::CreateFrameNode(BUTTON_ETS_TAG, nodeId, AceType::MakeRefPtr<ButtonPattern>());"),
    )),
    CreationCase("text", "frameworks/core/interfaces/native/node/view_model.cpp",
                 "createTextNode", 113, 90, "CreateFrameNode", "TextPattern", "complete", (
        ("frameworks/core/interfaces/native/node/view_model.cpp", 115,
         'auto frameNode = TextModelNG::CreateFrameNode(nodeId, u"");'),
        (f"{ROOT}/text/text_model_ng.cpp", 92,
         "auto frameNode = FrameNode::CreateFrameNode(V2::TEXT_ETS_TAG, nodeId, AceType::MakeRefPtr<TextPattern>());"),
    ), entry_namespace="OHOS::Ace::NG::ViewModel"),
    CreationCase("menu", f"{ROOT}/menu/bridge/menu/menu_dynamic_modifier.cpp",
                 "CreateMenuFrameNode", 445, 25, "GetOrCreateFrameNode", "InnerMenuPattern", "incomplete", (
        (f"{ROOT}/menu/bridge/menu/menu_dynamic_modifier.cpp", 447,
         "auto node = MenuModelNG::CreateFrameNode(nodeId);"),
        (f"{ROOT}/menu/menu_model_ng.cpp", 29,
         "[]() { return AceType::MakeRefPtr<InnerMenuPattern>(-1, MENU_ETS_TAG, MenuType::MULTI_MENU); };"),
        (f"{ROOT}/menu/menu_model_ng.cpp", 30,
         "return FrameNode::GetOrCreateFrameNode(MENU_ETS_TAG, nodeId, patternCreator);"),
    )),
)
# Menu intentionally stays incomplete: P2-C does not classify InnerMenuPattern,
# and P1 does not expose the callback-to-pattern argument binding. Do not
# substitute MenuPattern or claim that FrameNode directly calls InnerMenuPattern.


def write_creation_repository(root: Path) -> tuple[CreationCase, ...]:
    from tests.fixtures.framework_repository import FACTORY, write_repository

    write_repository(root)

    def write(path: str, text: str) -> None:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    write("support.h", f'#pragma once\n#include "{FACTORY}"\n' +
          "namespace OHOS::Ace { using AceType = Referenced; }\n"
          "namespace OHOS::Ace::NG { class Pattern : public Referenced {}; }\n")
    write(FRAME_HEADER, '#pragma once\n#include "support.h"\n' + """namespace OHOS::Ace::NG {
class FrameNode {
public:
    static RefPtr<FrameNode> CreateFrameNode(const char* tag, int nodeId, const RefPtr<Pattern>& pattern)
    {
        return new FrameNode();
    }
};
}
""")
    cases = []
    for component in ("button", "text", "menu"):
        title = component.title()
        write(f"{ROOT}/{component}/{component}_pattern.h", '#pragma once\n#include "support.h"\n' +
              f"namespace OHOS::Ace::NG {{ class {title}Pattern : public Pattern {{}}; }}\n")
        write(f"{ROOT}/{component}/{component}_model_ng.h", f'#pragma once\n#include "{FRAME_HEADER}"\n' +
              f'#include "{component}_pattern.h"\nnamespace OHOS::Ace::NG {{\n' +
              f'constexpr const char* {title}Tag = "{title}";\nclass {title}ModelNG {{\npublic:\n' +
              "    static RefPtr<FrameNode> CreateFrameNode(int nodeId)\n    {\n" +
              f"        auto frameNode = FrameNode::CreateFrameNode({title}Tag, nodeId, AceType::MakeRefPtr<{title}Pattern>());\n" +
              "        return frameNode;\n    }\n};\n}\n")
        entry = f"entries/{component}.cpp"
        write(entry, f'#include "{ROOT}/{component}/{component}_model_ng.h"\n' +
              f"namespace OHOS::Ace::NG {{\nvoid* Build{title}(int nodeId)\n{{\n"
              f"    return {title}ModelNG::CreateFrameNode(nodeId);\n}}\n}}\n")
        cases.append(CreationCase(component, entry, "Build" + title, 3, 8, "CreateFrameNode",
                                  title + "Pattern", "complete", ()))
    return tuple(cases)
