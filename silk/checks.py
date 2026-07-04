from django.core import checks

from silk.models import GARBAGE_COLLECT_MODES


@checks.register()
def check_garbage_collect_settings(app_configs, **kwargs):
    from silk.config import SilkyConfig

    errors = []
    mode = SilkyConfig().SILKY_GARBAGE_COLLECT_MODE
    max_time = SilkyConfig().SILKY_MAX_RECORDED_TIME

    if mode not in GARBAGE_COLLECT_MODES:
        errors.append(checks.Error(
            f"SILKY_GARBAGE_COLLECT_MODE is {mode!r}, which is not a valid "
            "garbage collection mode.",
            hint="Use 'count', 'time' or 'both'.",
            id='silk.E001',
        ))

    if max_time is not None and (isinstance(max_time, bool)
                                 or not isinstance(max_time, int)
                                 or max_time < 0):
        errors.append(checks.Error(
            f"SILKY_MAX_RECORDED_TIME is {max_time!r}, which is not a "
            "non-negative number of minutes.",
            hint="Set it to a positive integer (minutes), or None to disable "
                 "time-based collection.",
            id='silk.E002',
        ))

    if mode in ('time', 'both') and not max_time:
        errors.append(checks.Warning(
            f"SILKY_GARBAGE_COLLECT_MODE is {mode!r} but "
            "SILKY_MAX_RECORDED_TIME is not set, so nothing is removed by "
            "age" + (" and the count cap does not apply in 'time' mode"
                     if mode == 'time' else "") + ".",
            hint="Set SILKY_MAX_RECORDED_TIME to a positive integer (minutes).",
            id='silk.W001',
        ))

    return errors
