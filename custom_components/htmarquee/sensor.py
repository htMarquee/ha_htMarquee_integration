"""Sensor platform for htMarquee."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfInformation,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import HtMarqueeConfigEntry
from .coordinator import HtMarqueeCoordinator
from .entity import HtMarqueeEntity

# Recomputing "boot time" from an uptime counter drifts by a second or two on
# every poll, which would write a new state every 30 seconds forever. Only
# accept a new value once it moves more than this — a real reboot moves it by
# far more, ordinary jitter never does.
_UPTIME_DRIFT_TOLERANCE = timedelta(seconds=60)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HtMarqueeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up htMarquee sensors."""
    coordinator = entry.runtime_data
    entities: list[HtMarqueeEntity] = [
        HtMarqueePhaseSensor(coordinator, entry),
        HtMarqueeMovieSensor(coordinator, entry),
        HtMarqueeCpuSensor(coordinator, entry),
        HtMarqueeMemorySensor(coordinator, entry),
        HtMarqueeTemperatureSensor(coordinator, entry),
        HtMarqueeUptimeSensor(coordinator, entry),
        HtMarqueeDiskFreeSensor(coordinator, entry),
    ]
    # Scheduled Showtimes is Premiere-only, and older firmware doesn't have
    # it at all. The coordinator probes it during the first refresh, so by
    # now we know whether a showtime sensor could ever have a value.
    if coordinator.showtimes_supported is not False:
        entities.append(HtMarqueeNextShowtimeSensor(coordinator, entry))
    async_add_entities(entities)


class HtMarqueePhaseSensor(HtMarqueeEntity, SensorEntity):
    """Current slideshow phase sensor."""

    _attr_name = "Slideshow Phase"
    _attr_icon = "mdi:filmstrip"

    def __init__(self, coordinator: HtMarqueeCoordinator, entry: HtMarqueeConfigEntry) -> None:
        super().__init__(coordinator, entry, "phase")

    @property
    def native_value(self) -> str | None:
        if not self.coordinator.data:
            return None
        slideshow = self.coordinator.data.get("slideshow", {})
        return slideshow.get("phase")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        if not self.coordinator.data:
            return attrs
        slideshow = self.coordinator.data.get("slideshow", {})
        attrs["phase_duration_s"] = slideshow.get("phase_duration_s")
        attrs["transition_effect"] = slideshow.get("transition_effect")
        attrs["is_paused"] = slideshow.get("is_paused")
        return attrs


