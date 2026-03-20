from pydantic import BaseModel


class MetricPoint(BaseModel):
    timestamp: int
    value: float | None


class MetricSeries(BaseModel):
    metric: str
    display_name: str
    scope: str
    expression: str
    points: list[MetricPoint]
    unit: str | None = None

    @property
    def peak_value(self) -> float | None:
        vals = [p.value for p in self.points if p.value is not None]
        return max(vals) if vals else None

    @property
    def latest_value(self) -> float | None:
        for p in reversed(self.points):
            if p.value is not None:
                return p.value
        return None


class MetricsQueryResult(BaseModel):
    query: str
    series: list[MetricSeries]
    from_date: int
    to_date: int
    status: str
