from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = PROJECT_DIR / "config.yaml"
DEFAULT_CONFIG_ENV = "GR2_SIM_CONFIG"
FIXED_USD_FILENAME = "gr2v4_1_0_fourier_hand_6dof_fixed.usd"
ORIGINAL_USD_FILENAME = "gr2v4_1_0_fourier_hand_6dof.usd"


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"Cannot parse boolean value from {value!r}")


def _as_int(value: Any, default: int) -> int:
    if value is None:
        return default
    return int(value)


def _as_float(value: Any, default: float) -> float:
    if value is None:
        return default
    return float(value)


def _as_str(value: Any, default: str) -> str:
    if value is None:
        return default
    return str(value)


def _as_optional_str(value: Any) -> str | None:
    if value in (None, "", "null", "None"):
        return None
    return str(value)


def _as_list_of_str(value: Any, default: list[str]) -> list[str]:
    if value is None:
        return list(default)
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _resolve_path(value: str | None, base_dir: Path | None = None) -> Path | None:
    if not value:
        return None
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate
    if base_dir is not None:
        return (base_dir / candidate).resolve()
    return candidate.resolve()


def _parse_translation(value: Any) -> tuple[float, float, float]:
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return (float(value[0]), float(value[1]), float(value[2]))
    if isinstance(value, dict):
        return (
            _as_float(value.get("x"), 0.0),
            _as_float(value.get("y"), 0.0),
            _as_float(value.get("z"), 0.0),
        )
    return (0.0, 0.0, 0.0)