class HtMarqueeMovieSensor(HtMarqueeEntity, SensorEntity):
    """Current movie sensor with rich metadata attributes."""

    _attr_name = "Current Movie"
    _attr_icon = "mdi:movie-open"

    def __init__(self, coordinator: HtMarqueeCoordinator, entry: HtMarqueeConfigEntry) -> None:
        super().__init__(coordinator, entry, "movie")

    @property
    def native_value(self) -> str | None:
        movie = self._movie
        if not movie:
            return None
        return movie.get("title")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        movie = self._movie
        if not movie:
            return attrs
        attrs["tmdb_id"] = movie.get("tmdb_id")
        attrs["year"] = movie.get("year")
        attrs["genres"] = movie.get("genres", [])
        attrs["rating"] = movie.get("rating")
        attrs["runtime"] = movie.get("runtime")
        attrs["vote_average"] = movie.get("vote_average")
        attrs["rt_rating"] = movie.get("rt_rating")
        attrs["metacritic_rating"] = movie.get("metacritic_rating")
        attrs["tagline"] = movie.get("tagline")
        attrs["aspect_ratio"] = movie.get("aspect_ratio")
        poster = movie.get("poster_url", "")
        attrs["poster_url"] = self.coordinator.api.get_poster_url(poster) if poster else None
        if self.coordinator.data:
            attrs["state_label"] = self.coordinator.data.get("state_label")
        return attrs

    @property
    def _movie(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("current_movie")


class _HtMarqueeMetricSensor(HtMarqueeEntity, SensorEntity):
    """Base for the /api/hardware/metrics readings.

    Note these do *not* come from /api/status — its `hardware` block reports
    CPU and memory as a hard-coded 0.0 and only `disk_free` is real.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def available(self) -> bool:
        return super().available and bool(self.coordinator.metrics)


class HtMarqueeCpuSensor(_HtMarqueeMetricSensor):
    """CPU load."""

    _attr_name = "CPU Usage"
    _attr_icon = "mdi:cpu-64-bit"
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator: HtMarqueeCoordinator, entry: HtMarqueeConfigEntry) -> None:
        super().__init__(coordinator, entry, "cpu_percent")

    @property
    def native_value(self) -> float | None:
        return self.coordinator.metrics.get("cpu_percent")


class HtMarqueeMemorySensor(_HtMarqueeMetricSensor):
    """RAM in use."""

    _attr_name = "Memory Usage"
    _attr_icon = "mdi:memory"
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator: HtMarqueeCoordinator, entry: HtMarqueeConfigEntry) -> None:
        super().__init__(coordinator, entry, "memory_percent")

    @property
    def native_value(self) -> float | None:
        memory = self.coordinator.metrics.get("memory") or {}
        return memory.get("percent")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        memory = self.coordinator.metrics.get("memory") or {}
        return {
            "total_mb": memory.get("total_mb"),
            "used_mb": memory.get("used_mb"),
            "available_mb": memory.get("available_mb"),
        }


class HtMarqueeTemperatureSensor(_HtMarqueeMetricSensor):
    """Pi CPU temperature — the number that matters in a wall-mounted frame."""

    _attr_name = "CPU Temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator: HtMarqueeCoordinator, entry: HtMarqueeConfigEntry) -> None:
        super().__init__(coordinator, entry, "cpu_temp")

    @property
    def native_value(self) -> float | None:
        return self.coordinator.metrics.get("cpu_temp_c")


class HtMarqueeUptimeSensor(_HtMarqueeMetricSensor):
    """When the device last booted."""

    _attr_name = "Last Boot"
    _attr_icon = "mdi:clock-start"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_state_class = None  # a timestamp is not a measurement

    def __init__(self, coordinator: HtMarqueeCoordinator, entry: HtMarqueeConfigEntry) -> None:
        super().__init__(coordinator, entry, "last_boot")
        self._boot_time: datetime | None = None

    @property
    def native_value(self) -> datetime | None:
        seconds = self.coordinator.metrics.get("uptime_seconds")
        if not seconds:
            return self._boot_time
        computed = dt_util.utcnow() - timedelta(seconds=float(seconds))
        if self._boot_time is None or abs(computed - self._boot_time) > _UPTIME_DRIFT_TOLERANCE:
            self._boot_time = computed
        return self._boot_time


class HtMarqueeDiskFreeSensor(HtMarqueeEntity, SensorEntity):
    """Free space in the poster/trailer cache — this is what fills up."""

    _attr_name = "Cache Disk Free"
    _attr_icon = "mdi:harddisk"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_native_unit_of_measurement = UnitOfInformation.GIGABYTES
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: HtMarqueeCoordinator, entry: HtMarqueeConfigEntry) -> None:
        super().__init__(coordinator, entry, "disk_free")

    @property
    def native_value(self) -> float | None:
        hardware = (self.coordinator.data or {}).get("hardware") or {}
        return hardware.get("disk_free")


class HtMarqueeNextShowtimeSensor(HtMarqueeEntity, SensorEntity):
    """The next scheduled showing.

    Times are stored on the device in *its* local time, and the API sends
    them as bare 'YYYY-MM-DD' + 'HH:MM' strings with no offset. They are
    interpreted here in Home Assistant's timezone, which is correct whenever
    the two live in the same house — and off by the difference if they don't.
    """

    _attr_name = "Next Showtime"
    _attr_icon = "mdi:ticket"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: HtMarqueeCoordinator, entry: HtMarqueeConfigEntry) -> None:
        super().__init__(coordinator, entry, "next_showtime")

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.showtimes_supported is not False

    def _upcoming(self) -> list[tuple[datetime, dict[str, Any]]]:
        now = dt_util.now()
        found: list[tuple[datetime, dict[str, Any]]] = []
        for showtime in self.coordinator.showtimes:
            date = showtime.get("showtime_date")
            for value in showtime.get("times") or []:
                try:
                    naive = datetime.strptime(f"{date} {value}", "%Y-%m-%d %H:%M")
                except (TypeError, ValueError):
                    continue
                when = naive.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
                if when > now:
                    found.append((when, showtime))
        return sorted(found, key=lambda item: item[0])

    @property
    def native_value(self) -> datetime | None:
        upcoming = self._upcoming()
        return upcoming[0][0] if upcoming else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        upcoming = self._upcoming()
        if not upcoming:
            return {"upcoming_count": 0}
        _, showtime = upcoming[0]
        return {
            "upcoming_count": len(upcoming),
            "movie_title": showtime.get("movie_title"),
            "tmdb_id": showtime.get("tmdb_id"),
            "showtime_date": showtime.get("showtime_date"),
            "times": showtime.get("times"),
            "notes": showtime.get("notes"),
        }
