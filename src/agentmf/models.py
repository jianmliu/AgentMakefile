from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

PermissionAction = Literal["allow", "ask", "deny"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class CompileSpec(StrictModel):
    targets: List[str] = Field(default_factory=list)


class ArtifactSpec(StrictModel):
    path: Optional[str] = None
    frontmatter: Dict[str, Any] = Field(default_factory=dict)
    managed_block: bool = True


class IncludeSpec(StrictModel):
    path: Optional[str] = None
    package: Optional[str] = None
    version: Optional[str] = None
    as_: Optional[str] = Field(default=None, alias="as")

    @model_validator(mode="after")
    def validate_include(self) -> "IncludeSpec":
        if bool(self.path) == bool(self.package):
            raise ValueError("include must specify exactly one of path or package")
        if self.package is not None:
            raise ValueError("package includes are future-facing and disabled in the initial compiler")
        if self.version is not None and self.package is None:
            raise ValueError("version is only valid for package includes")
        return self


OutputSpec = ArtifactSpec


class InputSpec(StrictModel):
    required: List[str] = Field(default_factory=list)
    optional: List[str] = Field(default_factory=list)


class PermissionSpec(StrictModel):
    defaults: Dict[str, PermissionAction] = Field(default_factory=dict)
    rules: Dict[str, Dict[str, PermissionAction]] = Field(default_factory=dict)


PermissionSource = Union[PermissionSpec, Dict[str, Dict[str, PermissionAction]]]


class PolicySpec(StrictModel):
    description: Optional[str] = None
    applies_to: List[str] = Field(default_factory=list)
    guards: List[Union[str, Dict[str, Any]]] = Field(default_factory=list)
    steps: List[Union[str, Dict[str, Any]]] = Field(default_factory=list)
    output_format: List[str] = Field(default_factory=list)
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    locked: bool = False


class SkillSpec(StrictModel):
    namespace: Optional[str] = None
    description: Optional[str] = None
    implementation: Dict[str, Any] = Field(default_factory=dict)
    inputs: InputSpec = Field(default_factory=InputSpec)
    match: Dict[str, Any] = Field(default_factory=dict)
    steps: List[Union[str, Dict[str, Any]]] = Field(default_factory=list)
    guards: List[Union[str, Dict[str, Any]]] = Field(default_factory=list)
    output_format: List[str] = Field(default_factory=list)
    output_schema: Dict[str, Any] = Field(default_factory=dict)


class ModelSpec(StrictModel):
    family: Optional[str] = None
    cost: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list)
    match: Dict[str, Any] = Field(default_factory=dict)
    priority: StrictInt = Field(default=50, ge=0, le=100)
    default: bool = False


class TargetSpec(StrictModel):
    phony: bool = True
    priority: StrictInt = Field(default=50, ge=0, le=100)
    cost: float = Field(default=0.0, ge=0)
    description: Optional[str] = None
    inputs: InputSpec = Field(default_factory=InputSpec)
    match: Dict[str, Any] = Field(default_factory=dict)
    policies: List[str] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    deps: List[str] = Field(default_factory=list)
    compile_to: Optional[str] = None
    extends: Optional[str] = None
    add_policies: List[str] = Field(default_factory=list)
    add_steps: List[Union[str, Dict[str, Any]]] = Field(default_factory=list)
    add_output_format: List[str] = Field(default_factory=list)
    override: Dict[str, Any] = Field(default_factory=dict)
    steps: List[Union[str, Dict[str, Any]]] = Field(default_factory=list)
    guards: List[Union[str, Dict[str, Any]]] = Field(default_factory=list)
    output_format: List[str] = Field(default_factory=list)
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    fallback: Dict[str, List[Union[str, Dict[str, Any]]]] = Field(default_factory=dict)


