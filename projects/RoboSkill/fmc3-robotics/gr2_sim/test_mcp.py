from __future__ import annotations

import argparse
import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test the GR2 Isaac Lab MCP skill.")
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8000",
        help="Base URL of the running skill service.",
    )
    parser.add_argument(
        "--skip-motion",
        action="store_true",
        help="Only list tools and query state without issuing a move command.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    mcp_url = f"{args.url.rstrip('/')}/mcp"
    async with streamablehttp_client(mcp_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            response = await session.list_tools()
            print("tools:", [tool.name for tool in response.tools], flush=True)

            result = await session.call_tool("connect_robot", {})
            print("connect_robot:", result.content[0].text, flush=True)

            result = await session.call_tool("list_named_poses", {})
            print("list_named_poses:", result.content[0].text, flush=True)

            result = await session.call_tool("get_joint_state", {})
            print("get_joint_state:", result.content[0].text, flush=True)

            if not args.skip_motion:
                result = await session.call_tool(
                    "move_named_pose",
                    {"name": "upper_body_ready", "duration": 1.5, "blocking": True},
                )
                print("move_named_pose:", result.content[0].text, flush=True)

                result = await session.call_tool(
                    "move_joints",
                    {
                        "joint_targets": {
                            "head_yaw_joint": 0.25,
                            "left_wrist_pitch_joint": 0.2,
                            "right_wrist_pitch_joint": -0.2,
                        },
                        "duration": 1.0,
                        "blocking": True,
                    },
                )
                print("move_joints:", result.content[0].text, flush=True)

            result = await session.call_tool("disconnect_robot", {})
            print("disconnect_robot:", result.content[0].text, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