def _nested_get(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    content = yaml.safe_load(path.read_text(encoding="utf-8"))
    return content if isinstance(content, dict) else {}


@dataclass(frozen=True)
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    transport: str = "streamable-http"


@dataclass(frozen=True)
class SimulationConfig:
    headless: bool = False
    robot_prim_path: str = "/World/GR2_Bot"
    auto_start: bool = True
    spawn_translation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    align_to_ground: bool = True
    ground_clearance: float = 0.0
    settle_steps: int = 80


@dataclass(frozen=True)
class AssetsConfig:
    gr2_usd_path: Path | None = None
    asset_root_dir: Path | None = None
    use_fixed_usd: bool = True

    def resolve_usd_path(self) -> Path:
        candidates: list[Path] = []
        if self.gr2_usd_path is not None:
            candidates.append(self.gr2_usd_path)
        if self.asset_root_dir is not None:
            filename = FIXED_USD_FILENAME if self.use_fixed_usd else ORIGINAL_USD_FILENAME
            candidates.append(self.asset_root_dir / filename)

        checked: list[str] = []
        for candidate in candidates:
            resolved = candidate.expanduser()
            checked.append(str(resolved))
            if resolved.exists():
                return resolved.resolve()

        if checked:
            raise FileNotFoundError(
                "Configured GR2 USD path was not found. "
                f"Checked: {checked}"
            )

        raise FileNotFoundError(
            "GR2 USD path is not configured. "
            "Set GR2_USD_PATH, GR2_ASSET_ROOT_DIR, or configure assets.gr2_usd_path."
        )


@dataclass(frozen=True)
class RobotConfig:
    name: str = "gr2_sim"
    control_groups: list[str] = field(
        default_factory=lambda: ["head", "waist", "left_arm", "right_arm"]
    )


@dataclass(frozen=True)
class MotionConfig:
    default_duration: float = 1.0
    command_step_hz: int = 60
    blocking_by_default: bool = True


@dataclass(frozen=True)
class Settings:
    server: ServerConfig
    simulation: SimulationConfig
    assets: AssetsConfig
    robot: RobotConfig
    motion: MotionConfig
    config_path: Path | None = None

    def runtime_summary(self) -> dict[str, Any]:
        usd_path = None
        try:
            usd_path = str(self.assets.resolve_usd_path())
        except FileNotFoundError:
            usd_path = None
        return {
            "host": self.server.host,
            "port": self.server.port,
            "transport": self.server.transport,
            "headless": self.simulation.headless,
            "robot_name": self.robot.name,
            "robot_prim_path": self.simulation.robot_prim_path,
            "spawn_translation": list(self.simulation.spawn_translation),
            "align_to_ground": self.simulation.align_to_ground,
            "ground_clearance": self.simulation.ground_clearance,
            "usd_path": usd_path,
            "config_path": str(self.config_path) if self.config_path else None,
            "control_groups": list(self.robot.control_groups),
        }


def load_settings(config_path: str | os.PathLike[str] | None = None) -> Settings:
    configured_path = os.getenv(DEFAULT_CONFIG_ENV)
    config_file = Path(config_path or configured_path or DEFAULT_CONFIG_PATH).expanduser()
    config_file = config_file.resolve()
    raw = _load_yaml(config_file)
    config_base_dir = config_file.parent if config_file.exists() else PROJECT_DIR

    server = ServerConfig(
        host=_as_str(os.getenv("GR2_SERVER_HOST"), _nested_get(raw, "server", "host") or "0.0.0.0"),
        port=_as_int(os.getenv("GR2_SERVER_PORT"), _nested_get(raw, "server", "port") or 8000),
        transport=_as_str(
            os.getenv("GR2_SERVER_TRANSPORT"),
            _nested_get(raw, "server", "transport") or "streamable-http",
        ),
    )
    simulation = SimulationConfig(
        headless=_as_bool(
            os.getenv("SIM_HEADLESS"),
            _as_bool(_nested_get(raw, "simulation", "headless"), False),
        ),
        robot_prim_path=_as_str(
            os.getenv("SIM_ROBOT_PRIM_PATH"),
            _nested_get(raw, "simulation", "robot_prim_path") or "/World/GR2_Bot",
        ),
        auto_start=_as_bool(
            os.getenv("SIM_AUTO_START"),
            _as_bool(_nested_get(raw, "simulation", "auto_start"), True),
        ),
        spawn_translation=_parse_translation(
            _nested_get(raw, "simulation", "spawn_translation")
            if _nested_get(raw, "simulation", "spawn_translation") is not None
            else _nested_get(raw, "simulation", "initial_translation")
        ),
        align_to_ground=_as_bool(
            os.getenv("SIM_ALIGN_TO_GROUND"),
            _as_bool(_nested_get(raw, "simulation", "align_to_ground"), True),
        ),
        ground_clearance=_as_float(
            os.getenv("SIM_GROUND_CLEARANCE"),
            _nested_get(raw, "simulation", "ground_clearance") or 0.0,
        ),
        settle_steps=_as_int(
            os.getenv("SIM_SETTLE_STEPS"),
            _nested_get(raw, "simulation", "settle_steps") or 80,
        ),
    )
    assets = AssetsConfig(
        gr2_usd_path=_resolve_path(
            _as_optional_str(os.getenv("GR2_USD_PATH"))
            or _as_optional_str(_nested_get(raw, "assets", "gr2_usd_path")),
            config_base_dir,
        ),
        asset_root_dir=_resolve_path(
            _as_optional_str(os.getenv("GR2_ASSET_ROOT_DIR"))
            or _as_optional_str(_nested_get(raw, "assets", "asset_root_dir")),
            config_base_dir,
        ),
        use_fixed_usd=_as_bool(
            os.getenv("GR2_USE_FIXED_USD"),
            _as_bool(_nested_get(raw, "assets", "use_fixed_usd"), True),
        ),
    )
    robot = RobotConfig(
        name=_as_str(os.getenv("GR2_ROBOT_NAME"), _nested_get(raw, "robot", "name") or "gr2_sim"),
        control_groups=_as_list_of_str(
            _nested_get(raw, "robot", "control_groups"),
            ["head", "waist", "left_arm", "right_arm"],
        ),
    )
    motion = MotionConfig(
        default_duration=_as_float(
            os.getenv("GR2_DEFAULT_DURATION"),
            _nested_get(raw, "motion", "default_duration") or 1.0,
        ),
        command_step_hz=_as_int(
            os.getenv("GR2_COMMAND_STEP_HZ"),
            _nested_get(raw, "motion", "command_step_hz") or 60,
        ),
        blocking_by_default=_as_bool(
            os.getenv("GR2_BLOCKING_BY_DEFAULT"),
            _as_bool(_nested_get(raw, "motion", "blocking_by_default"), True),
        ),
    )
    return Settings(
        server=server,
        simulation=simulation,
        assets=assets,
        robot=robot,
        motion=motion,
        config_path=config_file if config_file.exists() else None,
    )
