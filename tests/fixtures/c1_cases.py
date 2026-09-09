"""Human-approved C1 expected, frozen before real retrieval (2026-09-09).

Authoritative rationale: docs/evaluation/p3-c1-annotation-draft.md.
No retrieval output may change these records or bounds.
"""
from dataclasses import dataclass

REVISION = "0096f5bd943ed1f7fa56883aed0e2379f13c2885"
REPOSITORY = "OpenHarmony/arkui_ace_engine"
HUMAN_APPROVER = "task user, explicit approval 2026-09-09"
FROZEN_AT = "2026-09-09T08:42:35+00:00"
CLOSURE_RULE = "p2-creation-source-closure-v1"
ROOT = "frameworks/core/components_ng/pattern"
FRAME_HEADER = "frameworks/core/components_ng/base/frame_node.h"
BOUNDS = dict(max_queries=64, max_calls_per_channel=512, max_name_candidates=20,
              max_results_per_query=200, max_records_per_query=1000,
              max_candidates_per_channel=1000, max_candidates=2000, max_query_characters=4096)


@dataclass(frozen=True)
class Case:
    component: str
    entry_file: str
    entry_name: str
    entry_line: int
    model_line: int
    entry_hash: str
    model_hash: str
    task_text: str
    entry_namespace: str = "OHOS::Ace::NG"

    @property
    def qualified_entry(self):
        return self.entry_namespace + "::" + self.entry_name

    @property
    def qualified_model(self):
        return "OHOS::Ace::NG::" + self.component.title() + "ModelNG::CreateFrameNode"

    @property
    def model_file(self):
        return f"{ROOT}/{self.component}/{self.component}_model_ng.cpp"


CASES = (
    Case("button", f"{ROOT}/button/bridge/button_dynamic_modifier.cpp", "CreateButtonFrameNodeForCustom", 970, 659,
         "cc4ac849eff263ef4aad50f4e1fe4dbc085fe662c3bf6f19e34ae1d50f31721e",
         "5e423a593b059e7a80e343656d2c24a56c5f176ea181a2792e55dce2a3d70667",
         "检查 [component:Button] [symbol:CreateButtonFrameNodeForCustom] 的创建依赖"),
    Case("text", "frameworks/core/interfaces/native/node/view_model.cpp", "createTextNode", 113, 90,
         "4766c5bf42da2ff872d057933d2ec457d7306cb38a691d40126105ddfdae5142",
         "bd2d8a9e78b8253d5841e56b5309baa457ca53c6a433cd8e65f3bd1b1c43dc69",
         "检查 [component:Text] [symbol:createTextNode] 的创建依赖", "OHOS::Ace::NG::ViewModel"),
    Case("menu", f"{ROOT}/menu/bridge/menu/menu_dynamic_modifier.cpp", "CreateMenuFrameNode", 445, 25,
         "24632be2039ecb32ccebcb5dc739aa15ae8d84dce7f01263563056e383b65dfb",
         "89562c75890f7bd943768b52f8b623a863ee8d271ba6ec066a5fe1bdc0941572",
         "解释 [component:Menu] [symbol:CreateMenuFrameNode] 的 callback 创建路径"),
)

TEXT_FILES = tuple(sorted({p for c in CASES for p in (c.entry_file, c.model_file)}))
PREPARATION_FILES = tuple(sorted(set(TEXT_FILES) | {FRAME_HEADER} | {
    f"{ROOT}/{c.component}/{c.component}_{suffix}.h" for c in CASES for suffix in ("model_ng", "pattern")
}))
