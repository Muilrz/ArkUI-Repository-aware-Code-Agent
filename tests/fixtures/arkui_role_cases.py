"""Static P2-C smoke expectations, inspected from revision 0096f5bd.

Kept independent of the implementation catalog; no expected result is derived
from mapper output. The fixture contains paths/names, not vendored ArkUI code.
"""

ROLE_CASES = (
    ("button", "ButtonBridge", "bridge", "frameworks/core/components_ng/pattern/button/bridge/arkts_native_button_bridge.h"),
    ("button", "ButtonModelNG", "model", "frameworks/core/components_ng/pattern/button/button_model_ng.h"),
    ("button", "ButtonPattern", "pattern", "frameworks/core/components_ng/pattern/button/button_pattern.h"),
    ("button", "ButtonLayoutProperty", "layout_property", "frameworks/core/components_ng/pattern/button/button_layout_property.h"),
    ("button", "ButtonLayoutAlgorithm", "layout_algorithm", "frameworks/core/components_ng/pattern/button/button_layout_algorithm.h"),
    ("text", "TextBridge", "bridge", "frameworks/bridge/declarative_frontend/engine/jsi/nativeModule/arkts_native_text_bridge.h"),
    ("text", "TextModelNG", "model", "frameworks/core/components_ng/pattern/text/text_model_ng.h"),
    ("text", "TextPattern", "pattern", "frameworks/core/components_ng/pattern/text/text_pattern.h"),
    ("text", "TextLayoutProperty", "layout_property", "frameworks/core/components_ng/pattern/text/text_layout_property.h"),
    ("text", "TextLayoutAlgorithm", "layout_algorithm", "frameworks/core/components_ng/pattern/text/text_layout_algorithm.h"),
    ("menu", "MenuBridge", "bridge", "frameworks/core/components_ng/pattern/menu/bridge/menu/arkts_native_menu_bridge.h"),
    ("menu", "MenuModelNG", "model", "frameworks/core/components_ng/pattern/menu/menu_model_ng.h"),
    ("menu", "MenuPattern", "pattern", "frameworks/core/components_ng/pattern/menu/menu_pattern.h"),
    ("menu", "MenuLayoutProperty", "layout_property", "frameworks/core/components_ng/pattern/menu/menu_layout_property.h"),
    ("menu", "MenuLayoutAlgorithm", "layout_algorithm", "frameworks/core/components_ng/pattern/menu/menu_layout_algorithm.h"),
    ("menu", "MenuPaintProperty", "paint_property", "frameworks/core/components_ng/pattern/menu/menu_paint_property.h"),
    (None, "OverlayManager", "overlay_manager", "frameworks/core/components_ng/pattern/overlay/overlay_manager.h"),
)

NEGATIVE_CASES = (
    ("ToggleButtonPattern", "frameworks/core/components_ng/pattern/button/toggle_button_pattern.h"),
    ("MenuItemPattern", "frameworks/core/components_ng/pattern/menu/menu_item/menu_item_pattern.h"),
    ("InnerMenuPattern", "frameworks/core/components_ng/pattern/menu/menu_pattern.h"),
)
