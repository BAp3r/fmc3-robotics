from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class IsaacModules:
    omni_usd: Any
    World: Any
    Articulation: Any
    create_prim: Any
    add_reference_to_stage: Any
    ArticulationAction: Any
    Gf: Any
    Usd: Any
    UsdGeom: Any
    UsdPhysics: Any


class IsaacSimContext:
    def __init__(self, headless: bool) -> None:
        self.headless = headless
        self.simulation_app = None
        self.modules: IsaacModules | None = None

    def start(self) -> IsaacModules:
        if self.modules is not None:
            return self.modules

        from isaacsim import SimulationApp

        self.simulation_app = SimulationApp({"headless": self.headless})

        import omni.usd
        from isaacsim.core.prims import SingleArticulation as Articulation
        from isaacsim.core.utils.prims import create_prim
        from isaacsim.core.utils.stage import add_reference_to_stage
        from isaacsim.core.utils.types import ArticulationAction
        from omni.isaac.core import World
        from pxr import Gf, Usd, UsdGeom, UsdPhysics

        self.modules = IsaacModules(
            omni_usd=omni.usd,
            World=World,
            Articulation=Articulation,
            create_prim=create_prim,
            add_reference_to_stage=add_reference_to_stage,
            ArticulationAction=ArticulationAction,
            Gf=Gf,
            Usd=Usd,
            UsdGeom=UsdGeom,
            UsdPhysics=UsdPhysics,
        )
        return self.modules

    def close(self) -> None:
        if self.simulation_app is not None:
            self.simulation_app.close()
            self.simulation_app = None
        self.modules = None
