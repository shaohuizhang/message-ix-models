from copy import copy, deepcopy
from functools import partial
import logging
from pathlib import Path

from ixmp.reporting.quantity import Quantity
from message_ix.reporting import Key, Reporter, configure
from message_ix.reporting.computations import write_report
from message_ix.reporting.computations import concat
import yaml

from . import computations
from .computations import combine, group_sum
from .util import collapse, infer_keys


log = logging.getLogger(__name__)


def prepare_reporter(scenario, config, key, output_path=None):
    """Prepare to report *key* from *scenario*.

    Parameters
    ----------
    scenario : ixmp.Scenario
        MESSAGE-GLOBIOM scenario containing a solution, to be reported.
    config : os.Pathlike or dict-like
        Reporting configuration path or dictionary.
    key : str or ixmp.reporting.Key
        Quantity or node to compute. The computation is not triggered (i.e.
        :meth:`get <ixmp.reporting.Reporter.get>` is not called); but the
        corresponding, full-resolution Key is returned.
    output_path : os.Pathlike
        If given, a computation ``cli-output`` is added to the Reporter which
        writes *key* to this path.

    Returns
    -------
    ixmp.reporting.Reporter
        Reporter prepared with MESSAGE-GLOBIOM calculations.
    ixmp.reporting.Key
        Same as *key*, in full resolution, if any.

    """
    if isinstance(config, Path):
        # Load configuration from a YAML file
        with open(config, 'r') as f:
            config = yaml.safe_load(f)
    else:
        # Make a copy, in case operations below are destructive
        config = deepcopy(config)

    # TODO do this in ixmp.reporting.configure
    def cfg_sections(*sections):
        return {s: config[s] for s in sections if s in config}

    # Apply global reporting configuration, e.g. unit definitions
    configure(**cfg_sections('units', 'rename_dims'))

    log.info('Preparing reporter')

    # Create a Reporter for *scenario* and apply Reporter-specific config
    rep = Reporter.from_scenario(scenario) \
                  .configure(**cfg_sections('default', 'filters', 'file',
                                            'alias', 'units'))

    # Variable name replacement: dict, not list of entries
    rep.add('iamc variable names', config.get('iamc variable names', {}))

    # Mapping of file sections to handlers
    sections = (
        ('aggregate', add_aggregate),
        ('combine', add_combination),
        ('iamc', add_iamc_table),
        ('general', add_general),
        ('report', add_report),
        )

    for section_name, func in sections:
        entries = config.get(section_name, [])

        # Handle the entries, if any
        if len(entries):
            log.info(f'--- {section_name!r} config section')
        for entry in entries:
            func(rep, entry)

    # If needed, get the full key for *quantity*
    key = rep.check_keys(key)[0]

    if output_path:
        # Add a new computation that writes *key* to the specified file
        rep.add('cli-output', (partial(write_report, path=output_path), key))
        key = 'cli-output'

    log.info('…done')

    return rep, key


def add_aggregate(rep, info):
    """Add one entry from the 'aggregates:' section of a config file.

    Each entry uses :meth:`~.message_ix.reporting.Reporter.aggregate` to
    compute sums across labels within one dimension of a quantity.

    The entry *info* must contain:

    - **_quantities**: list of 0 or more keys for quantities to aggregate. The
      full dimensionality of the key(s) is inferred.
    - **_tag** (:class:`str`): new tag to append to the keys for the aggregated
      quantities.
    - **_dim** (:class:`str`): dimensions

    All other keys are treated as group names; the corresponding values are
    lists of labels along the dimension to sum.

    **Example:**

    .. code-block:: yaml

       aggregates:
       - _quantities: [foo, bar]
         _tag: aggregated
         _dim: a

         baz123: [baz1, baz2, baz3]
         baz12: [baz1, baz2]

    If the full dimensionality of the input quantities are ``foo:a-b`` and
    ``bar:a-b-c``, then :meth:`add_aggregate` creates the new quantities
    ``foo:a-b:aggregated`` and ``bar:a-b-c:aggregated``. These new quantities
    have the new labels ``baz123`` and ``baz12`` along their ``a`` dimension,
    with sums of the indicated values.
    """
    # Copy for destructive .pop()
    info = copy(info)

    quantities = infer_keys(rep, info.pop('_quantities'))
    tag = info.pop('_tag')
    groups = {info.pop('_dim'): info}

    for qty in quantities:
        keys = rep.aggregate(qty, tag, groups, sums=True)

        log.info(f'Add {keys[0]!r} + {len(keys)-1} partial sums')


def add_combination(rep, info):
    r"""Add one entry from the 'combine:' section of a config file.

    Each entry uses the :func:`~.combine` operation to compute a weighted sum
    of different quantities.

    The entry *info* must contain:

    - **key**: key for the new quantity, including dimensionality.
    - **inputs**: a list of dicts specifying inputs to the weighted sum. Each
      dict contains:

      - **quantity** (required): key for the input quantity.
        :meth:`add_combination` infers the proper dimensionality from the
        dimensions of `key` plus dimension to `select` on.
      - **select** (:class:`dict`, optional): selectors to be applied to the
        input quantity. Keys are dimensions; values are either single labels,
        or lists of labels. In the latter case, the sum is taken across these
        values, so that the result has the same dimensionality as `key`.
      - **weight** (:class:`int`, optional): weight for the input quantity;
        default 1.

    **Example.** For the following YAML:

    .. code-block:: yaml

       combine:
       - key: foo:a-b-c
         inputs:
         - quantity: bar
           weight: -1
         - quantity: baz::tag
           select: {d: [d1, d2, d3]}

    …:meth:`add_combination` infers:

    .. math::

       \text{foo}_{abc} = -1 \times \text{bar}_{abc}
       + 1 \times \sum_{d \in \{ d1, d2, d3 \}}{\text{baz}_{abcd}^\text{(tag)}}
       \quad \forall \quad a, b, c
    """
    # Split inputs into three lists
    quantities, select, weights = [], [], []

    # Key for the new quantity
    key = Key.from_str_or_key(info['key'])

    # Loop over inputs to the combination
    for i in info['inputs']:
        # Required dimensions for this input: output key's dims, plus any
        # dims that must be selected on
        selector = i.get('select', {})
        dims = set(key.dims) | set(selector.keys())
        quantities.append(infer_keys(rep, i['quantity'], dims))

        select.append(selector)
        weights.append(i.get('weight', 1))

    # Check for malformed input
    assert len(quantities) == len(select) == len(weights)

    # Computation
    c = tuple([partial(combine, select=select, weights=weights)] + quantities)

    added = rep.add(key, c, strict=True, index=True, sums=True)

    log.info(f"Add {key}\n  computed from {quantities!r}\n  + {len(added)-1} "
             "partial sums")


