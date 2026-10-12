"""Entry point for a Delay-Aware FedAvg experiment worker."""


def run_delay_aware_experiment(experiment_id):
    """Run the shared FL worker with the experiment's DelayAware selector."""
    from backend.services.fl_service import run_experiment

    return run_experiment(experiment_id)