class AgentMakefileSource(StrictModel):
    version: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    include: List[Union[str, IncludeSpec]] = Field(default_factory=list)
    vars: Dict[str, Any] = Field(default_factory=dict)
    compile: CompileSpec = Field(default_factory=CompileSpec)
    artifacts: Dict[str, ArtifactSpec] = Field(default_factory=dict)
    outputs: Dict[str, OutputSpec] = Field(default_factory=dict)
    policies: Dict[str, PolicySpec] = Field(default_factory=dict)
    skills: Dict[str, SkillSpec] = Field(default_factory=dict)
    models: Dict[str, ModelSpec] = Field(default_factory=dict)
    targets: Dict[str, TargetSpec] = Field(default_factory=dict)
    permissions: PermissionSource = Field(default_factory=PermissionSpec)
    hooks: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict)
    validation: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    patterns: Dict[str, Any] = Field(default_factory=dict)
    cache: Dict[str, Any] = Field(default_factory=dict)
    tool_rules: Dict[str, Any] = Field(default_factory=dict)
    compiler_hints: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("version", mode="before")
    @classmethod
    def normalize_version(cls, value: Any) -> str:
        return str(value)

    @model_validator(mode="after")
    def validate_artifact_alias_conflicts(self) -> "AgentMakefileSource":
        duplicate_backends = set(self.artifacts).intersection(self.outputs)
        if duplicate_backends:
            names = ", ".join(sorted(duplicate_backends))
            raise ValueError(f"backend keys cannot appear in both artifacts and outputs: {names}")
        return self


class IRPolicy(StrictModel):
    name: str
    description: Optional[str] = None
    applies_to: List[str] = Field(default_factory=list)
    guards: List[Union[str, Dict[str, Any]]] = Field(default_factory=list)
    steps: List[Union[str, Dict[str, Any]]] = Field(default_factory=list)
    output_format: List[str] = Field(default_factory=list)
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    locked: bool = False


class IRSkill(StrictModel):
    name: str
    qualified_name: str
    namespace: Optional[str] = None
    description: Optional[str] = None
    implementation: Dict[str, Any] = Field(default_factory=dict)
    inputs: InputSpec = Field(default_factory=InputSpec)
    match: Dict[str, Any] = Field(default_factory=dict)
    steps: List[Union[str, Dict[str, Any]]] = Field(default_factory=list)
    guards: List[Union[str, Dict[str, Any]]] = Field(default_factory=list)
    output_format: List[str] = Field(default_factory=list)
    output_schema: Dict[str, Any] = Field(default_factory=dict)


class IRTarget(StrictModel):
    name: str
    phony: bool
    priority: int
    cost: float = 0.0
    compile_to: Optional[str] = None
    description: Optional[str] = None
    inputs: InputSpec = Field(default_factory=InputSpec)
    match: Dict[str, Any] = Field(default_factory=dict)
    policies: List[IRPolicy] = Field(default_factory=list)
    skills: List[IRSkill] = Field(default_factory=list)
    deps: List[str] = Field(default_factory=list)
    steps: List[Union[str, Dict[str, Any]]] = Field(default_factory=list)
    guards: List[Union[str, Dict[str, Any]]] = Field(default_factory=list)
    output_format: List[str] = Field(default_factory=list)
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    fallback: Dict[str, List[Union[str, Dict[str, Any]]]] = Field(default_factory=dict)
    pipeline: Dict[str, Any] = Field(default_factory=dict)


class IRModel(StrictModel):
    name: str
    family: Optional[str] = None
    cost: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list)
    match: Dict[str, Any] = Field(default_factory=dict)
    priority: int = 50
    default: bool = False


class IRPermission(StrictModel):
    tool: str
    pattern: str
    action: PermissionAction


class AgentRuleIR(StrictModel):
    version: str
    metadata: Dict[str, Any]
    vars: Dict[str, Any]
    targets: List[IRTarget]
    policies: List[IRPolicy]
    skills: List[IRSkill]
    models: List[IRModel] = Field(default_factory=list)
    permission_defaults: Dict[str, PermissionAction]
    permissions: List[IRPermission]
    hooks: Dict[str, List[Dict[str, Any]]]
    validation: Dict[str, Dict[str, Any]]
    artifacts: Dict[str, ArtifactSpec]
    patterns: Dict[str, Any]
    cache: Dict[str, Any]
    tool_rules: Dict[str, Any]
    compiler_hints: Dict[str, Any]
