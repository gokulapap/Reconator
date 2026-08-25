from fastapi import APIRouter
from pydantic import BaseModel

from app.recon.modules.builtin import register_builtin_modules
from app.recon.modules.registry import registry

router = APIRouter(prefix="/modules", tags=["modules"])


class ModuleInfo(BaseModel):
    name: str
    version: str
    description: str
    timeout: int
    capability: str
    consumes: list[str]
    produces: list[str]
    mode: str
    implementation: str
    default_profiles: list[str]
    cache_ttl_seconds: int
    accepts_derived_inputs: bool
    depends_on_capabilities: list[str]
    capability_policy: str
    implementation_priority: int
    available: bool


@router.get("", response_model=list[ModuleInfo])
def list_modules() -> list[ModuleInfo]:
    register_builtin_modules()
    return [
        ModuleInfo(
            name=m.manifest.name,
            version=m.manifest.version,
            description=m.manifest.description,
            timeout=m.manifest.timeout_seconds,
            capability=m.manifest.capability,
            consumes=sorted(m.manifest.consumes),
            produces=sorted(m.manifest.produces),
            mode=m.manifest.mode.value,
            implementation=m.manifest.implementation,
            default_profiles=sorted(m.manifest.default_profiles),
            cache_ttl_seconds=m.manifest.cache_ttl_seconds,
            accepts_derived_inputs=m.manifest.accepts_derived_inputs,
            depends_on_capabilities=sorted(m.manifest.depends_on_capabilities),
            capability_policy=registry.policy_for_capability(m.manifest.capability).value,
            implementation_priority=m.manifest.implementation_priority,
            available=registry.is_available(m),
        )
        for m in registry.all()
    ]
