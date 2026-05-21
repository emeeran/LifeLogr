"""Pydantic schemas for geotagging journal entries."""
from pydantic import BaseModel, ConfigDict, Field


class GeotagUpdate(BaseModel):
    """Set or update the geolocation of an entry."""
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    location_name: str | None = Field(default=None, max_length=255)


class GeotagResponse(BaseModel):
    """Geotag info for an entry."""
    entry_id: int = Field(alias="id")
    latitude: float | None
    longitude: float | None
    location_name: str | None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class NearbyEntry(BaseModel):
    """An entry near a given location."""
    id: int
    entry_date: str
    title: str | None
    latitude: float
    longitude: float
    location_name: str | None
    distance_km: float


class NearbyResponse(BaseModel):
    """Entries near a given location."""
    items: list[NearbyEntry]
    total: int