def add_iamc_table(rep, info):
    """Add one entry from the 'iamc:' section of a config file.

    Each entry uses :meth:`.Reporter.convert_pyam` (plus extra computations) to
    reformat data from the internal :class:`.Quantity` data structure into a
    :class:`pyam.IamDataFrame`.

    The entry *info* must contain:

    - **variable** (:class:`str`): variable name. This is used two ways: it
      is placed in 'Variable' column of the resulting IamDataFrame; and the
      reporting key to :meth:`~.Reporter.get` the data frame is
      ``<variable>:iamc``.
    - **base** (:class:`str`): key for the quantity to convert.
    - **select** (:class:`dict`, optional): keword arguments to
      :meth:`~.Quantity.sel`.
    - **group_sum** (2-:class:`tuple`, optional): `group` and `sum` arguments
      to :func:`.group_sum`.
    - **year_time_dim** (:class:`str`, optional): Dimension to use for the IAMC
      'Year' or 'Time' column. Default 'ya'. (Passed to
      :meth:`~message_ix.reporting.Reporter.convert_pyam`.)
    - **drop** (:class:`list` of :class:`str`, optional): Dimensions to drop
      (→ convert_pyam).
    - **unit** (:class:`str`, optional): Force output in these units (→
      convert_pyam).

    Additional entries are passed as keyword arguments to :func:`.collapse`,
    which is then given as the `collapse` callback for :meth:`.convert_pyam`.

    :func:`.collapse` formats the 'Variable' column of the IamDataFrame.
    The variable name replacements from the 'iamc variable names:' section of
    the config file are applied to all variables.
    """
    # For each quantity, use a chain of computations to prepare it
    name = info.pop('variable')

    # Chain of keys produced: first entry is the key for the base quantity
    base = Key.from_str_or_key(info.pop('base'))
    keys = [base]

    # Second entry is a simple rename
    keys.append(rep.add(Key(name, base.dims, base.tag), base))

    # Optionally select a subset of data from the base quantity
    try:
        sel = info.pop('select')
    except KeyError:
        pass
    else:
        key = keys[-1].add_tag('sel')
        rep.add(key, (Quantity.sel, keys[-1], sel), strict=True)
        keys.append(key)

    # Optionally aggregate data by groups
    try:
        gs = info.pop('group_sum')
    except KeyError:
        pass
    else:
        key = keys[-1].add_tag('agg')
        task = (partial(group_sum, group=gs[0], sum=gs[1]), keys[-1])
        rep.add(key, task, strict=True)
        keys.append(key)

    # Arguments for Reporter.convert_pyam()
    args = dict(
        # Use 'ya' for the IAMC 'Year' column; unless YAML reporting config
        # includes a different dim under format/year_time_dim.
        year_time_dim=info.pop('year_time_dim', 'ya'),
        drop=set(info.pop('drop', [])) & set(keys[-1].dims),
        replace_vars='iamc variable names',
    )

    # Optionally convert units
    try:
        args['unit'] = info.pop('unit')
    except KeyError:
        pass

    # Remaining arguments are for the collapse() callback
    args['collapse'] = partial(collapse, var_name=name, **info)

    # Use the message_ix.Reporter method to add the coversion step
    iamc_keys = rep.convert_pyam(keys[-1], **args)
    keys.extend(iamc_keys)

    # Revise the 'message:default' report to include the last key in the chain
    rep.add('message:default', rep.graph['message:default'] + (keys[-1],))

    log.info(f'Add {keys[-1]!r} from {keys[0]!r}')
    log.debug(f'  {len(keys)} keys total')


def add_report(rep, info):
    """Add items from the 'report' tree in the config file."""
    log.info(f"Add {info['key']!r}")

    # Concatenate pyam data structures
    rep.add(info['key'], tuple([concat] + info['members']), strict=True)


def add_general(rep, info):
    """Add one entry from the 'general:' tree in the config file.

    This is, as the name implies, the most generalized section of the config
    file. Entry *info* must contain:

    - **comp**: this refers to the name of a computation that is available in
      the namespace of :mod:`message_data.reporting.computations`.
    - **args** (:class:`dict`, optional): keyword arguments to the computation.
    - **inputs**: a list of keys to which the computation is applied.
    - **key**: the key for the computed quantity.
    """
    log.info(f"Add {info['key']!r}")

    # Retrieve the function for the computation
    f = getattr(computations, info['comp'])
    kwargs = info.get('args', {})
    inputs = infer_keys(rep, info['inputs'])
    task = tuple([partial(f, **kwargs)] + inputs)

    rep.add(info['key'], task, strict=True)