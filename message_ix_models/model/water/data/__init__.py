"""Generate input data."""

import logging

from message_ix_models import ScenarioInfo
from message_ix_models.util import add_par_data

from .water_for_ppl import cool_tech, non_cooling_tec
from .demands import add_demand

log = logging.getLogger(__name__)

DATA_FUNCTIONS = [
    cool_tech,  # Water & parasitic_electricity requirements for cooling technologies
    non_cooling_tec,
    add_demand
]


def add_data(scenario, context, dry_run=False):
    """Populate `scenario` with MESSAGEix-Nexus data."""

    info = ScenarioInfo(scenario)
    context["water build info"] = info

    data_funcs = (
        [cool_tech, non_cooling_tec]
        if context.nexus_set == "cooling"
        else DATA_FUNCTIONS
    )

    for func in data_funcs:
        # Generate or load the data; add to the Scenario
        log.info(f"from {func.__name__}()")
        add_par_data(scenario, func(context), dry_run=dry_run)

    log.info("done")