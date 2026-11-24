"""Local ASE/EMT calculation for a small periodic aluminum cell."""

import argparse
import json
from io import StringIO
from math import hypot

from ase.build import bulk
from ase.calculators.emt import EMT
from ase.io import write
from ase.optimize import BFGS

FORCE_THRESHOLD = 0.03
MAX_STEPS = 60


def calculate_aluminum(calculation: str) -> dict:
    if calculation not in {"energy", "relaxation"}:
        raise ValueError("Unsupported calculation")

    atoms = bulk("Al", "fcc", a=4.05, cubic=True)
    atoms.positions[0] += [0.12, -0.06, 0.04]
    atoms.calc = EMT()
    initial_energy = float(atoms.get_potential_energy())
    initial_force = max(hypot(*force) for force in atoms.get_forces())
    steps = 0
    converged = None
    if calculation == "relaxation":
        optimizer = BFGS(atoms, logfile=None)
        converged = bool(optimizer.run(fmax=FORCE_THRESHOLD, steps=MAX_STEPS))
        steps = optimizer.get_number_of_steps()

    structure = StringIO()
    write(structure, atoms, format="extxyz", write_results=False)
    return {
        "material": "aluminum",
        "calculation": calculation,
        "backend": "ase",
        "method": "ASE EMT" if calculation == "energy" else "ASE EMT / BFGS",
        "atom_count": len(atoms),
        "energy_ev": float(atoms.get_potential_energy()),
        "initial_energy_ev": initial_energy,
        "max_force_ev_per_angstrom": max(hypot(*force) for force in atoms.get_forces()),
        "initial_max_force_ev_per_angstrom": initial_force,
        "force_threshold_ev_per_angstrom": FORCE_THRESHOLD if calculation == "relaxation" else None,
        "steps": steps,
        "converged": converged,
        "structure_xyz": structure.getvalue(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("calculation", choices=["energy", "relaxation"])
    args = parser.parse_args()
    print(json.dumps(calculate_aluminum(args.calculation), allow_nan=False))


if __name__ == "__main__":
    main()
