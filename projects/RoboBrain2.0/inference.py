import argparse
import json
import os
import re
import cv2
import torch
from typing import Union
from transformers import AutoModelForVision2Seq, AutoProcessor, BitsAndBytesConfig
from qwen_vl_utils import process_vision_info

class UnifiedInference:
    """
    A unified class for performing inference using RoboBrain models.
    Supports both 3B (non-thinking) and 7B/32B (thinking) models.
    """

    def __init__(self, model_id="BAAI/RoboBrain2.0-7B", device_map="auto", load_in_4bit=False, max_memory=None):
        """
        Initialize the model and processor.
        """
        print("Loading Checkpoint ...")
        self.model_id = model_id

        quantization_config = None
        if load_in_4bit:
            print("Enabling 4-bit quantization...")
            quantization_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
                llm_int8_enable_fp32_cpu_offload=True
            )
            # === 关键修改：4-bit 模式强制使用单卡，避免 Meta Tensor 错误 ===
            print("Force setting device_map to GPU 0 for 4-bit mode...")
            device_map = {"": 0} 
            # 强制单卡后，max_memory 限制通常不再需要，或者会导致冲突，建议设为 None
            max_memory = None 

        max_memory_dict = None
        if max_memory:
            max_memory_dict = {0: max_memory, "cpu": "100GiB"}
            print(f"Applying max GPU memory limit: {max_memory_dict}")

        # === 针对 4090 48GB 的性能优化 ===
        # 1. 优先使用 bfloat16，这是 Ampere/Ada 架构(30/40系)的最佳精度
        dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        print(f"Using precision: {dtype}")

        # 2. 尝试启用 Flash Attention 2
        attn_impl = "sdpa" # PyTorch 2.0 默认的高效注意力
        try:
            import flash_attn
            attn_impl = "flash_attention_2"
            print("Flash Attention 2 is available and enabled.")
        except ImportError:
            print("Flash Attention 2 not found, falling back to SDPA/Eager.")

        self.model = AutoModelForVision2Seq.from_pretrained(
            model_id,
            torch_dtype=dtype,
            device_map=device_map,
            quantization_config=quantization_config,
            max_memory=max_memory_dict,
            low_cpu_mem_usage=True,
            attn_implementation=attn_impl  # 启用加速
        )

        # 3. 开启推理模式优化
        self.model.eval()

        self.processor = AutoProcessor.from_pretrained(model_id)
        
        self.supports_thinking = self._check_thinking_support(model_id)
        print(f"Model thinking support: {self.supports_thinking}")
        """
        Initialize the model and processor.

        Args:
            model_id (str): Path or Hugging Face model identifier
            device_map (str): Device mapping strategy ("auto", "cuda:0", etc.)
            load_in_4bit (bool): Whether to use 4-bit quantization.
            max_memory (str): Max GPU memory to use (e.g. "6GiB").
        """
        print("Loading Checkpoint ...")
        self.model_id = model_id

        quantization_config = None
        if load_in_4bit:
            print("Enabling 4-bit quantization...")
            quantization_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
                llm_int8_enable_fp32_cpu_offload=True
            )

        max_memory_dict = None
        if max_memory:
            max_memory_dict = {0: max_memory, "cpu": "100GiB"}
            print(f"Applying max GPU memory limit: {max_memory_dict}")

        self.model = AutoModelForVision2Seq.from_pretrained(
            model_id,
            torch_dtype=torch.float16,
            device_map=device_map,
            quantization_config=quantization_config,
            max_memory=max_memory_dict
        )
        self.processor = AutoProcessor.from_pretrained(model_id)
        
        self.supports_thinking = self._check_thinking_support(model_id)
        print(f"Model thinking support: {self.supports_thinking}")
        
    def _check_thinking_support(self, model_id):
        """Check if the model supports thinking mode based on model identifier."""
        model_name = model_id.lower()
        if "3b" in model_name:
            return False
        elif any(size in model_name for size in ["7b", "32b"]):
            return True
        else:
            return True
        
    def inference(self, text: str, image: Union[list, str], task="general", 
                 plot=False, enable_thinking=None, do_sample=True, temperature=0.7):
        """
        Perform inference with text and images input.
        
        Args:
            text (str): The input text prompt.
            image (Union[list,str]): The input image(s) as a list of file paths or a single file path.
            task (str): The task type, e.g., "general", "pointing", "affordance", "trajectory", "grounding".
            plot (bool): Whether to plot results on image.
            enable_thinking (bool, optional): Whether to enable thinking mode. 
                                            If None, auto-determined based on model capability.
            do_sample (bool): Whether to use sampling during generation.
            temperature (float): Temperature for sampling.
        """

        if isinstance(image, str):
            image = [image]
        if image is None:
            image = []

        assert task in ["general", "pointing", "affordance", "trajectory", "grounding"], \
            f"Invalid task type: {task}. Supported tasks are 'general', 'pointing', 'affordance', 'trajectory', 'grounding'."
        assert task == "general" or (task in ["pointing", "affordance", "trajectory", "grounding"] and len(image) == 1), \
            "Pointing, affordance, grounding, and trajectory tasks require exactly one image."

        if enable_thinking is None:
            enable_thinking = self.supports_thinking
        elif enable_thinking and not self.supports_thinking:
            print("Warning: Thinking mode requested but not supported by this model. Disabling thinking.")
            enable_thinking = False

        if task == "pointing":
            print("Pointing task detected. Adding pointing prompt.")
            text = f"{text}. Your answer should be formatted as a list of tuples, i.e. [(x1, y1), (x2, y2), ...], where each tuple contains the x and y coordinates of a point satisfying the conditions above. The coordinates should indicate the normalized pixel locations of the points in the image."
        elif task == "affordance":
            print("Affordance task detected. Adding affordance prompt.")
            text = f"You are a robot using the joint control. The task is \"{text}\". Please predict a possible affordance area of the end effector."
        elif task == "trajectory":
            print("Trajectory task detected. Adding trajectory prompt.")
            text = f"You are a robot using the joint control. The task is \"{text}\". Please predict up to 10 key trajectory points to complete the task. Your answer should be formatted as a list of tuples, i.e. [[x1, y1], [x2, y2], ...], where each tuple contains the x and y coordinates of a point."
        elif task == "grounding":
            print("Grounding task detected. Adding grounding prompt.")
            text = f"Please provide the bounding box coordinate of the region this sentence describes: {text}."

        print(f"\n{'='*20} INPUT {'='*20}\n{text}\n{'='*47}\n")

        messages = [
            {
                "role": "user",
                "content": [
                    *[
                        {"type": "image", 
                         "image": path if path.startswith("http") else f"file://{path}"
                        } for path in image
                    ],
                    {"type": "text", "text": f"{text}"},
                ],
            },
        ]

        text = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )

        if enable_thinking:
            print("Thinking enabled.")
            text = f"{text}<think>"
        elif self.supports_thinking:
            print("Thinking disabled (but supported).")
            text = f"{text}<think></think><answer>"

        image_inputs, video_inputs = process_vision_info(messages)
        inputs = self.processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        )
        inputs = inputs.to("cuda")

        # Inference
        print("Running inference ...")
        generated_ids = self.model.generate(**inputs, max_new_tokens=768, do_sample=do_sample, temperature=temperature)
        generated_ids_trimmed = [
            out_ids[len(in_ids) :] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
        ]
        output_text = self.processor.batch_decode(
            generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )

        if enable_thinking and self.supports_thinking:
            raw_output = output_text[0] if output_text else ""
            if "</think>" in raw_output:
                thinking_text = raw_output.split("</think>")[0].replace("<think>", "").strip()
                answer_text = raw_output.split("</think>")[1].replace("<answer>", "").replace("</answer>", "").strip()
            else:
                thinking_text = raw_output.replace("<think>", "").strip()
                answer_text = ""
        elif self.supports_thinking:
            # Thinking disabled but supported
            raw_output = output_text[0] if output_text else ""
            thinking_text = ""
            answer_text = raw_output.replace("<answer>", "").replace("</answer>", "").strip()
        else:
            # No thinking support (3B models)
            raw_output = output_text[0] if output_text else ""
            thinking_text = ""
            answer_text = raw_output

        # print(f"Raw output: {output_text}")
        # if thinking_text:
        #     print(f"Thinking: {thinking_text}")
        # print(f"Answer: {answer_text}")

        # Plotting functionality
        if plot and task in ["pointing", "affordance", "trajectory", "grounding"]:
            print("Plotting enabled. Drawing results on the image ...")
            
            plot_points, plot_boxes, plot_trajectories = None, None, None
            result_text = answer_text  # Use the processed answer text for plotting
            
            if task == "trajectory":
                trajectory_pattern = r'(\d+),\s*(\d+)'
                trajectory_points = re.findall(trajectory_pattern, result_text)
                plot_trajectories = [[(int(x), int(y)) for x, y in trajectory_points]]
                print(f"Extracted trajectory points: {plot_trajectories}")
                image_name_to_save = os.path.basename(image[0]).replace(".", "_with_trajectory_annotated.")
            elif task == "pointing":
                point_pattern = r'\(\s*(\d+)\s*,\s*(\d+)\s*\)'
                points = re.findall(point_pattern, result_text)
                plot_points = [(int(x), int(y)) for x, y in points]
                print(f"Extracted points: {plot_points}")
                image_name_to_save = os.path.basename(image[0]).replace(".", "_with_pointing_annotated.")
            elif task == "affordance":
                box_pattern = r'\[\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]'
                boxes = re.findall(box_pattern, result_text)
                plot_boxes = [[int(x1), int(y1), int(x2), int(y2)] for x1, y1, x2, y2 in boxes]
                print(f"Extracted bounding boxes: {plot_boxes}")
                image_name_to_save = os.path.basename(image[0]).replace(".", "_with_affordance_annotated.")
            elif task == "grounding":
                box_pattern = r'\[\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]'
                boxes = re.findall(box_pattern, result_text)
                plot_boxes = [[int(x1), int(y1), int(x2), int(y2)] for x1, y1, x2, y2 in boxes]
                print(f"Extracted bounding boxes: {plot_boxes}")
                image_name_to_save = os.path.basename(image[0]).replace(".", "_with_grounding_annotated.")

            os.makedirs("result", exist_ok=True)
            image_path_to_save = os.path.join("result", image_name_to_save)

            self.draw_on_image(
                image[0], 
                points=plot_points, 
                boxes=plot_boxes, 
                trajectories=plot_trajectories,
                output_path=image_path_to_save
            )

        # Return unified format
        result = {"answer": answer_text}
        if thinking_text:
            result["thinking"] = thinking_text
        
        return result

    def draw_on_image(self, image_path, points=None, boxes=None, trajectories=None, output_path=None):
        """
        Draw points, bounding boxes, and trajectories on an image
        
        Parameters:
            image_path: Path to the input image
            points: List of points in format [(x1, y1), (x2, y2), ...]
            boxes: List of boxes in format [[x1, y1, x2, y2], [x1, y1, x2, y2], ...]
            trajectories: List of trajectories in format [[(x1, y1), (x2, y2), ...], [...]]
            output_path: Path to save the output image. Default adds "_annotated" suffix to input path
        """
        try:
            # Read the image
            image = cv2.imread(image_path)
            if image is None:
                raise FileNotFoundError(f"Unable to read image: {image_path}")
            
            # Draw points
            if points:
                for point in points:
                    x, y = point
                    cv2.circle(image, (x, y), 5, (0, 0, 255), -1)  # Red solid circle
            
            # Draw bounding boxes
            if boxes:
                for box in boxes:
                    x1, y1, x2, y2 = box
                    cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)  # Green box, line width 2
            
            # Draw trajectories
            if trajectories:
                for trajectory in trajectories:
                    if len(trajectory) < 2:
                        continue  # Need at least 2 points to form a trajectory
                    # Connect trajectory points with lines
                    for i in range(1, len(trajectory)):
                        cv2.line(image, trajectory[i-1], trajectory[i], (255, 0, 0), 2)  # Blue line, width 2
                    # Draw a larger point at the trajectory end
                    end_x, end_y = trajectory[-1]
                    cv2.circle(image, (end_x, end_y), 7, (255, 0, 0), -1)  # Blue solid circle, slightly larger
            
            # Determine output path
            if not output_path:
                name, ext = os.path.splitext(image_path)
                output_path = f"{name}_annotated{ext}"
            
            # Save the result
            cv2.imwrite(output_path, image)
            print(f"Annotated image saved to: {output_path}")
            return output_path
            
        except Exception as e:
            print(f"Error processing image: {e}")
            return None


