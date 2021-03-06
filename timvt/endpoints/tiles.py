"""TiVTiler.endpoints.tiles: Vector Tiles endpoint."""

from typing import Any, Dict, Optional

from asyncpg.pool import Pool
from morecantile import Tile, TileMatrixSet

from ..models.mapbox import TileJSON
from ..models.metadata import TableMetadata
from ..ressources.enums import MimeTypes
from ..ressources.responses import TileResponse
from ..settings import MAX_FEATURES_PER_TILE, TILE_BUFFER, TILE_RESOLUTION
from ..utils.dependencies import (
    TableParams,
    TileMatrixSetParams,
    TileParams,
    _get_db_pool,
)
from ..utils.timings import Timer

from fastapi import APIRouter, Depends, Query, Request

router = APIRouter()

params: Dict[str, Any] = {
    "responses": {200: {"content": {"application/x-protobuf": {}}}},
    "response_class": TileResponse,
    "tags": ["Tiles"],
}


@router.get("/tiles/{table}/{z}/{x}/{y}.pbf", **params)
@router.get("/tiles/{TileMatrixSetId}/{table}/{z}/{x}/{y}.pbf", **params)
async def tile(
    request: Request,
    table: TableMetadata = Depends(TableParams),
    tile: Tile = Depends(TileParams),
    tms: TileMatrixSet = Depends(TileMatrixSetParams),
    db_pool: Pool = Depends(_get_db_pool),
    columns: str = None,
) -> TileResponse:
    """Handle /tiles requests."""
    timings = []
    headers: Dict[str, str] = {}

    bbox = tms.xy_bounds(tile)
    epsg = tms.crs.to_epsg()
    segSize = (bbox.xmax - bbox.xmin) / 4

    geometry_column = table.geometry_column
    cols = table.properties
    if geometry_column in cols:
        del cols[geometry_column]

    if columns is not None:
        include_cols = [c.strip() for c in columns.split(",")]
        for c in cols.copy():
            if c not in include_cols:
                del cols[c]

    colstring = ", ".join(list(cols))

    limitval = str(int(MAX_FEATURES_PER_TILE))
    limit = f"LIMIT {limitval}" if MAX_FEATURES_PER_TILE > -1 else ""

    sql_query = f"""
        WITH
        bounds AS (
            SELECT
                ST_Segmentize(
                    ST_MakeEnvelope(
                        $1,
                        $2,
                        $3,
                        $4,
                        $5
                    ),
                    $6
                ) AS geom
        ),
        mvtgeom AS (
            SELECT ST_AsMVTGeom(
                ST_Transform(t.{geometry_column}, $5),
                bounds.geom,
                $7,
                $8
            ) AS geom, {colstring}
            FROM {table.id} t, bounds
            WHERE ST_Intersects(
                ST_Transform(t.geom, 4326), ST_Transform(bounds.geom, 4326)
            ) {limit}
        )
        SELECT ST_AsMVT(mvtgeom.*) FROM mvtgeom
    """

    with Timer() as t:
        async with db_pool.acquire() as conn:
            q = await conn.prepare(sql_query)
            content = await q.fetchval(
                bbox.xmin,  # 1
                bbox.ymin,  # 2
                bbox.xmax,  # 3
                bbox.ymax,  # 4
                epsg,  # 5
                segSize,  # 6
                TILE_RESOLUTION,  # 7
                TILE_BUFFER,  # 8
            )
    timings.append(("db-read", t.elapsed))

    if timings:
        headers["X-Server-Timings"] = "; ".join(
            ["{} - {:0.2f}".format(name, time * 1000) for (name, time) in timings]
        )

    return TileResponse(bytes(content), media_type=MimeTypes.pbf.value, headers=headers)


@router.get(
    "/{table}.json",
    response_model=TileJSON,
    responses={200: {"description": "Return a tilejson"}},
    response_model_exclude_none=True,
    tags=["Tiles"],
)
@router.get(
    "/{TileMatrixSetId}/{table}.json",
    response_model=TileJSON,
    responses={200: {"description": "Return a tilejson"}},
    response_model_exclude_none=True,
    tags=["Tiles"],
)
async def tilejson(
    request: Request,
    table: TableMetadata = Depends(TableParams),
    tms: TileMatrixSet = Depends(TileMatrixSetParams),
    minzoom: Optional[int] = Query(None, description="Overwrite default minzoom."),
    maxzoom: Optional[int] = Query(None, description="Overwrite default maxzoom."),
):
    """Return TileJSON document."""
    kwargs = {
        "TileMatrixSetId": tms.identifier,
        "table": table.id,
        "z": "{z}",
        "x": "{x}",
        "y": "{y}",
    }
    tile_endpoint = request.url_for("tile", **kwargs).replace("\\", "")
    minzoom = minzoom or tms.minzoom
    maxzoom = maxzoom or tms.maxzoom
    return {
        "minzoom": minzoom,
        "maxzoom": maxzoom,
        "name": table.id,
        "tiles": [tile_endpoint],
    }
