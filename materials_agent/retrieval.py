"""Small bilingual sparse index for the local, curated knowledge base."""

import math
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from .catalog import REFERENCES


@dataclass(frozen=True)
class Chunk:
    id: str
    material: str | None
    title: str
    text: str
    url: str | None
    phrases: tuple[str, ...]


CHUNKS = (
    *(Chunk(
        f"{reference.material}-identity", reference.material, reference.title,
        reference.summary, reference.url,
        ("资料", "是什么", "元素", "化学符号", "atomic symbol", "element", "information"),
    ) for reference in REFERENCES),
    Chunk("silicon-structure", "silicon", "硅 · 晶体结构资料", (
        "常温常压下晶体硅通常采用金刚石立方结构。晶体结构描述的是原子在空间中的周期排列。"
    ), "https://www.webelements.com/silicon/crystal_structure.html",
        ("晶体结构", "金刚石", "diamond cubic", "crystal structure")),
    Chunk("aluminum-structure", "aluminum", "铝 · 晶体结构资料", (
        "常温常压下晶体铝为面心立方结构，常用缩写为 FCC。"
    ), "https://www.webelements.com/aluminium/crystal_structure.html",
        ("晶体结构", "面心立方", "fcc", "crystal structure")),
    Chunk("iron-structure", "iron", "铁 · 晶体结构资料", (
        "常温常压下的 α 铁为体心立方结构，常用缩写为 BCC。铁的晶体结构随温度和相而变化。"
    ), "https://www.webelements.com/iron/crystal_structure.html",
        ("晶体结构", "体心立方", "bcc", "crystal structure")),
    Chunk("guide-energy", None, "工作台 · 能量计算", (
        "模拟后端的评分没有能量单位，仅用于验证调度。结构实验室的 ASE / EMT 单点能量以 eV 表示，"
        "结果依赖输入结构和经验势。"
    ), None, ("能量单位", "能量计算", "能量评分", "energy score", "energy unit")),
    Chunk("guide-relaxation", None, "工作台 · 几何优化", (
        "几何优化（弛豫）迭代更新原子位置，直到最大受力满足收敛阈值或达到步数上限。"
        "结构实验室用 ASE BFGS 优化固定晶胞内的坐标，并导出计算前后的结构。"
    ), "https://ase.gitlab.io/ase/ase/optimize.html",
        ("几何优化", "弛豫", "原子位置", "力收敛", "force convergence", "relaxation")),
    Chunk("guide-retry", None, "工作台 · 任务重试", (
        "计算工具超时后最多重试一次。持续超时的任务进入失败状态。"
        "客户端可以用相同的幂等键重发同一请求并查询原任务。"
    ), None, ("工具超时", "超时之后", "任务重试", "幂等", "timeout", "retry", "idempotency")),
    Chunk("guide-recovery", None, "工作台 · 恢复与检查点", (
        "工作流在缺参数和等待审批时把状态存到检查点。后台 Worker 用租约领取任务，"
        "租约过期后的旧 Worker 结果会被拒绝。"
    ), None, ("检查点", "断线续跑", "进程重启", "租约", "checkpoint", "lease", "restart")),
)


def tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+|[\u3400-\u9fff]+", text.casefold())
    return [
        token for word in words
        for token in (
            [word] if word.isascii() or len(word) == 1
            else [word[index:index + 2] for index in range(len(word) - 1)]
        )
    ]


def grams(text: str) -> Counter:
    cleaned = " ".join(re.findall(r"[a-z0-9\u3400-\u9fff]+", text.casefold()))
    return Counter(cleaned[i:i + size] for size in (2, 3) for i in range(len(cleaned) - size + 1))


def cosine(query: Counter, document: Counter) -> float:
    dot = sum(count * document.get(term, 0) for term, count in query.items())
    norm = math.sqrt(sum(n * n for n in query.values()) * sum(n * n for n in document.values()))
    return dot / norm if norm else 0


