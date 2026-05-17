const cloud = require('wx-server-sdk')

const DEFAULT_MAX_DISTANCE_KM = 10
const EARTH_RADIUS_KM = 6371

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })

function toRadians(degrees) {
  return degrees * Math.PI / 180
}

function calculateDistanceKm(from, to) {
  if (!from || !to) {
    throw new Error('坐标不能为空')
  }

  const fromLat = toRadians(Number(from.latitude))
  const toLat = toRadians(Number(to.latitude))
  const deltaLat = toRadians(Number(to.latitude) - Number(from.latitude))
  const deltaLng = toRadians(Number(to.longitude) - Number(from.longitude))
  const haversine = Math.sin(deltaLat / 2) ** 2
    + Math.cos(fromLat) * Math.cos(toLat) * Math.sin(deltaLng / 2) ** 2

  return Number((EARTH_RADIUS_KM * 2 * Math.atan2(Math.sqrt(haversine), Math.sqrt(1 - haversine))).toFixed(2))
}

exports.main = async (event) => {
  const { shopperLocation, maxDistanceKm = DEFAULT_MAX_DISTANCE_KM } = event

  if (!shopperLocation) {
    throw new Error('缺少代购员位置')
  }

  const db = cloud.database()
  const result = await db.collection('orders')
    .where({ status: 'pending' })
    .orderBy('createdAt', 'desc')
    .limit(50)
    .get()

  return result.data
    .map((order) => ({
      ...order,
      distanceKm: calculateDistanceKm(shopperLocation, order.storeLocation)
    }))
    .filter((order) => order.distanceKm <= Number(maxDistanceKm))
    .sort((left, right) => left.distanceKm - right.distanceKm)
}
