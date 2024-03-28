import pytest
from jobflow import run_locally
from pymatgen.core import Structure

from atomate2.vasp.flows.adsorption import AdsorptionMaker


@pytest.fixture()
def test_adsorption(mock_vasp, clean_dir, test_dir):
    # mapping from job name to directory containing test files
    ref_paths = {
        "ads relax bulk": "Au_adsorption/bulk",
        "ads relax mol": "Au_adsorption/mol",
        "ads relax slab": "Au_adsorption/slab",
        "elastic relax 1/3": "Au_adsorption/ads_relax_1_3",
        "elastic relax 2/3": "Au_adsorption/ads_relax_2_3",
        "elastic relax 3/3": "Au_adsorption/ads_relax_3_3",
    }

    # settings passed to fake_run_vasp; adjust these to check for certain INCAR settings
    fake_run_vasp_kwargs = {
        "ads relax bulk": {"incar_settings": ["NSW", "ISMEAR", "ISIF"]},
        "ads relax mol": {"incar_settings": ["NSW", "ISMEAR", "ISIF"]},
        "ads relax slab": {"incar_settings": ["NSW", "ISMEAR", "ISIF"]},
        "elastic relax 1/3": {"incar_settings": ["NSW", "ISMEAR", "ISIF"]},
        "elastic relax 2/3": {"incar_settings": ["NSW", "ISMEAR", "ISIF"]},
        "elastic relax 3/3": {"incar_settings": ["NSW", "ISMEAR", "ISIF"]},
    }

    # automatically use fake VASP and write POTCAR.spec during the test
    mock_vasp(ref_paths, fake_run_vasp_kwargs)

    molcule = Structure.from_file(test_dir / "vasp/Au_adsorption/mol/POSCAR")
    bulk_structure = Structure.from_file(test_dir / "vasp/Au_adsorption/bulk/POSCAR")

    flow = AdsorptionMaker().make(molecule=molcule, structure=bulk_structure)

    # Run the flow or job and ensure that it finished running successfully
    responses = run_locally(flow, create_folders=True, ensure_success=True)

    # Check that the correct number of jobs are created
    assert len(responses) == 9, "Unexpected number of jobs in the flow."

    # Verify job names and order
    expected_job_names = [
        "molecule relaxation job",
        "molecule static job",
        "bulk relaxation job",
        "slab relaxation job",
        "slab static job",
        "adslabs job",
        "adsorption calculation",
    ]
    for response, expected_name in zip(responses, expected_job_names):
        assert (
            response.name == expected_name
        ), f"Job '{response.name}' does not match expected '{expected_name}'."

    # Additional checks (WIP)
    adsorption_result = responses[-1].output
    assert adsorption_result is not None, "Adsorption result is None."
    assert hasattr(
        adsorption_result, "adsorption_energy"
    ), "Adsorption result does not contain adsorption_energy."