class KnowledgeIndex:
    def __init__(self, chunks=CHUNKS):
        self.chunks = tuple(chunks)
        self.lexical = [Counter(tokens(chunk.title + " " + chunk.text)) for chunk in self.chunks]
        self.character = [grams(chunk.title + " " + chunk.text) for chunk in self.chunks]
        self.lengths = [sum(document.values()) for document in self.lexical]
        self.avg_length = sum(self.lengths) / len(self.chunks)
        self.df = Counter(term for document in self.lexical for term in document)

    def bm25(self, query: set[str], index: int) -> float:
        document = self.lexical[index]
        length_penalty = 1.5 * (0.25 + 0.75 * self.lengths[index] / self.avg_length)
        return sum(
            math.log1p((len(self.chunks) - self.df[term] + 0.5) / (self.df[term] + 0.5))
            * document[term] * 2.5 / (document[term] + length_penalty)
            for term in query if term in document
        )

    def search(self, query: str, material: str | None = None,
               *, mode: str = "hybrid", limit: int = 3) -> list[dict]:
        lexical_query, character_query = set(tokens(query)), grams(query)
        candidates = [
            i for i, chunk in enumerate(self.chunks)
            if material is None or chunk.material in (None, material)
        ]
        lexical = {i: self.bm25(lexical_query, i) for i in candidates}
        character = {i: cosine(character_query, self.character[i]) for i in candidates}

        def ranks(scores):
            return {
                index: rank for rank, (index, _) in enumerate(
                    sorted((item for item in scores.items() if item[1] > 0),
                           key=lambda item: (-item[1], self.chunks[item[0]].id)), 1)
            }

        lexical_rank, character_rank = ranks(lexical), ranks(character)
        normalized = query.casefold()
        hits = []
        for i in candidates:
            chunk = self.chunks[i]
            matched = [phrase for phrase in chunk.phrases if phrase in normalized]
            if chunk.id.endswith("-identity") and material is None:
                matched = []
            if mode == "bm25":
                score = lexical[i]
            else:
                score = sum(1 / (10 + ranking[i])
                            for ranking in (lexical_rank, character_rank) if i in ranking)
                score += 0.25 * len(matched)
            if score <= 0 or (
                mode == "hybrid" and not matched and lexical[i] == 0 and character[i] < 0.18
            ):
                continue
            hit = asdict(chunk)
            hit.pop("phrases")
            hit.update({"score": round(score, 5), "matched_phrases": matched})
            hits.append(hit)
        return sorted(hits, key=lambda hit: (-hit["score"], hit["id"]))[:limit]


INDEX = KnowledgeIndex()


def markdown_chunks(path: Path, *, size: int = 450, overlap: int = 60) -> list[Chunk]:
    text = path.read_text(encoding="utf-8")
    sections = re.split(r"(?m)^#{1,6}\s+(.+?)\s*$", text)
    named = [(path.stem, sections[0]), *zip(sections[1::2], sections[2::2])]
    chunks = []
    for heading, body in named:
        body = " ".join(body.split())
        if not body:
            continue
        for start in range(0, len(body), size - overlap):
            chunks.append(Chunk(
                f"md:{path.name}:{len(chunks) + 1}", None,
                f"{path.stem} · {heading}", body[start:start + size], None, (),
            ))
            if start + size >= len(body):
                break
    return chunks


def configured_index() -> KnowledgeIndex:
    directory = os.getenv("MATERIALS_KNOWLEDGE_DIR")
    if not directory:
        return INDEX
    folder = Path(directory)
    if not folder.is_dir():
        raise ValueError("MATERIALS_KNOWLEDGE_DIR must be a directory")
    paths = sorted(p for p in folder.glob("*.md") if p.is_file() and not p.is_symlink())
    if len(paths) > 40 or any(path.stat().st_size > 64_000 for path in paths):
        raise ValueError("Knowledge import accepts up to 40 Markdown files of up to 64 KB each")
    return KnowledgeIndex([*CHUNKS, *(chunk for path in paths for chunk in markdown_chunks(path))])
