"""Durable latest training state stored with an experiment, independent of the UI.

The worker commits at phase boundaries where pending round rows have not yet
been added (or have already been committed). No extra writer/thread is needed.
"""
from datetime import datetime, timezone


def publish(db, experiment, phase, round_number=None, selected=None, client_id=None, client_status=None, **values):
    config = dict(experiment.config_json or {})
    previous = config.get("training_progress", {})
    state = dict(previous)
    if round_number is not None and round_number != state.get("round"):
        state["clients"] = {}
        state["selected"] = []
    if selected is not None:
        state["selected"] = list(selected)
        state["clients"] = {client: {"status": "SELECTED"} for client in selected}
    if client_id is not None:
        clients = dict(state.get("clients", {}))
        clients[client_id] = {"status": client_status, **values}
        state["clients"] = clients
    state.update(revision=previous.get("revision", 0) + 1, phase=phase,
                 updated_at=datetime.now(timezone.utc).isoformat(), **values)
    if round_number is not None:
        state["round"] = round_number
    state["events"] = (previous.get("events", []) + [{
        "phase": phase, "round": state.get("round", 0), "client_id": client_id,
        "client_status": client_status, "at": state["updated_at"],
    }])[-40:]
    config["training_progress"] = state
    experiment.config_json = config
    db.commit()
