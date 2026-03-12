from __future__ import annotations

import atexit
import threading
from pathlib import PurePosixPath
from pathlib import Path
from typing import Any

from config import Settings
from sim_app import IsaacSimContext


JOINT_GROUPS: dict[str, list[str]] = {
    "head": [
        "head_yaw_joint",
        "head_pitch_joint",
    ],
    "waist": [
        "waist_yaw_joint",
    ],
    "left_arm": [
        "left_shoulder_pitch_joint",
        "left_shoulder_roll_joint",
        "left_shoulder_yaw_joint",
        "left_elbow_pitch_joint",
        "left_wrist_yaw_joint",
        "left_wrist_pitch_joint",
        "left_wrist_roll_joint",
    ],
    "right_arm": [
        "right_shoulder_pitch_joint",
        "right_shoulder_roll_joint",
        "right_shoulder_yaw_joint",
        "right_elbow_pitch_joint",
        "right_wrist_yaw_joint",
        "right_wrist_pitch_joint",
        "right_wrist_roll_joint",
    ],
}

DEFAULT_NAMED_POSES: dict[str, dict[str, float]] = {
    "upper_body_ready": {
        "left_shoulder_pitch_joint": 0.25,
        "left_shoulder_roll_joint": 0.12,
        "left_elbow_pitch_joint": 0.45,
        "right_shoulder_pitch_joint": -0.25,
        "right_shoulder_roll_joint": -0.12,
        "right_elbow_pitch_joint": -0.45,
    },
    "left_arm_up": {
        "left_shoulder_pitch_joint": 0.55,
        "left_shoulder_roll_joint": 0.18,
        "left_elbow_pitch_joint": 0.95,
    },
    "right_arm_up": {
        "right_shoulder_pitch_joint": -0.55,
        "right_shoulder_roll_joint": -0.18,
        "right_elbow_pitch_joint": -0.95,
    },
    "look_left": {
        "head_yaw_joint": 0.35,
    },
    "look_right": {
        "head_yaw_joint": -0.35,
    },
}


