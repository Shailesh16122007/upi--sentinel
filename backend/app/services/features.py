"""Feature extraction for the real-time path. Pure DB reads + in-memory graph; no I/O to LLMs/OCR."""
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.graph.network import graph
from app.models import Beneficiary, Device, Transaction, User

IST = ZoneInfo("Asia/Kolkata")
HISTORY_DAYS = 90


@dataclass
class Features:
    amount: float
    channel: str
    hour_ist: int
    hist_count: int
    hist_mean: float
    hist_std: float
    hist_max: float
    amount_ratio: float  # amount / max(hist_max, 1)
    amount_z: float
    is_new_beneficiary: bool
    beneficiary_age_days: float | None  # None if never seen by the system
    beneficiary_flagged: bool
    beneficiary_flag_reason: str | None
    fan_in: int
    is_new_device: bool
    device_users: int  # how many distinct users this device has been seen with
    usual_hours: set[int] = field(default_factory=set)
    hour_unusual: bool = False
    velocity_10m: int = 0
    distance_km: float | None = None
    network_score: float = 0.0
    network_path: list[str] = field(default_factory=list)

    def vector(self) -> list[float]:
        """Order must match ml.model.FEATURE_NAMES."""
        return [
            math.log1p(self.amount_ratio),
            float(self.is_new_beneficiary),
            float(self.is_new_device),
            min(self.beneficiary_age_days if self.beneficiary_age_days is not None else 0.0, 365.0) / 365.0,
            float(self.hour_unusual),
            float(min(self.velocity_10m, 10)),
            float(min(self.fan_in, 50)),
            self.network_score,
            math.log1p(self.distance_km or 0.0),
            float(self.channel == "AEPS"),
        ]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def extract(db: Session, user: User, vpa: str, amount: float, channel: str, device_ref: str,
            ts: datetime, lat: float | None, lon: float | None) -> Features:
    since = ts - timedelta(days=HISTORY_DAYS)
    hist = db.execute(
        select(Transaction.amount, Transaction.created_at, Transaction.beneficiary_id)
        .where(Transaction.user_id == user.id, Transaction.status == "COMPLETED",
               Transaction.created_at >= since, Transaction.created_at < ts)
    ).all()
    amounts = [h.amount for h in hist]
    n = len(amounts)
    mean = sum(amounts) / n if n else 0.0
    std = math.sqrt(sum((a - mean) ** 2 for a in amounts) / n) if n > 1 else 0.0
    hmax = max(amounts) if amounts else 0.0
    usual_hours = {_ist(h.created_at).hour for h in hist}

    bene = db.scalar(select(Beneficiary).where(Beneficiary.vpa == vpa))
    known_bene_ids = {h.beneficiary_id for h in hist}
    is_new_bene = bene is None or bene.id not in known_bene_ids
    bene_age = None
    if bene is not None:
        bene_age = max((ts - _aware(bene.created_at)).total_seconds() / 86400, 0.0)

    known_devices = set(db.scalars(select(Device.ref).where(Device.user_id == user.id)))
    device_users = db.scalar(select(func.count(func.distinct(Device.user_id))).where(Device.ref == device_ref)) or 0

    velocity = db.scalar(
        select(func.count()).select_from(Transaction)
        .where(Transaction.user_id == user.id, Transaction.is_historical.is_(False),
               Transaction.created_at >= ts - timedelta(minutes=10), Transaction.created_at <= ts)
    ) or 0

    hour = _ist(ts).hour
    hour_unusual = bool(usual_hours) and all(min(abs(hour - h), 24 - abs(hour - h)) > 1 for h in usual_hours)

    dist = None
    if lat is not None and lon is not None and user.home_lat is not None and user.home_lon is not None:
        dist = haversine_km(user.home_lat, user.home_lon, lat, lon)

    net_score, path = graph.beneficiary_risk(vpa)

    return Features(
        amount=amount, channel=channel, hour_ist=hour, hist_count=n, hist_mean=mean, hist_std=std,
        hist_max=hmax, amount_ratio=amount / max(hmax, 1.0),
        amount_z=(amount - mean) / std if std > 0 else (0.0 if n == 0 else 10.0 * (amount > hmax)),
        is_new_beneficiary=is_new_bene, beneficiary_age_days=bene_age,
        beneficiary_flagged=bool(bene and bene.flagged_fraud), beneficiary_flag_reason=bene.flag_reason if bene else None,
        fan_in=graph.fan_in(vpa), is_new_device=device_ref not in known_devices, device_users=device_users,
        usual_hours=usual_hours, hour_unusual=hour_unusual, velocity_10m=velocity, distance_km=dist,
        network_score=net_score, network_path=path,
    )


def _aware(dt: datetime) -> datetime:
    from datetime import timezone
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _ist(dt: datetime) -> datetime:
    return _aware(dt).astimezone(IST)
