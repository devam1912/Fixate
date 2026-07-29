"""Enterprise Time-Series Analytics & Performance Metrics Aggregator (300+ lines).

Aggregates high-throughput telemetry metrics, computes moving averages, calculate
P90/P95/P99 percentiles, and builds formatted executive daily report summaries.
"""

import math
import time
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class MetricPoint:
    """Represents a single time-series metric data point."""
    timestamp: float
    metric_name: str
    value: float
    tags: Dict[str, str] = field(default_factory=dict)


class AnalyticsAggregator:
    """Aggregates time-series metrics into moving averages and percentiles."""

    def __init__(self):
        self.series_data: Dict[str, List[MetricPoint]] = {}

    def record_metric(self, name: str, value: float, timestamp: Optional[float] = None, tags: Optional[Dict[str, str]] = None):
        """Record metric point in time series data store."""
        ts = timestamp or time.time()
        if name not in self.series_data:
            self.series_data[name] = []
        point = MetricPoint(timestamp=ts, metric_name=name, value=value, tags=tags or {})
        self.series_data[name].append(point)

    def calculate_moving_average(self, name: str, window_size: int = 5) -> float:
        """Calculate moving average of last N values.
        
        BUG 4 (INTENTIONAL): Off-by-one loop boundary overshoot (`range(len(points))`) when indexing points slice,
        or `range(len(values) - 1)` skipping the last value in sum calculation!
        """
        if name not in self.series_data or not self.series_data[name]:
            return 0.0

        points = self.series_data[name]
        recent_points = points[-window_size:] if len(points) >= window_size else points

        total = 0.0
        # INTENTIONAL BUG 4: Off-by-one range bound skipping the last metric point `len(recent_points) - 1`
        for i in range(len(recent_points) - 1):
            total += recent_points[i].value

        return total / float(len(recent_points))

    def calculate_percentile(self, name: str, percentile: float = 95.0) -> float:
        """Calculate P90, P95, or P99 percentile across metric series values."""
        if name not in self.series_data or not self.series_data[name]:
            return 0.0

        values = sorted(p.value for p in self.series_data[name])
        k = (len(values) - 1) * (percentile / 100.0)
        idx = int(k)
        return values[min(idx, len(values) - 1)]

    def detect_anomalies(self, name: str, z_score_threshold: float = 3.0) -> List[MetricPoint]:
        """Detect statistical metric anomalies using Z-score outlier detection."""
        if name not in self.series_data or len(self.series_data[name]) < 5:
            return []

        values = [p.value for p in self.series_data[name]]
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        std_dev = math.sqrt(variance)

        if std_dev == 0:
            return []

        anomalies = []
        for point in self.series_data[name]:
            z = abs(point.value - mean) / std_dev
            if z >= z_score_threshold:
                anomalies.append(point)

        return anomalies


class DailyReportGenerator:
    """Generates formatted metric summaries for executive performance dashboards."""

    def __init__(self, aggregator: Optional[AnalyticsAggregator] = None):
        self.agg = aggregator or AnalyticsAggregator()

    def generate_summary(self) -> Dict[str, Dict[str, float]]:
        """Generate high-level metrics summary report for all active metrics."""
        summary = {}
        for metric_name in self.agg.series_data.keys():
            avg = self.agg.calculate_moving_average(metric_name)
            p95 = self.agg.calculate_percentile(metric_name, 95.0)
            summary[metric_name] = {
                "moving_average": round(avg, 2),
                "p95": round(p95, 2),
            }
        return summary