import logging

import click

from message_ix_models.util.click import common_params

log = logging.getLogger(__name__)


# allows to activate water module
@click.group("water")
@common_params("regions")
@click.pass_obj
def cli(context, regions):
    """This allows adding components of the MESSAGEix-Nexus module

    This modifies model name & scenario name
    and verifies the region setup
    """

    from .utils import read_config

    # Ensure water model configuration is loaded
    read_config(context)
    if not context.scenario_info:
        context.scenario_info.update(
            dict(model="ENGAGE_SSP2_v4.1.7", scenario="baseline_clone_test")
        )
    context.output_scenario = "baseline"
    context.output_model = context.scenario_info["model"] + "_wat"

    # Handle --regions; use a sensible default for MESSAGEix-Nexus
    if regions:
        log.info(f"Regions choice {regions}")
        if regions in ["R14", "R32", "RCP"]:
            log.warning(
                "the MESSAGEix-Nexus module might not be compatible with your 'regions' choice"
            )
    else:
        log.info("Use default --regions=R11")
        regions = "R11"
    # add an attribute to distinguish country models
    if regions in ["R11", "R12", "R14", "R32", "RCP"]:
        context.type_reg = "global"
    else:
        context.type_reg = "country"
    context.regions = regions


@cli.command("nexus")
@common_params("regions")
@click.pass_obj
def nexus(context, regions):
    """Build and solve model with new cooling technologies.

    Use the --url option to specify the base scenario.
    """
    context.nexus_set = "nexus"

    from .build import main as build

    # Determine the output scenario name based on the --url CLI option. If the
    # user did not give a recognized value, this raises an error
    output_scenario_name = 'nexus'
    output_model_name = context.output_model

    # Clone and build
    scen = context.get_scenario().clone(
        model=output_model_name, scenario=output_scenario_name
    )

    print(scen.model)
    print(scen.scenario)
    # Build
    build(context, scen)

    # Solve
    scen.solve()


@cli.command("cooling")
@common_params("regions")
@click.pass_obj
def cooling(context, regions):
    """Build and solve model with new cooling technologies.

    Use the --url option to specify the base scenario.
    """
    context.nexus_set = "cooling"

    from .build import main as build

    # Determine the output scenario name based on the --url CLI option. If the
    # user did not give a recognized value, this raises an error.

    output_scenario_name = "cooling"
    output_model_name = context.output_model

    # Clone and build
    scen = context.get_scenario().clone(
        model=output_model_name, scenario=output_scenario_name
    )

    print(scen.model)
    print(scen.scenario)
    # Build
    build(context, scen)

    # Solve
    scen.solve()