from __future__ import annotations

import logging
import socket
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def _configure_python_logging() -> None:
    # Isaac Sim forwards Python stderr into its own log stream, which makes
    # third-party DEBUG lines look like Isaac runtime errors. Keep library
    # loggers quiet so actual exceptions remain visible.
    logging.basicConfig(level=logging.WARNING, force=True)
    logging.getLogger().setLevel(logging.WARNING)

    noisy_loggers = [
        "asyncio",
        "AutoNode",
        "mcp",
        "mcp.client",
        "mcp.server",
        "mcp.client.streamable_http",
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
        "httpx",
        "httpcore",
        "anyio",
        "sse_starlette",
        "server",
        "client",
        "omni",
        "omni.graph",
        "omni.graph.core",
        "omni.graph.tools",
    ]
    for logger_name in noisy_loggers:
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.WARNING)
        logger.propagate = False


_configure_python_logging()

from mcp.server.fastmcp import FastMCP

from config import load_settings
from gr2_controller import GR2SimulationController


SETTINGS = load_settings()
CONTROLLER = GR2SimulationController(SETTINGS)
mcp = FastMCP(
    SETTINGS.robot.name,
    stateless_http=True,
    host=SETTINGS.server.host,
    port=SETTINGS.server.port,
)


def _log(message: str) -> None:
    print(f"[gr2-sim-skill] {message}", flush=True)


def _validate_startup() -> None:
    resolved_usd_path = SETTINGS.assets.resolve_usd_path()
    summary = SETTINGS.runtime_summary()
    summary["usd_path"] = str(resolved_usd_path)
    _log(f"startup_config={summary}")


def _ensure_server_port_available() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((SETTINGS.server.host, SETTINGS.server.port))
        except OSError as exc:
            raise RuntimeError(
                "Skill server port is already in use. "
                f"host={SETTINGS.server.host!r} port={SETTINGS.server.port}. "
                "Stop the existing skill process or change server.port in config.yaml."
            ) from exc


def _prepare_runtime() -> None:
    # Isaac Sim initialization is significantly more stable when it happens
    # before the FastMCP/uvicorn event loop starts handling requests.
    _log("preloading the Isaac simulation runtime")
    CONTROLLER.connect()
    CONTROLLER.disconnect()


@mcp.tool()
def connect_robot() -> dict[str, Any]:
    """Start or reuse the GR2 Isaac simulation session and prepare upper-body control.

    Call this before any motion or state query tools.
    """
    _log("connect_robot called")
    return CONTROLLER.connect()


@mcp.tool()
def disconnect_robot() -> dict[str, Any]:
    """Mark the GR2 simulation idle.

    This baseline keeps the underlying SimulationApp alive for reuse instead of closing it.
    """
    _log("disconnect_robot called")
    return CONTROLLER.disconnect()


@mcp.tool()
def get_joint_state(joint_names: list[str] | None = None) -> dict[str, Any]:
    """Get absolute joint positions in radians for the GR2 upper body.

    If joint_names is omitted, the baseline returns all supported upper-body joints.
    """
    _log(f"get_joint_state called with joint_names={joint_names}")
    return CONTROLLER.get_joint_state(joint_names=joint_names)


@mcp.tool()
def list_named_poses() -> dict[str, Any]:
    """List the named poses supported by the current baseline skill."""
    _log("list_named_poses called")
    return CONTROLLER.list_named_poses()


@mcp.tool()
def move_named_pose(
    name: str,
    duration: float | None = None,
    blocking: bool = True,
) -> dict[str, Any]:
    """Move the GR2 upper body to a named pose.

    Named poses are small baseline presets such as home and upper_body_ready.
    Keep blocking=true in the current baseline.
    """
    _log(f"move_named_pose called with name={name}, duration={duration}, blocking={blocking}")
    return CONTROLLER.move_named_pose(name=name, duration=duration, blocking=blocking)


@mcp.tool()
def move_joints(
    joint_targets: dict[str, float],
    duration: float | None = None,
    blocking: bool = True,
) -> dict[str, Any]:
    """Move a subset of GR2 upper-body joints to absolute target positions in radians.

    Supported joint groups in the current baseline:
    - head
    - waist
    - left_arm
    - right_arm

    Keep blocking=true in the current baseline.
    """
    _log(
        "move_joints called with "
        f"joint_targets={sorted(joint_targets.keys())}, duration={duration}, blocking={blocking}"
    )
    return CONTROLLER.move_joints(
        joint_targets=joint_targets,
        duration=duration,
        blocking=blocking,
    )


if __name__ == "__main__":
    _validate_startup()
    try:
        _ensure_server_port_available()
    except RuntimeError as exc:
        _log(f"startup_error={exc}")
        raise SystemExit(1) from exc
    if not SETTINGS.simulation.auto_start:
        _log(
            "SIM_AUTO_START=false was requested, but the baseline still preloads the "
            "simulation to avoid Isaac/FastMCP event-loop conflicts."
        )
    _prepare_runtime()
    _log(
        f"starting FastMCP server on http://{SETTINGS.server.host}:{SETTINGS.server.port}/mcp"
    )
    mcp.run(transport=SETTINGS.server.transport)
