"""P2 graph models and storage-independent query contracts."""

from arkui_agent.graph.memory import MemoryGraph
from arkui_agent.graph.model import (
    EdgeIdentity,
    GraphEdge,
    GraphNode,
    NodeIdentity,
    NodeKind,
    RelationEvidence,
    RelationType,
    SourceAnchor,
)
from arkui_agent.graph.query import (
    Direction,
    GraphQuery,
    GraphQueryError,
    NodeVisit,
    TraversalBounds,
    TraversalResult,
    TraversalStop,
)
from arkui_agent.graph.projection import GraphSnapshot, project_index
from arkui_agent.graph.storage import GraphStorageError, GraphStore
from arkui_agent.graph.domain import (
    ArkUIRoleMapper, ComponentMapping, ComponentSpec, DomainMap, MappingStatus,
    RoleCandidate, RoleMapping, RoleRule,
)
from arkui_agent.graph.arkui_rules import default_role_mapper
from arkui_agent.graph.framework import FrameworkDiagnostic, FrameworkExtraction, extract_framework_relations
from arkui_agent.graph.creation import (
    CreationBounds, CreationNode, CreationPath, CreationStage, CreationStatus,
    CreationTrace, PatternArgument, trace_component_creation,
)
from arkui_agent.graph.property import (
    PropertyBinding, PropertyBounds, PropertyNode, PropertyPath, PropertyStage,
    PropertyStatus, PropertyTrace, trace_property_update,
)
from arkui_agent.graph.layout import (
    LayoutBounds, LayoutDependency, LayoutNode, LayoutStage, LayoutStageResult,
    LayoutStatus, LayoutTrace, trace_measure_layout,
)
from arkui_agent.graph.overlay import (
    OverlayAnimation, OverlayBounds, OverlayLeg, OverlayNode, OverlayPath, OverlayStage,
    OverlayStatus, OverlayTrace, trace_overlay,
)

__all__ = [
    "Direction", "EdgeIdentity", "GraphEdge", "GraphNode", "GraphQuery",
    "GraphQueryError", "MemoryGraph", "NodeIdentity", "NodeKind", "NodeVisit",
    "RelationEvidence", "RelationType", "SourceAnchor", "TraversalBounds",
    "TraversalResult", "TraversalStop",
    "GraphSnapshot", "GraphStorageError", "GraphStore", "project_index",
    "ArkUIRoleMapper", "ComponentMapping", "ComponentSpec", "DomainMap", "MappingStatus",
    "RoleCandidate", "RoleMapping", "RoleRule", "default_role_mapper",
    "FrameworkDiagnostic", "FrameworkExtraction", "extract_framework_relations",
    "CreationBounds", "CreationNode", "CreationPath", "CreationStage", "CreationStatus",
    "CreationTrace", "PatternArgument", "trace_component_creation",
    "PropertyBinding", "PropertyBounds", "PropertyNode", "PropertyPath", "PropertyStage",
    "PropertyStatus", "PropertyTrace", "trace_property_update",
    "LayoutBounds", "LayoutDependency", "LayoutNode", "LayoutStage", "LayoutStageResult",
    "LayoutStatus", "LayoutTrace", "trace_measure_layout",
    "OverlayAnimation", "OverlayBounds", "OverlayLeg", "OverlayNode", "OverlayPath", "OverlayStage",
    "OverlayStatus", "OverlayTrace", "trace_overlay",
]
