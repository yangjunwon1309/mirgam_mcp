from pydantic import BaseModel, Field


class FarmCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    address_input: str | None = Field(default=None, max_length=500)
    pnu: str | None = Field(default=None, pattern=r"^\d{19}$")


class FarmUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    address_input: str | None = Field(default=None, max_length=500)
    pnu: str | None = Field(default=None, pattern=r"^\d{19}$")


class BoundaryCreate(BaseModel):
    coordinates: list[tuple[float, float]] = Field(min_length=3, max_length=500)
    imagery_zoom: int | None = Field(default=None, ge=1, le=22)


class RouteCreate(BaseModel):
    boundary_id: str
    label: str | None = Field(default=None, max_length=120)
    coordinates: list[tuple[float, float]] = Field(min_length=2, max_length=500)
