"""Small reviewed ArkUI catalog, not suffix-based discovery.

Paths and qualified class names inspected at Ace Engine revision
0096f5bd943ed1f7fa56883aed0e2379f13c2885. Other symbols remain unknown.
"""

from arkui_agent.graph.domain import ArkUIRoleMapper, ComponentSpec, RoleRule
from arkui_agent.graph.model import NodeKind
from arkui_agent.repository.model import RepositoryFile


COMPONENTS = (
    ComponentSpec("button", "Button"), ComponentSpec("text", "Text"), ComponentSpec("menu", "Menu"),
)
_ROOT = "frameworks/core/components_ng/pattern"
_BRIDGES = {
    "button": f"{_ROOT}/button/bridge/arkts_native_button_bridge.h",
    "text": "frameworks/bridge/declarative_frontend/engine/jsi/nativeModule/arkts_native_text_bridge.h",
    "menu": f"{_ROOT}/menu/bridge/menu/arkts_native_menu_bridge.h",
}


def _rules() -> tuple[RoleRule, ...]:
    rules = []
    for component in COMPONENTS:
        for role, suffix, basename in (
            (NodeKind.MODEL, "ModelNG", "model_ng"),
            (NodeKind.PATTERN, "Pattern", "pattern"),
            (NodeKind.LAYOUT_PROPERTY, "LayoutProperty", "layout_property"),
            (NodeKind.LAYOUT_ALGORITHM, "LayoutAlgorithm", "layout_algorithm"),
            (NodeKind.BRIDGE, "Bridge", "bridge"),
        ):
            path = (_BRIDGES[component.key] if role == NodeKind.BRIDGE
                    else f"{_ROOT}/{component.key}/{component.key}_{basename}.h")
            rules.append(RoleRule(
                f"{component.key}.{role.value}", role,
                f"OHOS::Ace::NG::{component.display_name}{suffix}",
                RepositoryFile.from_path(path), component.key,
            ))
    rules.extend((
        RoleRule("menu.paint_property", NodeKind.PAINT_PROPERTY, "OHOS::Ace::NG::MenuPaintProperty",
                 RepositoryFile.from_path(f"{_ROOT}/menu/menu_paint_property.h"), "menu"),
        RoleRule("shared.overlay_manager", NodeKind.OVERLAY_MANAGER, "OHOS::Ace::NG::OverlayManager",
                 RepositoryFile.from_path(f"{_ROOT}/overlay/overlay_manager.h"), None),
    ))
    return tuple(rules)


ROLE_RULES = _rules()


def default_role_mapper() -> ArkUIRoleMapper:
    return ArkUIRoleMapper(COMPONENTS, ROLE_RULES)
