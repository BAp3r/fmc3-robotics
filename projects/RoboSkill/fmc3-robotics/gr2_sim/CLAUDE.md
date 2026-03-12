# CLAUDE.md

## Purpose

`gr2_sim` is the current contribution-ready RoboSkill baseline for connecting RoboOS to GR2 running inside Isaac Sim / Isaac Lab.

The immediate delivery target is not a complete manipulation benchmark. It is a stable integration baseline that another team can pull, start, and attach to RoboOS master.

## Contribution Boundary

Included in this project boundary:

- MCP skill service for GR2 simulation
- Isaac runtime bootstrap
- GR2 articulation control and state query
- YAML-based runtime configuration
- docs for startup, troubleshooting, and integration status

Explicitly outside this project boundary:

- `scene_bottle` as a published module
- personal playground scripts as formal runtime entrypoints
- task props such as table / bottle / bowl
- IK and higher-level task primitives
- vendor PD-parameter work

## Current Architecture

The baseline is kept deliberately small:

1. `sim_app.py`
   Isaac runtime bootstrap
2. `gr2_controller.py`
   robot loading, articulation attachment, state management, motion execution
3. `skill.py`
   FastMCP tool surface for RoboOS
4. `config.py` + `config.yaml`
   runtime configuration

This keeps RoboOS-facing APIs separate from Isaac-specific implementation details.

## Current Tool Surface

Exposed tools:

- `connect_robot`
- `disconnect_robot`
- `get_joint_state`
- `list_named_poses`
- `move_named_pose`
- `move_joints`

Current named-pose baseline includes:

- `home`
- `upper_body_ready`
- `look_left`
- `look_right`
- `left_arm_up`
- `right_arm_up`

## Design Principles

- keep the RoboOS interface narrow and stable
- keep Isaac details inside the controller layer
- prefer config over machine-specific path edits in code
- favor high cohesion and low coupling over feature sprawl
- optimize first for a reliable baseline, then for richer skills

## Current Delivery Facts

- the skill can load the fixed GR2 USD and align it to the ground automatically
- the skill no longer relies on a hardcoded `z=1.0`
- stage-style fixed USD loading falls back to direct stage opening when reference loading is unsuitable
- one full natural-language RoboOS path has been validated locally

Validated request:

```text
请让 gr2_sim 动一下右胳膊。
```

Validated behavior:

- `master` reduces the request to a single executable subtask
- `slaver` resolves that subtask to `move_named_pose(name="right_arm_up")`
- the skill executes the pose successfully

## Known Risks

- `omni.fabric.plugin` warnings are still noisy
- `master` currently shows repeated result messages in logs
- `slaver` keeps historical failed actions in its prompt context, which makes logs messy

These do not currently block the working baseline, but they are real follow-up cleanup items.

## Next Expected Work

- clean repeated result handling on the RoboOS side
- reduce stale failed-action context in slaver prompts
- extend a few more natural-language mappings for baseline motions
- keep environment props and IK in later phases, not in the baseline push
