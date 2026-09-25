from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class TopologyStats(BaseModel):
    total: int
    space: int
    air: int
    ground: int
    sea: int
    links: int
    active_links: int
    average_link_latency_ms: float

class ParticipantStats(BaseModel):
    total: int
    selected: int

class FLRoundMetric(BaseModel):
    round: int
    accuracy: float
    loss: float
    participants: int
    latency_ms: float
    energy_j: float

class ExperimentSummary(BaseModel):
    id: int
    scenario: str
    algorithm: str
    target_rounds: int
    completed_rounds: int
    current_round: int
    accuracy: float
    status: str
    is_simulation: bool

class AlertInfo(BaseModel):
    severity: str
    title: str
    message: str

class FilterOptions(BaseModel):
    scenarios: List[dict]
    algorithms: List[str]
    selected_scenario_id: Optional[int] = None
    selected_algorithm: Optional[str] = None

class DashboardStatsData(BaseModel):
    topology: TopologyStats
    participants: ParticipantStats
    latest_experiment: Optional[ExperimentSummary]
    recent_experiments: List[ExperimentSummary]
    fl_training: List[FLRoundMetric]
    alerts: List[AlertInfo]
    filters: FilterOptions
    generated_at: datetime
