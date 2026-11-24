from math import hypot, isfinite
from typing import Literal

from pydantic import BaseModel, Field

METALS = ("Al", "Ni", "Cu", "Pd", "Ag", "Pt", "Au")
MAX_ATOMS = 128


class StructureRequest(BaseModel):
    xyz: str = Field(min_length=1, max_length=16000)
    cell: float = Field(ge=2.5, le=35)


class ExperimentRequest(StructureRequest):
    calculation: Literal["energy", "relaxation"]
    approved: Literal[True]


def parse_structure(source: str, cell: float):
    from ase import Atoms

    rows = source.strip().splitlines()
    try:
        count = int(rows[0])
    except (IndexError, ValueError) as error:
        raise ValueError("XYZ 首行应是原子数") from error
    if not 1 <= count <= MAX_ATOMS or len(rows) != count + 2:
        raise ValueError(f"仅支持单帧 XYZ，原子数需为 1–{MAX_ATOMS}，并与坐标行数一致")

    symbols = []
    positions = []
    for row in rows[2:]:
        columns = row.split()
        if len(columns) != 4 or columns[0] not in METALS:
            raise ValueError("每行需要元素和三个坐标。支持 Al、Ni、Cu、Pd、Ag、Pt、Au")
        try:
            coordinates = [float(value) for value in columns[1:]]
        except ValueError as error:
            raise ValueError("XYZ 坐标必须是数字") from error
        if any(not isfinite(value) or abs(value) > 1000 for value in coordinates):
            raise ValueError("坐标需为 ±1000 Å 内的有限数值")
        symbols.append(columns[0])
        positions.append(coordinates)

    atoms = Atoms(symbols, positions=positions, cell=[cell] * 3, pbc=True)
    distances = atoms.get_all_distances(mic=True)
    distances.flat[::count + 1] = float("inf")
    if distances.min() < 0.8:
        raise ValueError("周期边界下至少有两个原子间距小于 0.8 Å")
    atoms.wrap()
    return atoms


def max_force(atoms) -> float:
    return max(hypot(*force) for force in atoms.get_forces())
