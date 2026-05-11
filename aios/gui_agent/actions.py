"""UI-TARS compatible action parsing for TaijiOS GUI agents."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Action:
    """A parsed GUI action proposed by a visual model."""

    action_type: str
    inputs: dict[str, Any] = field(default_factory=dict)
    thought: str = ""
    reflection: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.action_type in {"finished", "call_user", "error_env", "max_loop", "user_stop"}


class ActionParser:
    """Parse UI-TARS style model output into structured actions."""

    def __init__(
        self,
        factors: tuple[int, int] = (1000, 1000),
        scale_factor: float = 1.0,
    ):
        self.factors = factors
        self.scale_factor = scale_factor

    def parse(
        self,
        prediction: str,
        screen_width: int | None = None,
        screen_height: int | None = None,
    ) -> list[Action]:
        text = prediction.strip()
        thought, reflection, action_text = self._split_prediction(text)
        actions: list[Action] = []

        for raw in self._split_action_calls(action_text):
            raw = raw.strip()
            if not raw:
                continue
            parsed = self._parse_call(raw)
            if parsed is None:
                continue
            action_type, inputs = parsed
            self._attach_screen_coords(inputs, screen_width, screen_height)
            actions.append(
                Action(
                    action_type=action_type,
                    inputs=inputs,
                    thought=thought,
                    reflection=reflection,
                )
            )

        return actions

    def _split_action_calls(self, action_text: str) -> list[str]:
        """Split one or more model-emitted action calls."""
        chunks: list[str] = []
        current: list[str] = []
        quote: str | None = None
        paren_depth = 0

        for char in action_text.strip():
            if char in {"'", '"'}:
                quote = None if quote == char else char if quote is None else quote
            elif quote is None:
                if char == "(":
                    paren_depth += 1
                elif char == ")" and paren_depth:
                    paren_depth -= 1
                    current.append(char)
                    if paren_depth == 0:
                        chunk = "".join(current).strip()
                        if chunk:
                            chunks.append(chunk)
                        current = []
                    continue
            if current or not char.isspace():
                current.append(char)

        trailing = "".join(current).strip()
        if trailing:
            chunks.append(trailing)
        return chunks

    def _split_prediction(self, text: str) -> tuple[str, str | None, str]:
        thought = ""
        reflection: str | None = None
        action_text = text

        reflection_match = re.search(
            r"Reflection:\s*([\s\S]+?)Action_Summary:\s*([\s\S]+?)(?=\s*Action[:：]|$)",
            text,
        )
        if reflection_match:
            reflection = reflection_match.group(1).strip()
            thought = reflection_match.group(2).strip()
        else:
            thought_match = re.search(
                r"Thought:\s*([\s\S]+?)(?=\s*Action[:：]|$)",
                text,
            )
            if thought_match:
                thought = thought_match.group(1).strip()
            else:
                summary_match = re.search(
                    r"Action_Summary:\s*([\s\S]+?)(?=\s*Action[:：]|$)",
                    text,
                )
                if summary_match:
                    thought = summary_match.group(1).strip()

        parts = re.split(r"Action[:：]", text)
        if len(parts) > 1:
            action_text = parts[-1]

        return thought, reflection, action_text

    def _parse_call(self, action_text: str) -> tuple[str, dict[str, Any]] | None:
        normalized = (
            action_text.replace("<|box_start|>", "")
            .replace("<|box_end|>", "")
            .replace("start_point=", "start_box=")
            .replace("end_point=", "end_box=")
        )
        normalized = re.sub(r"(?<!start_)(?<!end_)point=", "start_box=", normalized)

        match = re.match(r"^(\w+)\((.*)\)$", normalized.strip(), flags=re.DOTALL)
        if not match:
            return None

        action_type = match.group(1)
        args = self._parse_kwargs(match.group(2))
        return action_type, args

    def _parse_kwargs(self, args_text: str) -> dict[str, Any]:
        if not args_text.strip():
            return {}

        args: dict[str, Any] = {}
        for key, value in self._split_kwargs(args_text):
            value = value.strip().strip("\"'")
            value = self._normalize_box_markup(value)
            args[key.strip()] = value
        return args

    def _split_kwargs(self, args_text: str) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        current: list[str] = []
        quote: str | None = None
        bracket_depth = 0

        for char in args_text:
            if char in {"'", '"'}:
                quote = None if quote == char else char if quote is None else quote
            elif quote is None:
                if char in "([{":
                    bracket_depth += 1
                elif char in ")]}" and bracket_depth:
                    bracket_depth -= 1
                elif char == "," and bracket_depth == 0:
                    self._append_pair(pairs, "".join(current))
                    current = []
                    continue
            current.append(char)

        self._append_pair(pairs, "".join(current))
        return pairs

    @staticmethod
    def _append_pair(pairs: list[tuple[str, str]], chunk: str) -> None:
        if "=" not in chunk:
            return
        key, value = chunk.split("=", 1)
        if key.strip():
            pairs.append((key, value))

    @staticmethod
    def _normalize_box_markup(value: str) -> str:
        if "<bbox>" in value:
            content = value.replace("<bbox>", "").replace("</bbox>", "")
            return f"({','.join(content.split())})"
        if "<point>" in value:
            content = value.replace("<point>", "").replace("</point>", "")
            return f"({','.join(content.split())})"
        return value

    def _attach_screen_coords(
        self,
        inputs: dict[str, Any],
        screen_width: int | None,
        screen_height: int | None,
    ) -> None:
        if not screen_width or not screen_height:
            return

        for box_key, coords_key in (("start_box", "start_coords"), ("end_box", "end_coords")):
            box = inputs.get(box_key)
            if not isinstance(box, str):
                continue
            coords = self.box_to_screen_coords(box, screen_width, screen_height)
            if coords is not None:
                inputs[coords_key] = coords

    def box_to_screen_coords(
        self,
        box: str,
        screen_width: int,
        screen_height: int,
    ) -> tuple[float, float] | None:
        numbers = [
            float(item)
            for item in re.findall(r"-?\d+(?:\.\d+)?", box)
        ]
        if len(numbers) == 2:
            x1, y1 = numbers
            x2, y2 = x1, y1
        elif len(numbers) >= 4:
            x1, y1, x2, y2 = numbers[:4]
        else:
            return None

        width_factor, height_factor = self.factors
        x = ((x1 + x2) / 2 / width_factor) * screen_width * self.scale_factor
        y = ((y1 + y2) / 2 / height_factor) * screen_height * self.scale_factor
        return (round(x, 2), round(y, 2))
