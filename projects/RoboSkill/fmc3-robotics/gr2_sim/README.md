# GR2 Sim Skill Bridge

## Overview

`gr2_sim` is the current RoboSkill baseline for driving GR2 inside Isaac Sim / Isaac Lab through RoboOS.

This directory is the contribution boundary for the team-facing baseline. It does not treat `scene_bottle` as a public project dependency or as the runtime entrypoint. `scene_bottle` remains the local playground and source of earlier validated experiments.

Current delivery scope:

- RoboOS can connect to a GR2 simulation skill over MCP
- the simulation can load the GR2 body USD and keep it stable on the ground
- the baseline can control head, waist, left arm, and right arm joints
- one natural-language path has already been validated end-to-end through RoboOS

Out of scope for this baseline:

- table / bottle / task props
- IK
- hand-level fine control
- manufacturer PD parameters
- full task scene authoring

## Current Status

The following path has been validated on this machine:

`release page -> master -> Redis -> slaver -> gr2_sim skill -> Isaac Sim`

Validated natural-language example:

```text
请让 gr2_sim 动一下右胳膊。
```

Observed behavior:

- `master` decomposes the request into one executable subtask
- `slaver` selects `move_named_pose`
- the skill executes `move_named_pose(name="right_arm_up")`

## Architecture

The project is intentionally split into a few simple layers:

- `skill.py`
  FastMCP entrypoint and RoboOS-facing tool surface
- `gr2_controller.py`
  GR2 articulation loading, state, motion, and named poses
- `sim_app.py`
  Isaac runtime bootstrap
- `config.py`
  YAML config loading plus environment-variable overrides
- `config.yaml`
  local runtime defaults

Main tools exposed to RoboOS:

- `connect_robot`
- `disconnect_robot`
- `get_joint_state`
- `list_named_poses`
- `move_named_pose`
- `move_joints`

## Asset Strategy

The baseline currently uses a locally configured GR2 USD path from `config.yaml`.

Important boundary:

- runtime asset paths are configured
- source code does not hardcode personal absolute paths
- `scene_bottle` is not the formal project entrypoint

Current loading behavior:

- if the USD supports direct reference loading, the skill will use it
- otherwise it falls back to opening the stage directly and locating the articulation root
- the robot is aligned to the ground from its bounding box instead of using a hardcoded `z=1.0`

This was necessary because the fixed USD behaves like a stage asset and can initially intersect the ground plane if loaded naively.

## Setup

Install skill-side dependencies in `env_isaaclab`:

```bash
conda activate env_isaaclab
cd /home/fmc3/Documents/workspace1/fmc3-robotics/projects/RoboSkill/fmc3-robotics/gr2_sim
python -m pip install -r requirements.txt
```

Current MCP package alignment:

- `mcp==1.21.0`

## Configuration

Primary runtime config lives in [config.yaml](/home/fmc3/Documents/workspace1/fmc3-robotics/projects/RoboSkill/fmc3-robotics/gr2_sim/config.yaml).

Key fields:

- `server.host`
- `server.port`
- `simulation.headless`
- `simulation.spawn_translation`
- `simulation.align_to_ground`
- `simulation.ground_clearance`
- `assets.asset_root_dir`
- `assets.gr2_usd_path`

Environment variables remain supported only as override layers.

## Full Startup Sequence

### 1. Redis

If Redis is not already running:

```bash
redis-server
```

### 2. Start `gr2_sim` skill

If you want Isaac GUI, set `simulation.headless: false`.
For stable integration testing, `true` is still useful.

```bash
conda activate env_isaaclab
cd /home/fmc3/Documents/workspace1/fmc3-robotics/projects/RoboSkill/fmc3-robotics/gr2_sim
./run_skill.sh
```

### 3. Start RoboBrain service

Current tested model path:

```bash
conda activate robobrain
cd /home/fmc3/Documents/workspace1/fmc3-robotics
python projects/RoboBrain2.0/inference.py --serve --host 127.0.0.1 --port 4567 --model-id /home/fmc3/hf_models/RoboBrain2.0-3B
```

### 4. Start RoboOS master

Clear proxy variables first. The current `roboos` environment can fail on `socks://...` proxy settings.

```bash
conda activate roboos
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY
cd /home/fmc3/Documents/workspace1/fmc3-robotics/projects/RoboOS/master
python run.py
```

### 5. Start RoboOS slaver

```bash
conda activate roboos
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY
cd /home/fmc3/Documents/workspace1/fmc3-robotics/projects/RoboOS/slaver
python run.py
```

### 6. Start RoboOS web UI

```bash
conda activate roboos
cd /home/fmc3/Documents/workspace1/fmc3-robotics/projects/RoboOS/deploy
python run.py
```

Then open:

```text
http://127.0.0.1:8888/release
```

## Tested Local Config

Current machine-tested model config in:

- [config.yaml](/home/fmc3/Documents/workspace1/fmc3-robotics/projects/RoboOS/master/config.yaml)
- [config.yaml](/home/fmc3/Documents/workspace1/fmc3-robotics/projects/RoboOS/slaver/config.yaml)

Current tested values:

```yaml
model_select: "/home/fmc3/hf_models/RoboBrain2.0-3B"
cloud_model: "/home/fmc3/hf_models/RoboBrain2.0-3B"
cloud_server: "http://127.0.0.1:4567/v1/"
```

Current tested robot target in slaver config:

```yaml
robot:
  name: gr2_sim
  call_type: remote
  path: "http://127.0.0.1:8000"
```

## Troubleshooting

Common blockers seen during integration:

- `Redis 127.0.0.1:6379 connection refused`
  Redis is not running
- `address already in use` on port `8000`
  an older `python skill.py` is still alive
- `Unknown scheme for proxy URL 'socks://...'`
  clear proxy variables before starting `master` and `slaver`
- Isaac GUI opens and then exits immediately
  often this was a skill server startup failure, not a physics failure

Known non-blocking warnings:

- `omni.fabric.plugin getAttributeCount/getTypes called on non-existent path ...`
- Isaac deprecation warnings from legacy Omniverse modules

These are still noisy, but they do not currently block the baseline motion path.

## Scene Boundary

The baseline should keep a clean split between:

- minimal stable robot scene
- future task scene templates

Recommended order:

1. keep GR2 stable and controllable in a minimal scene
2. add props and tables through separate scene templates or USD composition
3. only then extend into richer tasks

## Documentation

- [CLAUDE.md](/home/fmc3/Documents/workspace1/fmc3-robotics/projects/RoboSkill/fmc3-robotics/gr2_sim/CLAUDE.md)
  project intent, design boundary, and current delivery state
- [PLAN.md](/home/fmc3/Documents/workspace1/fmc3-robotics/projects/RoboSkill/fmc3-robotics/gr2_sim/PLAN.md)
  phased implementation plan
- [WORKLOG.md](/home/fmc3/Documents/workspace1/fmc3-robotics/projects/RoboSkill/fmc3-robotics/gr2_sim/WORKLOG.md)
  running log of integration and debugging decisions
