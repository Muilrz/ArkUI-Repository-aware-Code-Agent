"""P2-H source expectations frozen before querying, revision 0096f5bd943ed1f7fa56883aed0e2379f13c2885.

Only annotations of the external sources; synthetic C++ below is original.
"""

from pathlib import Path

ROOT = "frameworks/core/components_ng"
MANAGER_H = f"{ROOT}/pattern/overlay/overlay_manager.h"
MANAGER_CPP = f"{ROOT}/pattern/overlay/overlay_manager.cpp"
FRAME_H = f"{ROOT}/base/frame_node.h"
PATTERN_H = f"{ROOT}/pattern/menu/menu_pattern.h"
ANIMATION_H = f"{ROOT}/render/animation_utils.h"
ENTRY_CPP = f"{ROOT}/base/view_abstract.cpp"
MENU_CPP = f"{ROOT}/pattern/menu/menu_pattern.cpp"
MENU_MANAGER = f"{ROOT}/pattern/menu/menu_manager.cpp"
NS = "OHOS::Ace::NG::"

REAL_CHECKS = (
    (MANAGER_H, 198, "void ShowMenu(int32_t targetId,"),
    (MANAGER_H, 199, "void HideMenu(const RefPtr<FrameNode>& menu,"),
    (ENTRY_CPP, 5403, "void ViewAbstract::BindMenuWithItems("),
    (ENTRY_CPP, 5446, "overlayManager->ShowMenu(targetNode->GetId(), offset, menuNode);"),
    (ENTRY_CPP, 5385, "int32_t ViewAbstract::CloseMenu("),
    (ENTRY_CPP, 5399, "overlayManager->HideMenu(menuWrapperNode, customNode->GetId(), false, HideMenuType::CLOSE_MENU);"),
    (MENU_CPP, 1070, "void MenuPattern::HideMenu(bool isMenuOnTouch,"),
    (MENU_CPP, 1113, "overlayManager->HideMenu(wrapper, targetId_, isMenuOnTouch, reason);"),
    (MANAGER_CPP, 1623, "void OverlayManager::ShowMenu("),
    (MANAGER_CPP, 1630, "modifier->showMenu("),
    (MANAGER_CPP, 1684, "void OverlayManager::HideMenu("),
    (MANAGER_CPP, 1693, "modifier->hideMenu("),
    # Downstream source observations, NOT fictional CALL edges across modifier dispatch.
    (MENU_MANAGER, 1195, "auto menuWrapperPattern = menu->GetPattern<MenuWrapperPattern>();"),
    (MENU_MANAGER, 1263, "ShowMenuAnimation(menu, overlayManager);"),
    (MENU_MANAGER, 1416, "PopMenuAnimation(menu, overlayManager);"),
    (MENU_MANAGER, 1095, "AnimationUtils::Animate("),
    (MENU_MANAGER, 1137, "void MenuManager::HideAllMenusWithoutAnimation("),
    (MENU_MANAGER, 1154, "overlayManager->RemoveChildWithService(rootNode, menuNode);"),
)
REAL_SHOW = (NS + "ViewAbstract::BindMenuWithItems", NS + "OverlayManager::ShowMenu")
REAL_CLOSE = ((NS + "ViewAbstract::CloseMenu", NS + "OverlayManager::HideMenu"),
              (NS + "MenuPattern::HideMenu", NS + "OverlayManager::HideMenu"))
# Definition anchors were inspected with REAL_CHECKS, before the first query.
# MenuPattern::HideMenu also has a distinct inline overload in the header.
REAL_SEED_DEFINITIONS = {
    REAL_SHOW[0]: (ENTRY_CPP, 5403),
    REAL_CLOSE[0][0]: (ENTRY_CPP, 5385),
    REAL_CLOSE[1][0]: (MENU_CPP, 1070),
}
REAL_STAGES = ("entry", "manager", "operation", "managed_node_type")
REAL_GAPS = ("unsupported_manager_body",)
REAL_ANIMATION = "unresolved"


def write_overlay_repository(root: Path, *, animation: bool = False, multiple_close: bool = False) -> None:
    def write(path: str, content: str) -> None:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    write(FRAME_H, """#pragma once
namespace OHOS::Ace {
template<class T> using RefPtr = T*;
namespace NG {
struct OffsetF {};
enum class HideMenuType { NORMAL };
class FrameNode {
public:
    template<class T> T* GetPattern() { return nullptr; }
};
}
}
""")
    write(PATTERN_H, """#pragma once
namespace OHOS::Ace::NG {
class MenuPattern {
public:
    void OnModifyDone() {}
};
}
""")
    write(ANIMATION_H, """#pragma once
namespace OHOS::Ace {
class AnimationUtils {
public:
    static void Animate(int option, void (*callback)()) { callback(); }
};
}
""")
    write(MANAGER_H, f'#pragma once\n#include "{FRAME_H}"\n' + """#include <cstdint>
namespace OHOS::Ace::NG {
class OverlayManager {
public:
    void ShowMenu(int32_t targetId, const NG::OffsetF& offset, RefPtr<FrameNode> menu = nullptr);
    void HideMenu(const RefPtr<FrameNode>& menu, int32_t targetId, bool isMenuOnTouch = false,
        const HideMenuType& reason = HideMenuType::NORMAL);
};
}
""")
    body = """    CHECK_NULL_VOID(menu);
    auto pattern = menu->GetPattern<MenuPattern>();
    CHECK_NULL_VOID(pattern);
    pattern->OnModifyDone();
"""
    if animation:
        body += "    AnimationUtils::Animate(option, callback);\n"
    write(MANAGER_CPP, f'#include "{MANAGER_H}"\n#include "{PATTERN_H}"\n#include "{ANIMATION_H}"\n' +
          "#define CHECK_NULL_VOID(p) if (!(p)) return\nnamespace OHOS::Ace::NG {\n"
          "int option = 1;\nvoid callback() {}\n"
          "void OverlayManager::ShowMenu(int32_t targetId, const NG::OffsetF& offset, RefPtr<FrameNode> menu)\n{\n" + body + "}\n"
          "void OverlayManager::HideMenu(const RefPtr<FrameNode>& menu, int32_t targetId, bool isMenuOnTouch,\n"
          "    const HideMenuType& reason)\n{\n" + body + "}\n}\n")
    entry = (f'#include "{MANAGER_H}"\nnamespace OHOS::Ace::NG {{\n'
             'void Open(OverlayManager& manager, RefPtr<FrameNode> node) { manager.ShowMenu(1, OffsetF(), node); }\n'
             'void Dismiss(OverlayManager& manager, RefPtr<FrameNode> node) { manager.HideMenu(node, 1); }\n')
    if multiple_close:
        entry += ('void Keyboard(OverlayManager& manager, RefPtr<FrameNode> node) { manager.HideMenu(node, 1); }\n'
                  'void Close(OverlayManager& manager, RefPtr<FrameNode> node) { Dismiss(manager, node); Keyboard(manager, node); }\n')
    else:
        entry += 'void Close(OverlayManager& manager, RefPtr<FrameNode> node) { Dismiss(manager, node); }\n'
    write("overlay_entry.cpp", entry + "}\n")
