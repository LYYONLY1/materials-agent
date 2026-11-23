from dataclasses import dataclass


@dataclass(frozen=True)
class Reference:
    material: str
    aliases: tuple[str, ...]
    title: str
    summary: str
    url: str


REFERENCES = (
    Reference(
        "silicon", ("硅", "silicon", "si"), "Silicon · PubChem",
        "硅是元素 Si。示例工作流可以对它提交几何优化或能量计算任务。",
        "https://pubchem.ncbi.nlm.nih.gov/element/Silicon",
    ),
    Reference(
        "aluminum", ("铝", "aluminum", "aluminium", "al"), "Aluminum · PubChem",
        "铝是元素 Al。此处的资料卡只提供元素信息，模拟结果不代表材料性质。",
        "https://pubchem.ncbi.nlm.nih.gov/element/Aluminum",
    ),
    Reference(
        "iron", ("铁", "iron", "fe"), "Iron · PubChem",
        "铁是元素 Fe。示例计算用于验证任务执行，不用于预测铁的性质。",
        "https://pubchem.ncbi.nlm.nih.gov/element/Iron",
    ),
)
MATERIALS = {reference.material: reference for reference in REFERENCES}


def search_reference(material: str | None) -> dict | None:
    reference = MATERIALS.get(material or "")
    if reference is None:
        return None
    return {"title": reference.title, "summary": reference.summary, "url": reference.url}
