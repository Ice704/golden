const EARTH_RADIUS_KM = 6371

function toRadians(degrees) {
  return degrees * Math.PI / 180
}

function assertCoordinate(point) {
  if (!point || !Number.isFinite(Number(point.latitude)) || !Number.isFinite(Number(point.longitude))) {
    throw new Error('坐标必须包含有效的 latitude 和 longitude')
  }
}

function calculateDistanceKm(from, to) {
  assertCoordinate(from)
  assertCoordinate(to)

  const fromLat = toRadians(Number(from.latitude))
  const toLat = toRadians(Number(to.latitude))
  const deltaLat = toRadians(Number(to.latitude) - Number(from.latitude))
  const deltaLng = toRadians(Number(to.longitude) - Number(from.longitude))

  const haversine = Math.sin(deltaLat / 2) ** 2
    + Math.cos(fromLat) * Math.cos(toLat) * Math.sin(deltaLng / 2) ** 2
  const centralAngle = 2 * Math.atan2(Math.sqrt(haversine), Math.sqrt(1 - haversine))

  return Number((EARTH_RADIUS_KM * centralAngle).toFixed(2))
}

function isWithinDistance(from, to, maxDistanceKm) {
  if (!Number.isFinite(Number(maxDistanceKm)) || Number(maxDistanceKm) < 0) {
    throw new Error('最大距离必须是非负数字')
  }

  return calculateDistanceKm(from, to) <= Number(maxDistanceKm)
}

module.exports = {
  calculateDistanceKm,
  isWithinDistance
}
