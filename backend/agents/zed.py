import json
from typing import Dict, Any, Optional, Callable
from backend.agents.base import BaseAgent
from backend.agents.evaan import evaan_agent
from backend.agents.athena import athena_agent
from backend.agents.lumi import lumi_agent
from backend.config import settings
from backend.memory.db import db
from backend.tools.registry import registry, PermissionLevel


class ZedOrchestrator(BaseAgent):
    """
    Zed: Orchestrator & RoboNest Team Lead (Green #4cc48a).
    Coordinates user requests, plans multi-agent tasks, delegates to
    Evaan (Design), Athena (Architecture), and Lumi (Engineering),
    and delivers the consolidated outcome.
    """

    def __init__(self):
        super().__init__(
            name="Zed",
            role="Team Lead & Multi-Agent Orchestrator",
            prompt_filename="zed.md",
            allowed_tools=[
                "list_directory", "read_file",
                "list_calendar_events", "add_calendar_event",
                "git_status", "get_repo_info",
                "read_recent_emails", "send_email",
                "search_web", "list_drive_files"
            ]
        )
        self.team = {
            "evaan": evaan_agent,
            "athena": athena_agent,
            "lumi": lumi_agent
        }

    async def execute(
        self,
        task_id: str,
        instruction: str,
        context: Optional[str] = None,
        event_callback: Optional[Callable[[Dict[str, Any]], Any]] = None
    ) -> Dict[str, Any]:
        run_id = self.db.start_agent_run(task_id, self.name)
        self.db.update_task_status(task_id, "running")

        history = [
            {"role": "user", "content": f"Task: {instruction}\nContext: {context or 'None'}"}
        ]

        if event_callback:
            await self._emit_event(event_callback, {
                "type": "orchestrator_start",
                "task_id": task_id,
                "agent": self.name,
                "instruction": instruction
            })

        step = 0
        while step < self.max_steps:
            step += 1

            # Get Zed's decision
            llm_response = await self.llm.chat(
                messages=history[-settings.agent.history_limit:],
                system_prompt=self.system_prompt,
                enforce_json=True
            )

            if llm_response.get("error"):
                error_text = "Configured AI model failed: " + str(llm_response["error"])
                self.db.finish_agent_run(run_id, status="failed", summary=error_text, step_count=step)
                self.db.update_task_status(task_id, "failed", result=error_text)
                if event_callback:
                    await self._emit_event(event_callback, {
                        "type": "orchestrator_finish", "task_id": task_id,
                        "agent": self.name, "result": error_text
                    })
                return {"status": "failed", "task_id": task_id, "run_id": run_id,
                        "agent": self.name, "error": error_text, "steps": step}

            thought = llm_response.get("thought", "")
            action = llm_response.get("action", "finish")
            target_agent = str(llm_response.get("agent", "")).lower()
            agent_instruction = llm_response.get("instruction", "")
            tool_name = llm_response.get("tool")
            args = llm_response.get("args", {})
            response_text = llm_response.get("response", "") or llm_response.get("result", "")

            # 1. Delegation to team member
            if action == "delegate" and target_agent in self.team:
                worker = self.team[target_agent]
                self.db.log_step(run_id, task_id, self.name, step, thought, f"delegate_to_{worker.name}", worker.name, {"instruction": agent_instruction}, None)

                if event_callback:
                    await self._emit_event(event_callback, {
                        "type": "delegation",
                        "task_id": task_id,
                        "orchestrator": self.name,
                        "target_agent": worker.name,
                        "instruction": agent_instruction,
                        "thought": thought
                    })

                # Execute specialist agent
                worker_result = await worker.execute(
                    task_id=task_id,
                    instruction=agent_instruction or instruction,
                    context=f"Delegated by Zed. Original Goal: {instruction}",
                    event_callback=event_callback
                )

                if worker_result.get("status") == "waiting_approval":
                    self.db.finish_agent_run(run_id, status="blocked", summary=f"Paused: {worker.name} requires user approval", step_count=step)
                    return worker_result

                res_str = worker_result.get("result", "") or worker_result.get("error", "Completed")
                self.db.update_task_status(task_id, "running")
                history.append({"role": "assistant", "content": json.dumps(llm_response)})
                history.append({"role": "user", "content": f"Output from {worker.name}:\n{res_str}"})

            # 2. Tool execution by Zed
            elif action == "call_tool" and tool_name:
                tool = registry.get(tool_name)
                if not tool:
                    tool_output = f"Tool '{tool_name}' not found."
                elif tool.permission_level == PermissionLevel.ASK_USER:
                    approval_id = self.db.request_approval(
                        task_id=task_id,
                        run_id=run_id,
                        agent_name=self.name,
                        tool_name=tool_name,
                        tool_args=args,
                        reason=f"Zed tool '{tool_name}' requires approval."
                    )
                    self.db.finish_agent_run(run_id, status="blocked", summary=f"Waiting approval for {tool_name}", step_count=step)
                    return {
                        "status": "waiting_approval",
                        "approval_id": approval_id,
                        "task_id": task_id,
                        "run_id": run_id,
                        "agent": self.name,
                        "tool": tool_name
                    }
                else:
                    try:
                        tool_output = tool.handler(**args)
                    except Exception as e:
                        tool_output = f"Error: {e}"

                self.db.log_step(run_id, task_id, self.name, step, thought, "tool_call", tool_name, args, tool_output)
                self.db.update_task_status(task_id, "running")
                history.append({"role": "assistant", "content": json.dumps(llm_response)})
                history.append({"role": "user", "content": f"Result of {tool_name}:\n{tool_output}"})

            # 3. Finished
            else:
                final_output = response_text or thought
                self.db.log_step(run_id, task_id, self.name, step, thought, "finish", None, None, final_output)
                self.db.finish_agent_run(run_id, status="completed", summary=final_output, step_count=step)
                self.db.update_task_status(task_id, "completed", result=final_output)

                if event_callback:
                    await self._emit_event(event_callback, {
                        "type": "orchestrator_finish",
                        "task_id": task_id,
                        "agent": self.name,
                        "result": final_output
                    })

                return {
                    "status": "completed",
                    "task_id": task_id,
                    "run_id": run_id,
                    "agent": self.name,
                    "result": final_output,
                    "steps": step
                }

        # Step limit reached
        limit_msg = f"Task exceeded maximum step limit ({self.max_steps})."
        self.db.finish_agent_run(run_id, status="failed", summary=limit_msg, step_count=step)
        self.db.update_task_status(task_id, "failed", result=limit_msg)
        return {
            "status": "failed",
            "task_id": task_id,
            "error": limit_msg,
            "steps": step
        }

    async def run_pipeline(
        self,
        task_id: str,
        project_name: str,
        project_description: str,
        event_callback: Optional[Callable[[Dict[str, Any]], Any]] = None
    ) -> Dict[str, Any]:
        """
        Executes the 3-stage website pipeline:
        Stage 1: Evaan (Colors, Typography, Visual Theme)
        Stage 2: Athena (HTML Wireframe & Layout Skeleton)
        Stage 3: Lumi (JavaScript interactivity, event handlers & validation)
        """
        run_id = self.db.start_agent_run(task_id, self.name)
        self.db.update_task_status(task_id, "running")

        async def stop_if_stage_failed(result: Dict[str, Any]) -> bool:
            status = result.get("status", "failed")
            if status == "completed":
                return False
            detail = result.get("error") or result.get("result") or f"Project pipeline stopped ({status})."
            blocked = status == "waiting_approval"
            self.db.finish_agent_run(run_id, status="blocked" if blocked else "failed", summary=str(detail), step_count=0)
            self.db.update_task_status(task_id, "blocked" if blocked else "failed", result=str(detail))
            if event_callback:
                await self._emit_event(event_callback, {
                    "type": "orchestrator_finish", "task_id": task_id,
                    "agent": self.name, "result": str(detail)
                })
            return True

        # Stage 1: Evaan
        if event_callback:
            await self._emit_event(event_callback, {
                "type": "pipeline_stage",
                "stage": 1,
                "agent": "Evaan",
                "description": "Choosing colors, fonts, and visual theme"
            })
        evaan_res = await self.team["evaan"].execute(
            task_id=task_id,
            instruction=f"Design visual style, color palette, and layout tokens for: {project_name}. Description: {project_description}",
            event_callback=event_callback
        )
        if await stop_if_stage_failed(evaan_res):
            return evaan_res
        self.db.update_task_status(task_id, "running")

        # Stage 2: Athena
        if event_callback:
            await self._emit_event(event_callback, {
                "type": "pipeline_stage",
                "stage": 2,
                "agent": "Athena",
                "description": "Building semantic structure and layout wireframe"
            })
        athena_res = await self.team["athena"].execute(
            task_id=task_id,
            instruction=f"Build the semantic structure and layout for {project_name}. Preserve the user's requirements: {project_description}",
            context=f"User brief:\n{project_description}\n\nDesign direction from Evaan:\n{evaan_res.get('result', '')}",
            event_callback=event_callback
        )
        if await stop_if_stage_failed(athena_res):
            return athena_res
        self.db.update_task_status(task_id, "running")

        # Stage 3: Lumi
        if event_callback:
            await self._emit_event(event_callback, {
                "type": "pipeline_stage",
                "stage": 3,
                "agent": "Lumi",
                "description": "Adding interactive logic, JS handlers and testing"
            })
        lumi_res = await self.team["lumi"].execute(
            task_id=task_id,
            instruction=f"Implement the interactive behavior and logic for {project_name}, following the user's brief: {project_description}",
            context=f"User brief:\n{project_description}\n\nStructure from Athena:\n{athena_res.get('result', '')}",
            event_callback=event_callback
        )
        if await stop_if_stage_failed(lumi_res):
            return lumi_res

        final_summary = (
            f"Project '{project_name}' built successfully by RoboNest team.\n"
            f"- Design (Evaan): {str(evaan_res.get('result', ''))[:120]}...\n"
            f"- Architecture (Athena): {str(athena_res.get('result', ''))[:120]}...\n"
            f"- Engineering (Lumi): {str(lumi_res.get('result', ''))[:120]}..."
        )

        self.db.finish_agent_run(run_id, status="completed", summary=final_summary, step_count=3)
        self.db.update_task_status(task_id, "completed", result=final_summary)

        if event_callback:
            await self._emit_event(event_callback, {
                "type": "pipeline_complete",
                "task_id": task_id,
                "summary": final_summary
            })

        return {
            "status": "completed",
            "task_id": task_id,
            "project_name": project_name,
            "evaan": evaan_res,
            "athena": athena_res,
            "lumi": lumi_res,
            "summary": final_summary
        }


zed_orchestrator = ZedOrchestrator()
