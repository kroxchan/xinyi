from collections import defaultdict
from datetime import datetime, timezone

from rich.console import Console

console = Console()


def _ts_to_str(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _role(is_sender: int) -> str:
    return "self" if is_sender else "other"


class ConversationBuilder:
    def __init__(
        self,
        time_gap_minutes: int = 30,
        max_turns: int = 15,
        min_turns: int = 3,
        twin_mode: str = "self",
    ) -> None:
        self.time_gap = time_gap_minutes * 60
        self.max_turns = max_turns
        self.min_turns = min_turns
        self.twin_mode = twin_mode

    def _is_twin_side(self, is_sender: int) -> bool:
        """该消息是否属于被训练方（twin）。"""
        if self.twin_mode == "partner":
            return is_sender == 0
        return is_sender == 1

    def _group_by_contact(self, messages: list[dict]) -> dict[str, list[dict]]:
        groups: dict[str, list[dict]] = defaultdict(list)
        for msg in messages:
            talker = msg.get("StrTalker", "")
            if talker:
                groups[talker].append(msg)
        for msgs in groups.values():
            msgs.sort(key=lambda m: m.get("CreateTime", 0))
        return groups

    def _split_segments(self, messages: list[dict]) -> list[list[dict]]:
        if not messages:
            return []

        segments: list[list[dict]] = [[messages[0]]]
        for msg in messages[1:]:
            prev_time = segments[-1][-1].get("CreateTime", 0)
            curr_time = msg.get("CreateTime", 0)

            if curr_time - prev_time > self.time_gap or len(segments[-1]) >= self.max_turns:
                segments.append([msg])
            else:
                segments[-1].append(msg)

        return [seg for seg in segments if len(seg) >= self.min_turns]

    def build_conversations(
        self, messages: list[dict], skip_chatrooms: bool = False,
    ) -> list[dict]:
        groups = self._group_by_contact(messages)
        conversations: list[dict] = []
        skipped_no_self = 0
        skipped_chatroom = 0
        included_chatroom_segments = 0
        conv_id = 0

        for contact, msgs in groups.items():
            is_chatroom = "@chatroom" in contact

            if skip_chatrooms and is_chatroom:
                skipped_chatroom += len(msgs)
                continue

            for segment in self._split_segments(msgs):
                has_twin = any(self._is_twin_side(m.get("IsSender", 0)) for m in segment)
                if not has_twin:
                    skipped_no_self += 1
                    continue

                if is_chatroom:
                    included_chatroom_segments += 1

                turns = [
                    {
                        "role": "self" if self._is_twin_side(m.get("IsSender", 0)) else "other",
                        "content": m.get("StrContent", ""),
                        "timestamp": _ts_to_str(m.get("CreateTime", 0)),
                    }
                    for m in segment
                ]
                text = "\n".join(
                    f"{'我' if t['role'] == 'self' else '对方'}: {t['content']}" for t in turns
                )

                conv_id += 1
                conversations.append(
                    {
                        "id": f"conv_{conv_id:04d}",
                        "contact": contact,
                        "start_time": turns[0]["timestamp"],
                        "end_time": turns[-1]["timestamp"],
                        "turn_count": len(turns),
                        "turns": turns,
                        "text": text,
                    }
                )

        parts = [
            f"构建对话段: {len(conversations)} 段",
            f"来自 {len(groups)} 个联系人",
        ]
        if included_chatroom_segments:
            parts.append(f"含群聊 {included_chatroom_segments} 段")
        if skipped_no_self:
            parts.append(f"跳过 {skipped_no_self} 段无自己发言")
        if skipped_chatroom:
            parts.append(f"跳过群聊 {skipped_chatroom} 条")
        console.print(f"[green]{' | '.join(parts)}[/green]")
        return conversations

    def build_qa_pairs(self, messages: list[dict]) -> list[dict]:
        groups = self._group_by_contact(messages)
        qa_pairs: list[dict] = []

        for msgs in groups.values():
            merged = self._merge_consecutive(msgs)
            for i in range(len(merged) - 1):
                curr = merged[i]
                nxt = merged[i + 1]
                if self._is_twin_side(nxt["IsSender"]) and not self._is_twin_side(curr["IsSender"]):
                    qa_pairs.append(
                        {
                            "question": curr["StrContent"],
                            "answer": nxt["StrContent"],
                        }
                    )

        console.print(f"[green]构建问答对: {len(qa_pairs)} 对[/green]")
        return qa_pairs

    def _merge_consecutive(self, messages: list[dict]) -> list[dict]:
        if not messages:
            return []

        merged: list[dict] = [
            {
                "IsSender": messages[0].get("IsSender", 0),
                "StrContent": messages[0].get("StrContent", ""),
                "CreateTime": messages[0].get("CreateTime", 0),
            }
        ]

        for msg in messages[1:]:
            sender = msg.get("IsSender", 0)
            content = msg.get("StrContent", "")
            if sender == merged[-1]["IsSender"]:
                merged[-1]["StrContent"] += "\n" + content
            else:
                merged.append(
                    {
                        "IsSender": sender,
                        "StrContent": content,
                        "CreateTime": msg.get("CreateTime", 0),
                    }
                )

        return merged
