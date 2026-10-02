"""操作日志（撤销用）：所有移动/重命名都记批次，可整批回滚。"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import DATA_DIR, JOURNAL_PATH

MAX_BATCHES = 200


@dataclass
class Move:
    src: str
    dst: str


@dataclass
class Batch:
    id: str
    action: str  # archive | rename
    note: str
    created_at: float
    moves: list[Move] = field(default_factory=list)
    undone: bool = False
    undone_at: float = 0.0


class Journal:
    """JSON 文件形式的操作台账。"""

    def __init__(self, path: Path = JOURNAL_PATH) -> None:
        self.path = Path(path)
        self._batches: list[Batch] = []
        self.load()

    # ---------- 持久化 ----------

    def load(self) -> None:
        self._batches = []
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        for item in raw.get("batches", []):
            try:
                moves = [Move(**m) for m in item.get("moves", [])]
                self._batches.append(
                    Batch(
                        id=str(item.get("id", uuid.uuid4().hex)),
                        action=str(item.get("action", "?")),
                        note=str(item.get("note", "")),
                        created_at=float(item.get("created_at", 0)),
                        moves=moves,
                        undone=bool(item.get("undone", False)),
                        undone_at=float(item.get("undone_at", 0)),
                    )
                )
            except Exception:
                continue

    def save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if len(self._batches) > MAX_BATCHES:
            self._batches = self._batches[-MAX_BATCHES:]
        payload = {"version": 1, "batches": [asdict(b) for b in self._batches]}
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    # ---------- 写入 ----------

    def record(self, action: str, moves: list[tuple[str, str]], note: str = "") -> Batch:
        batch = Batch(
            id=uuid.uuid4().hex[:12],
            action=action,
            note=note,
            created_at=time.time(),
            moves=[Move(str(a), str(b)) for a, b in moves],
        )
        self._batches.append(batch)
        self.save()
        return batch

    def mark_undone(self, batch_id: str) -> None:
        for b in self._batches:
            if b.id == batch_id:
                b.undone = True
                b.undone_at = time.time()
        self.save()

    # ---------- 查询 ----------

    @property
    def batches(self) -> list[Batch]:
        return list(self._batches)

    def last_undoable(self) -> Batch | None:
        for b in reversed(self._batches):
            if not b.undone and b.moves:
                return b
        return None

    def recent(self, n: int = 20) -> list[Batch]:
        return list(reversed(self._batches[-n:]))
