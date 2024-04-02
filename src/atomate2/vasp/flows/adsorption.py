"""Flow for calculating surface adsorption energies."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from jobflow import Flow, Job, Maker

from atomate2.vasp.jobs.adsorption import (
    BulkRelaxMaker,
    MolRelaxMaker,
    MolStaticMaker,
    SlabRelaxMaker,
    SlabStaticMaker,
    adsorption_calculations,
    generate_adslabs,
    generate_slab,
)

if TYPE_CHECKING:
    from pathlib import Path

    from pymatgen.core.structure import Molecule, Structure

    from atomate2.forcefields.jobs import ForceFieldRelaxMaker, ForceFieldStaticMaker
    from atomate2.vasp.jobs.base import BaseVaspMaker


@dataclass
class AdsorptionMaker(Maker):
    """
    Workflow that calculates the adsorption energy of a molecule on a surface.

    The flow consists of the following steps:
    1. Optimize the molecule structure and calculate its static energy.
    2. Optimize the bulk structure.
    3. Generate a slab structure using the optimized bulk structure and calculate its static energy.
    4. Generate adsorption sites on the slab and calculate corresponding static energy.
    5. Calculate the adsorption energy by calculating the energy difference between the slab with
    adsorbed molecule and the sum of the slab without the adsorbed molecule and the molecule.

    Parameters
    ----------
    name: str
        Name of the flow.
    bulk_relax_maker: BaseVaspMaker
        Maker for bulk relaxation.
    mol_relax_maker: BaseVaspMaker
        Maker for molecule relaxation.
    slab_relax_maker: BaseVaspMaker
        Maker for slab relaxation with adsorption.
    slab_static_maker: BaseVaspMaker
        Maker for slab static energy calculation.
    mol_static_energy_maker: BaseVaspMaker
        Maker for molecule static energy calculation.
    """  # noqa: E501

    name: str = "adsorption workflow"

    mol_relax_maker: BaseVaspMaker | ForceFieldRelaxMaker | None = field(
        default_factory=MolRelaxMaker
    )

    mol_static_maker: BaseVaspMaker | ForceFieldStaticMaker | None = field(
        default_factory=MolStaticMaker
    )

    bulk_relax_maker: BaseVaspMaker | ForceFieldRelaxMaker | None = field(
        default_factory=BulkRelaxMaker
    )

    slab_relax_maker: BaseVaspMaker | ForceFieldRelaxMaker | None = field(
        default_factory=SlabRelaxMaker
    )

    slab_static_maker: BaseVaspMaker | ForceFieldStaticMaker | None = field(
        default_factory=SlabStaticMaker
    )

    def make(
        self,
        molecule: Molecule,
        structure: Structure,
        min_vacuum: float = 20.0,
        min_slab_size: float = 10.0,
        min_lw: float = 10.0,
        surface_idx: tuple[int, int, int] = (0, 0, 1),
        prev_dir_mol: str | Path | None = None,
        prev_dir_bulk: str | Path | None = None,
    ) -> Flow:
        """
        Generate a flow for calculating adsorption energies.

        Parameters
        ----------
        molecule: Molecule
            A pymatgen molecule object. The molecule to be adsorbed.
        structure: Structure
            A pymatgen structure object. The bulk structure to be used for slab generation.
        min_vacuum: float
            The minimum size of the vacuum region. In Angstroms or number of hkl planes.
        min_slab_size: float
            The minimum size of layers of the slab. In Angstroms or number of hkl planes.
        min_lw: float
            Minimum length and width of the slab
        surface_idx: tuple
            Miller index [h, k, l] of plane parallel to surface.
        prev_dir_mol: str or Path or None
            A previous VASP calculation directory to copy output files from.
        prev_dir_bulk: str or Path or None
            A previous VASP calculation directory to copy output files from.

        Returns
        -------
        Flow
            A flow object for calculating adsorption energies.
        """  # noqa: E501
        molecule_structure = molecule.get_boxed_structure(10, 10, 10)

        jobs: list[Job] = []

        if self.mol_relax_maker:
            mol_optimize_job = self.mol_relax_maker.make(
                molecule_structure, prev_dir=None
            )
            mol_optimize_job.append_name("molecule relaxation job")
            jobs += [mol_optimize_job]

            prev_dir = mol_optimize_job.output.dir_name
            optimized_molecule = mol_optimize_job.output.structure
        else:
            prev_dir = prev_dir_mol
            optimized_molecule = molecule_structure

        mol_static_job = self.mol_static_maker.make(
            molecule_structure, prev_dir=prev_dir
        )
        mol_static_job.append_name("molecule static job")
        jobs += [mol_static_job]

        molecule_dft_energy = mol_static_job.output.output.energy

        if self.bulk_relax_maker:
            bulk_optimize_job = self.bulk_relax_maker.make(
                structure, prev_dir=prev_dir_bulk
            )
            bulk_optimize_job.append_name("bulk relaxation job")
            jobs += [bulk_optimize_job]

            optimized_bulk = bulk_optimize_job.output.structure
        else:
            optimized_bulk = structure

        generate_slab_structure = generate_slab(
            bulk_structure=optimized_bulk,
            min_slab_size=min_slab_size,
            surface_idx=surface_idx,
            min_vacuum_size=min_vacuum,
            min_lw=min_lw,
        )
        # jobs += [generate_slab_structure]
        slab_structure = generate_slab_structure

        generate_adslabs_structures = generate_adslabs(
            bulk_structure=optimized_bulk,
            molecule_structure=optimized_molecule,
            min_slab_size=min_slab_size,
            surface_idx=surface_idx,
            min_vacuum_size=min_vacuum,
            min_lw=min_lw,
        )
        # jobs += [generate_adslabs_structures]
        adslab_structures = generate_adslabs_structures

        if self.slab_relax_maker is None:
            raise ValueError("adslab_relax_maker shouldn't be Null.")

        # slab relaxation without adsorption
        slab_optimize_job = self.slab_relax_maker.make(slab_structure, prev_dir=None)
        slab_optimize_job.append_name("slab relaxation job")
        jobs += [slab_optimize_job]

        optimized_slab = slab_optimize_job.output.structure
        prev_dir = slab_optimize_job.output.dir_name

        slab_static_job = self.slab_static_maker.make(optimized_slab, prev_dir=prev_dir)
        slab_static_job.append_name("slab static job")
        jobs += [slab_static_job]

        slab_dft_energy = slab_static_job.output.output.energy

        adsorption_jobs = []
        ads_outputs = defaultdict(list)

        for i, ad_structure in enumerate(adslab_structures):
            ads_job = self.slab_relax_maker.make(ad_structure)
            ads_job.append_name(f"configuration {i}")

            adsorption_jobs.append(ads_job)
            ads_outputs["configuration_number"].append(i)
            ads_outputs["relaxed_structures"].append(ads_job.output.structure)

            static_job = self.slab_static_maker.make(ads_job.output.structure)
            static_job.append_name(f"static configuration {i}")
            adsorption_jobs.append(static_job)

            ads_outputs["static_energy"].append(static_job.output.energy)
            ads_outputs["dirs"].append(ads_job.output.dir_name)

        jobs += [adsorption_jobs]

        adsorption_calc = adsorption_calculations(
            # bulk_structure=optimized_bulk,
            # molecule_structure=optimized_molecule,
            # surface_idx=surface_idx,
            adslab_structures=adslab_structures,
            adslabs_data=ads_outputs,
            molecule_dft_energy=molecule_dft_energy,
            slab_dft_energy=slab_dft_energy,
        )
        jobs += [adsorption_calc]

        return Flow(jobs, output=adsorption_calc.output, name=self.name)
