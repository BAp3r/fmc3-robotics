# Plan

## 基线目标

今天的目标不是做完整仿真场景，而是交付一个能让另一支 team 先接入 `master` 的可运行基线。

最低标准：

- RoboOS `slaver` 能连接 skill 服务
- skill 服务能加载 GR2 本体 USD
- 至少能控制头、腰、双臂的基础关节
- 团队成员无需改源码中的个人绝对路径

## 阶段 0：现状固化

目标：把已有探索结果整理为可以继续开发的输入。

- 阅读 RoboOS 的 MCP 接入链路。
- 阅读 `cm_bot2.py` 与 `fix_robot_physics.py`。
- 明确 GR2 当前可控关节、场景资源路径、相机能力。
- 新建正式贡献目录并写基础说明文档。

状态：已完成。

## 阶段 1：最小桥接版

目标：RoboOS 可以调用仿真中的 GR2 完成稳定的低层动作。

交付物：

- `skill.py`
- `sim_app.py`
- `gr2_controller.py`
- `config.py`
- `config.yaml`
- `config.example.yaml`
- `test_mcp.py`
- `run_skill.sh`

建议 tools：

- `connect_robot()`
- `disconnect_robot()`
- `get_joint_state()`
- `move_joints(joint_targets, duration=1.0, blocking=true)`
- `move_named_pose(name)`

验收标准：

- MCP 服务能正常 `list_tools()`
- RoboOS `slaver` 能成功连接该服务
- 至少一个 tool 能在仿真中稳定驱动 GR2 关节
- 返回值包含关键状态，便于日志排查
- 不依赖 `scene_bottle` 目录作为运行入口
- 优先通过 `config.yaml` 提供 USD 路径和运行参数
- 环境变量仅作为覆盖项保留

状态：已完成最小闭环和本地 smoke test。

## 当前问题记录

- `isaacsim.txt` 中大量 `[Error] [py stderr]` 主要是 Isaac / MCP 的 debug 文本通过 stderr 输出，并不等价于真实失败。
- 当前本地 smoke test 已经证明 skill 本身可用，`connect_robot / move_named_pose / move_joints` 正常。
- `roboos.txt` 中真正的阻塞问题不是 MCP，而是 `Redis 127.0.0.1:6379` 未启动，导致 `RoboOS slaver` 无法注册和监听协作消息。
- 有头模式下，当前 fixed USD 直接打开后，GR2 本体与 ground plane 初始重合，导致穿模、抖动、腿飞起，严重时会触发 GUI 闪退。

结论：

- 当前 skill 服务链路是通的。
- 如果要真正接 `master`，下一步必须保证 Redis 正常启动。
- 场景稳定性的第一优先级不是补桌子和物件，而是保证机器人本体初始位姿稳定。

## 场景基线策略

目标：先交付“最小稳定场景”，而不是一开始就绑定完整任务场景。

当前推荐：

- 由 `gr2_sim` 在启动时负责最小场景基线
- 至少包含 ground plane、light、GR2 本体
- 机器人默认按包围盒自动贴地，避免把 `z=1.0` 这类经验值硬编码进加载逻辑

后续再扩展：

- 单独的 scene template USD
- 桌子 / 抓取物体
- 多相机和任务观测

原因：

- 机器人本体站不稳时，任务场景只会放大排障难度
- “最小稳定场景”和“任务场景模板”应该是两层职责
- 这也更符合 `gr2_sim` 作为 RoboSkill 基线的交付边界

## 阶段 2：场景与观测能力

目标：让 skill 具备更完整的仿真交互能力。

交付物：

- 相机抓图接口
- reset / reload scene
- named poses 配置
- 关节限位与输入校验
- 场景资产接入规范

建议 tools：

- `capture_camera(tag=None)`
- `reset_scene()`
- `list_named_poses()`

验收标准：

- 相机抓图能落盘并返回路径
- reset 后机器人能回到稳定初始状态
- 无效 joint name / 非法目标值会得到清晰错误信息

## 阶段 2.5：解耦改造

目标：把 MCP 服务层和 Isaac 仿真执行层拆开，降低 `env_isaaclab` 的依赖污染和运行风险。

建议结构：

- `MCP gateway` 运行在轻量环境中
- `sim worker` 运行在 `env_isaaclab`
- gateway 通过进程间通信调用 worker

首选方案：

- `RoboOS -> FastMCP gateway -> stdio/json -> Isaac worker`

原因：

- 不要求 Isaac 环境继续承载 web server 依赖
- 能减少对 Isaac 环境内 `mcp / uvicorn / httpx` 版本的影响
- 仿真进程崩溃后，gateway 可以更容易做重启和错误翻译

交付物：

- `gateway/skill.py`
- `worker/worker_main.py`
- 统一的请求/响应 schema
- worker 启停和健康检查脚本

验收标准：

- `env_isaaclab` 中不再需要直接运行 FastMCP 服务
- gateway 与 worker 可以独立重启
- 现有 `connect_robot / get_joint_state / move_joints / move_named_pose` 语义不变
- 解耦后仍能通过 RoboOS `slaver` 完成同样的 smoke test

## 阶段 3：动作组合与扩展

目标：从低层 joint 控制扩展到更像 skill 的动作接口。

候选项：

- wave / nod / bow 等组合动作
- 双臂同步轨迹
- 手部姿态控制
- 面向任务的 primitive
- IK 控制接入

约束：

- 只有在阶段 1 的低层接口稳定后再做
- 组合动作要复用底层控制器，不重复造轮子
- IK 不应阻塞今天的基线交付

## 当前推荐的实现顺序

1. 从 `cm_bot2.py` 提取 USD 加载、articulation root 查找、DOF 索引逻辑
2. 抽象一个 `GR2SimulationController`
3. 加入配置层，优先使用 `config.yaml` 指定 USD 路径和运行参数
4. 用 `FastMCP` 暴露最小工具集
5. 写一个独立的 MCP 测试脚本验证工具调用
6. 提供最小启动脚本和 README
7. 用 RoboOS `slaver/config.yaml` 指向该 skill 服务做联通测试
8. 在基线稳定后启动 `gateway + worker` 解耦改造

## 需要确认的事项

1. 新项目目录名现已统一为 `gr2_sim`
2. 运行入口是否由 skill 服务独立启动 Isaac
3. 第一阶段只覆盖头、腰、双臂，不包含手部细粒度控制
4. 基线版本只加载机器人本体 USD，不绑定环境物体