class GR2SimulationController:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.RLock()
        self._ctx = IsaacSimContext(headless=settings.simulation.headless)
        self._modules = None
        self._world = None
        self._robot = None
        self._connected = False
        self._usd_path: Path | None = None
        self._articulation_root_path: str | None = None
        self._dof_names: list[str] = []
        self._dof_lookup: dict[str, int] = {}
        self._initial_joint_positions: dict[str, float] = {}
        self._controlled_joint_names = self._build_controlled_joint_names()
        self._named_poses = self._build_named_poses()
        atexit.register(self.shutdown)

    def connect(self) -> dict[str, Any]:
        with self._lock:
            if self._connected:
                return self._status_payload(
                    status="ok",
                    message="GR2 simulation already connected.",
                )

            self._ensure_loaded()
            self._connected = True
            return self._status_payload(
                status="ok",
                message="GR2 simulation connected and ready.",
            )

    def disconnect(self) -> dict[str, Any]:
        with self._lock:
            if not self._modules or not self._robot:
                return self._status_payload(
                    status="ok",
                    message="GR2 simulation was not started.",
                )

            self._connected = False
            return self._status_payload(
                status="ok",
                message=(
                    "GR2 simulation marked idle. "
                    "The SimulationApp remains alive for reuse in this baseline."
                ),
            )

    def shutdown(self) -> None:
        with self._lock:
            self._connected = False
            self._robot = None
            self._world = None
            self._dof_names = []
            self._dof_lookup = {}
            self._initial_joint_positions = {}
            self._articulation_root_path = None
            self._usd_path = None
            self._ctx.close()
            self._modules = None

    def list_named_poses(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "named_poses": sorted(self._named_poses.keys()),
            "supported_joints": list(self._controlled_joint_names),
        }

    def get_joint_state(self, joint_names: list[str] | None = None) -> dict[str, Any]:
        with self._lock:
            self._require_connected()
            requested_joint_names = joint_names or list(self._controlled_joint_names)
            self._validate_joint_names(requested_joint_names)
            current_positions = self._robot.get_joint_positions()
            positions = {
                name: float(current_positions[self._dof_lookup[name]])
                for name in requested_joint_names
            }
            return self._status_payload(
                status="ok",
                message="Joint state retrieved.",
                joint_state=positions,
                requested_joints=requested_joint_names,
            )

    def move_named_pose(
        self,
        name: str,
        duration: float | None = None,
        blocking: bool | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._require_connected()
            pose_name = str(name)
            if pose_name not in self._named_poses:
                raise ValueError(
                    f"Unknown pose {pose_name!r}. Available poses: {sorted(self._named_poses)}"
                )
            return self.move_joints(
                joint_targets=self._named_poses[pose_name],
                duration=duration,
                blocking=blocking,
                label=f"named pose {pose_name}",
            )

    def move_joints(
        self,
        joint_targets: dict[str, float],
        duration: float | None = None,
        blocking: bool | None = None,
        label: str = "joint motion",
    ) -> dict[str, Any]:
        with self._lock:
            self._require_connected()
            if not isinstance(joint_targets, dict) or not joint_targets:
                raise ValueError("joint_targets must be a non-empty mapping of joint_name -> radians")

            use_blocking = self.settings.motion.blocking_by_default if blocking is None else bool(blocking)
            if not use_blocking:
                raise ValueError("Non-blocking motion is not supported in the current baseline.")

            resolved_duration = self.settings.motion.default_duration if duration is None else float(duration)
            if resolved_duration < 0.0:
                raise ValueError("duration must be >= 0")

            normalized_targets = {
                str(name): float(value) for name, value in joint_targets.items()
            }
            self._validate_joint_names(list(normalized_targets))

            start_positions = self._robot.get_joint_positions().copy()
            target_positions = start_positions.copy()
            for joint_name, target in normalized_targets.items():
                target_positions[self._dof_lookup[joint_name]] = target

            step_hz = max(1, int(self.settings.motion.command_step_hz))
            step_count = max(1, int(round(resolved_duration * step_hz))) if resolved_duration > 0 else 1
            controller = self._robot.get_articulation_controller()

            for step_idx in range(1, step_count + 1):
                alpha = float(step_idx) / float(step_count)
                interpolated = start_positions + (target_positions - start_positions) * alpha
                controller.apply_action(
                    self._modules.ArticulationAction(joint_positions=interpolated)
                )
                self._world.step(render=not self.settings.simulation.headless)

            final_positions = self._robot.get_joint_positions()
            commanded_positions = {
                joint_name: float(final_positions[self._dof_lookup[joint_name]])
                for joint_name in normalized_targets
            }
            return self._status_payload(
                status="ok",
                message=f"Completed {label}.",
                commanded_joints=commanded_positions,
                duration=resolved_duration,
                step_count=step_count,
            )

    def _ensure_loaded(self) -> None:
        if self._robot is not None and self._world is not None:
            return

        self._usd_path = self.settings.assets.resolve_usd_path()
        self._modules = self._ctx.start()
        if self._should_try_reference_loading() and self._try_load_by_reference():
            return
        self._load_by_opening_stage()

    def _require_connected(self) -> None:
        if not self._connected:
            self.connect()

    def _build_controlled_joint_names(self) -> list[str]:
        controlled_joint_names: list[str] = []
        for group_name in self.settings.robot.control_groups:
            if group_name not in JOINT_GROUPS:
                raise ValueError(
                    f"Unsupported control group {group_name!r}. Available groups: {sorted(JOINT_GROUPS)}"
                )
            controlled_joint_names.extend(JOINT_GROUPS[group_name])
        return controlled_joint_names

    def _build_named_poses(self) -> dict[str, dict[str, float]]:
        named_poses: dict[str, dict[str, float]] = {"home": {}}
        controlled = set(self._controlled_joint_names)
        for pose_name, pose_values in DEFAULT_NAMED_POSES.items():
            filtered = {
                joint_name: value
                for joint_name, value in pose_values.items()
                if joint_name in controlled
            }
            named_poses[pose_name] = filtered
        return named_poses

    def _validate_control_groups(self) -> None:
        missing = [
            joint_name
            for joint_name in self._controlled_joint_names
            if joint_name not in self._dof_lookup
        ]
        if missing:
            raise RuntimeError(
                "Configured control joints were not found in the loaded GR2 articulation: "
                f"{missing}"
            )

    def _validate_joint_names(self, joint_names: list[str]) -> None:
        unsupported = [
            joint_name
            for joint_name in joint_names
            if joint_name not in self._controlled_joint_names
        ]
        if unsupported:
            raise ValueError(
                "Unsupported joint names in this baseline: "
                f"{unsupported}. Supported joints: {self._controlled_joint_names}"
            )

    def _status_payload(self, status: str, message: str, **extra: Any) -> dict[str, Any]:
        payload = {
            "status": status,
            "message": message,
            "robot_name": self.settings.robot.name,
            "connected": self._connected,
            "usd_path": str(self._usd_path) if self._usd_path else None,
            "articulation_root": self._articulation_root_path,
            "robot_prim_path": self.settings.simulation.robot_prim_path,
            "supported_joints": list(self._controlled_joint_names),
            "named_poses": sorted(self._named_poses.keys()),
        }
        payload.update(extra)
        return payload

    def _find_articulation_root(self, asset_root_path: str) -> str:
        stage = self._modules.omni_usd.get_context().get_stage()
        asset_prim = stage.GetPrimAtPath(asset_root_path)
        if not asset_prim.IsValid():
            raise RuntimeError(f"Asset prim not found: {asset_root_path}")

        matches: list[str] = []
        for prim in self._modules.Usd.PrimRange(asset_prim):
            if prim.HasAPI(self._modules.UsdPhysics.ArticulationRootAPI):
                matches.append(str(prim.GetPath()))

        if not matches:
            raise RuntimeError(f"No articulation root found under {asset_root_path}")

        root_joint_matches = [path for path in matches if path.endswith("/root_joint")]
        return root_joint_matches[0] if root_joint_matches else matches[0]

    def _set_translate(self, prim_path: str, xyz: tuple[float, float, float]) -> None:
        stage = self._modules.omni_usd.get_context().get_stage()
        prim = stage.GetPrimAtPath(prim_path)
        xform = self._modules.UsdGeom.Xformable(prim)
        translate_op = None
        for op in xform.GetOrderedXformOps():
            if op.GetOpName() == "xformOp:translate":
                translate_op = op
                break
        if translate_op is None:
            translate_op = xform.AddTranslateOp()
        translate_op.Set(self._modules.Gf.Vec3d(*xyz))

    def _compute_bounds_min_z(self, prim_path: str) -> float:
        stage = self._modules.omni_usd.get_context().get_stage()
        prim = stage.GetPrimAtPath(prim_path)
        if not prim.IsValid():
            raise RuntimeError(f"Cannot compute bounds for missing prim: {prim_path}")

        bbox_cache = self._modules.UsdGeom.BBoxCache(
            self._modules.Usd.TimeCode.Default(),
            [self._modules.UsdGeom.Tokens.default_],
        )
        aligned_range = bbox_cache.ComputeWorldBound(prim).ComputeAlignedRange()
        min_corner = aligned_range.GetMin()
        max_corner = aligned_range.GetMax()
        if min_corner[2] > max_corner[2]:
            raise RuntimeError(f"Invalid bounds while computing ground alignment for {prim_path}")
        return float(min_corner[2])

    def _resolve_robot_root_path(self, articulation_root_path: str) -> str:
        articulation_path = PurePosixPath(articulation_root_path)
        if articulation_path.name == "root_joint" and len(articulation_path.parts) > 1:
            return str(articulation_path.parent)
        return articulation_root_path

    def _align_robot_to_ground(self, prim_path: str) -> None:
        spawn_x, spawn_y, spawn_z = self.settings.simulation.spawn_translation
        if self.settings.simulation.align_to_ground:
            min_z = self._compute_bounds_min_z(prim_path)
            target_z = spawn_z + self.settings.simulation.ground_clearance - min_z
        else:
            target_z = spawn_z

        self._set_translate(prim_path, (spawn_x, spawn_y, target_z))

    def _should_try_reference_loading(self) -> bool:
        usd_stage = self._modules.Usd.Stage.Open(str(self._usd_path))
        default_prim = usd_stage.GetDefaultPrim()
        if not default_prim or not default_prim.IsValid():
            return False

        default_path = str(default_prim.GetPath())
        if default_path in {"/Render", "/Looks"}:
            return False

        for prim in usd_stage.TraverseAll():
            if not prim.HasAPI(self._modules.UsdPhysics.ArticulationRootAPI):
                continue
            prim_path = str(prim.GetPath())
            if prim_path == default_path or prim_path.startswith(f"{default_path}/"):
                return True
        return False

    def _try_load_by_reference(self) -> bool:
        self._world = self._modules.World()
        self._world.scene.add_default_ground_plane()
        self._modules.create_prim(
            "/World/EnvLight",
            "DomeLight",
            attributes={"inputs:intensity": 1000},
        )
        self._modules.create_prim(self.settings.simulation.robot_prim_path, "Xform")
        self._modules.add_reference_to_stage(
            str(self._usd_path),
            self.settings.simulation.robot_prim_path,
        )
        self._pump_updates(5)
        try:
            self._align_robot_to_ground(self.settings.simulation.robot_prim_path)
        except RuntimeError:
            pass

        try:
            articulation_root_path = self._find_articulation_root(
                self.settings.simulation.robot_prim_path
            )
        except RuntimeError:
            self._world = None
            return False

        self._attach_robot(articulation_root_path)
        return True

    def _load_by_opening_stage(self) -> None:
        usd_context = self._modules.omni_usd.get_context()
        usd_context.open_stage(str(self._usd_path))
        self._pump_updates(5)

        self._world = self._modules.World()
        try:
            self._world.scene.add_default_ground_plane()
        except Exception:
            pass

        articulation_root_path = self._find_any_articulation_root()
        robot_root_path = self._resolve_robot_root_path(articulation_root_path)
        self._align_robot_to_ground(robot_root_path)
        self._pump_updates(5)
        self._attach_robot(articulation_root_path)

    def _find_any_articulation_root(self) -> str:
        stage = self._modules.omni_usd.get_context().get_stage()
        matches: list[str] = []
        for prim in stage.TraverseAll():
            if prim.HasAPI(self._modules.UsdPhysics.ArticulationRootAPI):
                matches.append(str(prim.GetPath()))

        if not matches:
            raise RuntimeError(
                f"No articulation root found anywhere in stage loaded from {self._usd_path}"
            )

        root_joint_matches = [path for path in matches if path.endswith("/root_joint")]
        return root_joint_matches[0] if root_joint_matches else matches[0]

    def _attach_robot(self, articulation_root_path: str) -> None:
        self._articulation_root_path = articulation_root_path
        self._robot = self._modules.Articulation(
            prim_path=self._articulation_root_path,
            name=self.settings.robot.name,
        )
        self._world.scene.add(self._robot)
        self._world.reset()

        for _ in range(max(1, self.settings.simulation.settle_steps)):
            self._world.step(render=not self.settings.simulation.headless)

        self._dof_names = list(self._robot.dof_names)
        self._dof_lookup = {name: idx for idx, name in enumerate(self._dof_names)}
        initial_positions = self._robot.get_joint_positions()
        self._initial_joint_positions = {
            joint_name: float(initial_positions[self._dof_lookup[joint_name]])
            for joint_name in self._controlled_joint_names
        }
        self._named_poses["home"] = dict(self._initial_joint_positions)
        self._validate_control_groups()

    def _pump_updates(self, count: int) -> None:
        app = self._ctx.simulation_app
        if app is None:
            return
        update = getattr(app, "update", None)
        if update is None:
            return
        for _ in range(max(0, count)):
            update()
