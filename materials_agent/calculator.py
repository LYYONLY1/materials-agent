"""Run a local ASE/EMT calculation in an isolated process."""

import argparse
import json
import sys
from io import StringIO

from ase.build import bulk
from ase.calculators.emt import EMT
from ase.io import write
from ase.optimize import BFGS

from .structures import max_force, parse_structure

FORCE_THRESHOLD = 0.03
MAX_STEPS = 60


def structure_xyz(atoms) -> str:
    stream = StringIO()
    write(stream, atoms, format="extxyz", write_results=False)
    return stream.getvalue()


def calculate(atoms, calculation: str, *, material: str) -> dict:
    if calculation not in {"energy", "relaxation"}:
        raise ValueError("Unsupported calculation")
    initial_structure = structure_xyz(atoms)
    atoms.calc = EMT()
    trajectory = []

    def record():
        trajectory.append({
            "step": len(trajectory),
            "energy_ev": float(atoms.get_potential_energy()),
            "max_force_ev_per_angstrom": max_force(atoms),
        })

    converged = None
    if calculation == "relaxation":
        optimizer = BFGS(atoms, logfile=None)
        optimizer.attach(record, interval=1)
        converged = bool(optimizer.run(fmax=FORCE_THRESHOLD, steps=MAX_STEPS))
    else:
        record()

    initial, final = trajectory[0], trajectory[-1]
    return {
        "material": material,
        "calculation": calculation,
        "backend": "ase",
        "method": "ASE EMT" if calculation == "energy" else "ASE EMT / BFGS",
        "atom_count": len(atoms),
        "cell_angstrom": float(atoms.cell.lengths()[0]),
        "energy_ev": final["energy_ev"],
        "initial_energy_ev": initial["energy_ev"],
        "max_force_ev_per_angstrom": final["max_force_ev_per_angstrom"],
        "initial_max_force_ev_per_angstrom": initial["max_force_ev_per_angstrom"],
        "force_threshold_ev_per_angstrom": FORCE_THRESHOLD if calculation == "relaxation" else None,
        "steps": final["step"],
        "converged": converged,
        "initial_structure_xyz": initial_structure,
        "structure_xyz": structure_xyz(atoms),
        "trajectory": trajectory,
    }


def calculate_aluminum(calculation: str) -> dict:
    atoms = bulk("Al", "fcc", a=4.05, cubic=True)
    atoms.positions[0] += [0.12, -0.06, 0.04]
    return calculate(atoms, calculation, material="aluminum")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("calculation", choices=["energy", "relaxation"])
    parser.add_argument("--structure", action="store_true")
    args = parser.parse_args()
    if args.structure:
        data = json.load(sys.stdin)
        atoms = parse_structure(data["xyz"], data["cell"])
        result = calculate(atoms, args.calculation, material=atoms.get_chemical_formula())
    else:
        result = calculate_aluminum(args.calculation)
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