# Usage examples
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true", help="Start OpenAI-compatible server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=4567)
    parser.add_argument("--model-id", default="/home/phl/workspace/models/RoboBrain2.0-7B")
    parser.add_argument("--device-map", default="auto")
    parser.add_argument("--enable-thinking", action="store_true")
    parser.add_argument("--load-in-4bit", action="store_true", help="Load model in 4-bit quantization to save memory")
    parser.add_argument("--max-gpu-memory", type=str, help="Maximum GPU memory to use (e.g., '6GiB') to avoid OOM")
    args = parser.parse_args()

    if args.serve:
        from fastapi import FastAPI
        from pydantic import BaseModel
        import uvicorn

        app = FastAPI()
        model = UnifiedInference(
            model_id=args.model_id,
            device_map=args.device_map,
            load_in_4bit=args.load_in_4bit,
            max_memory=args.max_gpu_memory
        )

        class ChatMessage(BaseModel):
            role: str
            content: Union[str, list]
            model_config = {"extra": "allow"}

        class ChatRequest(BaseModel):
            model: str | None = None
            messages: list[ChatMessage]
            temperature: float | None = None
            tools: list | None = None
            tool_choice: object | None = None
            max_tokens: int | None = None
            top_p: float | None = None
            stop: list[str] | str | None = None
            model_config = {"extra": "allow"}

        def _extract_user_text_and_images(messages: list[ChatMessage]) -> tuple[str, list[str]]:
            text_parts = []
            images: list[str] = []
            for msg in messages:
                if msg.role != "user":
                    continue
                if isinstance(msg.content, str):
                    text_parts.append(msg.content)
                else:
                    for item in msg.content:
                        if item.get("type") == "text":
                            text_parts.append(item.get("text", ""))
                        elif item.get("type") == "image":
                            img = item.get("image", "")
                            if img:
                                images.append(img.replace("file://", ""))
            return "\n".join(text_parts).strip(), images

        def _extract_task_focus_text(prompt: str) -> str:
            patterns = [
                r"# The task to be completed is:\s*(.+?)\.\s*Your output answer:",
                r"Task:\s*(.+?)(?:\n\n|$)",
            ]
            for pattern in patterns:
                match = re.search(pattern, prompt, re.IGNORECASE | re.DOTALL)
                if match:
                    return match.group(1).strip()
            return prompt.strip()

        def _match_keyword(text: str, keywords: list[str]) -> bool:
            return any(keyword in text for keyword in keywords)

        def _build_master_plan(task_text: str) -> str | None:
            task_lower = task_text.lower()
            reasoning = (
                "This task is a short single-robot motion request for gr2_sim. "
                "The safest baseline decomposition is to keep it as one executable subtask "
                "that directly maps to the robot's currently supported upper-body control skill, "
                "instead of expanding it into navigation or manipulation steps that do not exist "
                "in the current baseline. The robot only exposes upper-body simulation tools such as "
                "connect_robot, move_named_pose, move_joints, get_joint_state, and related helpers. "
                "So the task should stay focused on one motion intent and be assigned entirely to gr2_sim."
            )

            if _match_keyword(task_lower, ["right arm", "右臂", "右胳膊", "右手臂"]):
                return json.dumps(
                    {
                        "reasoning_explanation": reasoning,
                        "subtask_list": [
                            {
                                "robot_name": "gr2_sim",
                                "subtask": "Raise the right arm of gr2_sim a little.",
                                "subtask_order": 1,
                            }
                        ],
                    },
                    ensure_ascii=False,
                )

            if _match_keyword(task_lower, ["left arm", "左臂", "左胳膊", "左手臂"]):
                return json.dumps(
                    {
                        "reasoning_explanation": reasoning,
                        "subtask_list": [
                            {
                                "robot_name": "gr2_sim",
                                "subtask": "Raise the left arm of gr2_sim a little.",
                                "subtask_order": 1,
                            }
                        ],
                    },
                    ensure_ascii=False,
                )

            if _match_keyword(task_lower, ["connect", "连接机器人", "启动仿真", "连接仿真"]):
                return json.dumps(
                    {
                        "reasoning_explanation": reasoning,
                        "subtask_list": [
                            {
                                "robot_name": "gr2_sim",
                                "subtask": "Connect the gr2_sim robot.",
                                "subtask_order": 1,
                            }
                        ],
                    },
                    ensure_ascii=False,
                )

            if _match_keyword(task_lower, ["disconnect", "断开机器人", "停止仿真连接"]):
                return json.dumps(
                    {
                        "reasoning_explanation": reasoning,
                        "subtask_list": [
                            {
                                "robot_name": "gr2_sim",
                                "subtask": "Disconnect the gr2_sim robot.",
                                "subtask_order": 1,
                            }
                        ],
                    },
                    ensure_ascii=False,
                )

            if _match_keyword(task_lower, ["look left", "向左看", "看左边", "左看"]):
                return json.dumps(
                    {
                        "reasoning_explanation": reasoning,
                        "subtask_list": [
                            {
                                "robot_name": "gr2_sim",
                                "subtask": "Turn the head of gr2_sim to the left.",
                                "subtask_order": 1,
                            }
                        ],
                    },
                    ensure_ascii=False,
                )

            if _match_keyword(task_lower, ["look right", "向右看", "看右边", "右看"]):
                return json.dumps(
                    {
                        "reasoning_explanation": reasoning,
                        "subtask_list": [
                            {
                                "robot_name": "gr2_sim",
                                "subtask": "Turn the head of gr2_sim to the right.",
                                "subtask_order": 1,
                            }
                        ],
                    },
                    ensure_ascii=False,
                )

            return None

        def _select_tool_call(task_text: str, tool_names: list[str]) -> tuple[str | None, dict]:
            task_lower = task_text.lower()
            tool_set = set(tool_names)

            if "list_named_poses" in tool_set and _match_keyword(
                task_lower, ["list poses", "named poses", "available poses", "有哪些姿态", "列出姿态"]
            ):
                return "list_named_poses", {}

            if "get_joint_state" in tool_set and _match_keyword(
                task_lower, ["joint state", "joint positions", "当前关节", "关节状态", "当前姿态"]
            ):
                return "get_joint_state", {}

            if "disconnect_robot" in tool_set and _match_keyword(
                task_lower, ["disconnect", "stop robot", "断开", "停止连接"]
            ):
                return "disconnect_robot", {}

            if "connect_robot" in tool_set and _match_keyword(
                task_lower, ["connect", "启动机器人", "连接机器人", "启动仿真", "连接仿真"]
            ):
                return "connect_robot", {}

            if "move_named_pose" in tool_set:
                if _match_keyword(task_lower, ["upper_body_ready", "ready pose", "准备姿态", "准备位置"]):
                    return "move_named_pose", {"name": "upper_body_ready"}
                if _match_keyword(task_lower, ["home pose", "go home", "回到初始", "回到home", "复位"]):
                    return "move_named_pose", {"name": "home"}
                if _match_keyword(task_lower, ["look left", "看左边", "向左看", "左看"]):
                    return "move_named_pose", {"name": "look_left"}
                if _match_keyword(task_lower, ["look right", "看右边", "向右看", "右看"]):
                    return "move_named_pose", {"name": "look_right"}
                if _match_keyword(
                    task_lower,
                    ["right arm", "right hand", "右臂", "右胳膊", "右手臂"],
                ):
                    return "move_named_pose", {"name": "right_arm_up"}
                if _match_keyword(
                    task_lower,
                    ["left arm", "left hand", "左臂", "左胳膊", "左手臂"],
                ):
                    return "move_named_pose", {"name": "left_arm_up"}

            for name in tool_names:
                if name and name.lower() in task_lower:
                    return name, {}

            return None, {}

        @app.post("/v1/chat/completions")
        def chat_completions(req: ChatRequest):
            prompt, images = _extract_user_text_and_images(req.messages)
            task_text = _extract_task_focus_text(prompt)
            tool_list = req.tools or []
            tool_names = [
                t.get("function", {}).get("name", "")
                for t in tool_list
                if isinstance(t, dict)
            ]
            selected_tool, tool_args = _select_tool_call(task_text, tool_names)

            if not tool_list and "Please break down the given task into sub-tasks" in prompt:
                planned = _build_master_plan(task_text)
                if planned is not None:
                    return {
                        "id": "robobrain-chatcmpl",
                        "object": "chat.completion",
                        "model": args.model_id,
                        "usage": {
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                            "total_tokens": 0,
                        },
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": planned},
                                "finish_reason": "stop",
                            }
                        ],
                    }

            if selected_tool == "wait":
                match = re.search(r"(\d+(?:\.\d+)?)", task_text.lower())
                if match:
                    tool_args = {"seconds": float(match.group(1))}
                else:
                    tool_args = {}

            if selected_tool and selected_tool in tool_names:
                return {
                    "id": "robobrain-chatcmpl",
                    "object": "chat.completion",
                    "model": args.model_id,
                    "usage": {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                    },
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "call_0",
                                        "type": "function",
                                        "function": {
                                            "name": selected_tool,
                                            "arguments": json.dumps(tool_args),
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                }

            temp = req.temperature if req.temperature is not None else 0.7
            do_sample = temp is not None and temp > 0
            result = model.inference(
                prompt,
                images,
                task="general",
                enable_thinking=args.enable_thinking,
                do_sample=do_sample,
                temperature=temp if temp > 0 else 1.0,
            )
            content = result.get("answer", "")
            return {
                "id": "robobrain-chatcmpl",
                "object": "chat.completion",
                "model": args.model_id,
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
            }

        uvicorn.run(app, host=args.host, port=args.port)
    else:
        print("=== Testing 7B Model ===")
        model_7b = UnifiedInference("/home/phl/workspace/models/RoboBrain2.0-7B")
        prompt = "What is shown in this image?"
        image = "http://images.cocodataset.org/val2017/000000039769.jpg"
        pred_7b = model_7b.inference(prompt, image, task="general", enable_thinking=True)
        print(f"7B Prediction:\\n{pred_7b}")
