"""Small original C++ fixture exercising framework idioms through real clangd."""

from pathlib import Path


ROOT = "frameworks/core/components_ng/pattern"
FACTORY = "interfaces/inner_api/ace_kit/include/ui/base/referenced.h"
MACROS = "frameworks/core/components_ng/base/view_stack_processor.h"
COMPONENTS = ("Button", "Text", "Menu")


def queries() -> dict[str, tuple[str, ...]]:
    result = {}
    for name in COMPONENTS:
        slug = name.lower()
        for suffix, file, methods in (
            ("Pattern", "pattern", ("CreateLayoutProperty",)),
            ("ModelNG", "model_ng", ("SetFontWeight",)),
            ("LayoutProperty", "layout_property", ()),
            ("LayoutAlgorithm", "layout_algorithm", (("MeasureContent",) if name == "Text" else
                                                     ("Measure", "Layout") if name == "Menu" else ("Measure",))),
        ):
            owner = f"OHOS::Ace::NG::{name}{suffix}"
            result[f"{ROOT}/{slug}/{slug}_{file}.h"] = (owner,) + tuple(f"{owner}::{m}" for m in methods)
    owner = "OHOS::Ace::NG::OverlayManager"
    result[f"{ROOT}/overlay/overlay_manager.h"] = (owner, f"{owner}::ShowMenu", f"{owner}::HideMenu")
    return result


def write_repository(root: Path) -> None:
    def write(path: str, content: str) -> None:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    write(FACTORY, """#pragma once
#include <utility>
namespace OHOS::Ace {
template<class T> using RefPtr = T*;
class Referenced {
public:
    template<class T, bool> static RefPtr<T> Claim(T* p) { return p; }
    template<class T, class... Args>
    static RefPtr<T> MakeRefPtr(Args&&... args)
    {
        return Claim<T, true>(new T(std::forward<Args>(args)...));
    }
};
}
""")
    write("support.h", f'#pragma once\n#include "{FACTORY}"\n' + """#include <optional>
#include <cstdint>
namespace OHOS::Ace::NG {
struct LayoutWrapper {};
struct SizeF {};
struct LayoutConstraintF {};
struct OffsetF {};
enum class HideMenuType { NORMAL };
class LayoutProperty { public: void UpdateFontWeight(int) {} };
class LayoutAlgorithm {
public:
    virtual void Measure(LayoutWrapper*) {}
    virtual void Layout(LayoutWrapper*) {}
    virtual std::optional<SizeF> MeasureContent(const LayoutConstraintF&, LayoutWrapper*) { return {}; }
};
class FrameNode { public: template<class T> T* GetLayoutPropertyPtr() { return nullptr; } };
class ViewStackProcessor {
public:
    static ViewStackProcessor* GetInstance() { return nullptr; }
    FrameNode* GetMainFrameNode() { return nullptr; }
};
}
""")
    # Macro fixture is executable C++, not a text-only semantic-fact substitute.
    write(MACROS, '#pragma once\n#include "support.h"\n#define CHECK_NULL_VOID(p) if (!(p)) return\n' + """
#define ACE_UPDATE_LAYOUT_PROPERTY(target, name, value) \\
    do { \\
        auto frameNode = ViewStackProcessor::GetInstance()->GetMainFrameNode(); \\
        ACE_UPDATE_NODE_LAYOUT_PROPERTY(target, name, value, frameNode); \\
    } while (false)
#define ACE_UPDATE_NODE_LAYOUT_PROPERTY(target, name, value, frameNode) \\
    do { \\
        CHECK_NULL_VOID(frameNode); \\
        auto cast##target = (frameNode)->GetLayoutPropertyPtr<target>(); \\
        if (cast##target) { \\
            cast##target->Update##name(value); \\
        } \\
    } while (false)
""")
    for name in COMPONENTS:
        slug = name.lower()
        directory = f"{ROOT}/{slug}"
        write(f"{directory}/{slug}_layout_property.h", '#pragma once\n#include "support.h"\n' +
              f"namespace OHOS::Ace::NG {{\nclass {name}LayoutProperty : public LayoutProperty {{}};\n}}\n")
        write(f"{directory}/{slug}_pattern.h", f'#pragma once\n#include "{slug}_layout_property.h"\n' +
              f"namespace OHOS::Ace::NG {{\nclass {name}Pattern : public Referenced {{\npublic:\n" +
              f"    RefPtr<LayoutProperty> CreateLayoutProperty()\n    {{\n"
              f"        return MakeRefPtr<{name}LayoutProperty>();\n    }}\n}};\n}}\n")
        write(f"{directory}/{slug}_model_ng.h", f'#pragma once\n#include "{slug}_layout_property.h"\n' +
              f'#include "{MACROS}"\nnamespace OHOS::Ace::NG {{\nclass {name}ModelNG {{\npublic:\n' +
              f"    void SetFontWeight(int fontWeight)\n    {{\n"
              f"        ACE_UPDATE_LAYOUT_PROPERTY({name}LayoutProperty, FontWeight, fontWeight);\n    }}\n}};\n}}\n")
        methods = ("    std::optional<SizeF> MeasureContent(\n"
                   "        const LayoutConstraintF& contentConstraint, LayoutWrapper* layoutWrapper) override;\n"
                   if name == "Text" else "    void Measure(LayoutWrapper* layoutWrapper) override;\n")
        if name == "Menu":
            methods += "    void Layout(LayoutWrapper* layoutWrapper) override;\n"
        write(f"{directory}/{slug}_layout_algorithm.h", '#pragma once\n#include "support.h"\n' +
              f"namespace OHOS::Ace::NG {{\nclass {name}LayoutAlgorithm : public LayoutAlgorithm {{\npublic:\n" +
              methods + "};\n}\n")
    write(f"{ROOT}/overlay/overlay_manager.h", '#pragma once\n#include "support.h"\n' + """namespace OHOS::Ace::NG {
class OverlayManager {
public:
    void ShowMenu(int32_t targetId, const NG::OffsetF& offset, RefPtr<FrameNode> menu = nullptr);
    void HideMenu(const RefPtr<FrameNode>& menu, int32_t targetId, bool isMenuOnTouch = false,
        const HideMenuType& reason = HideMenuType::NORMAL);
};
}
""")
