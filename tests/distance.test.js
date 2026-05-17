const assert = require('node:assert/strict')
const { calculateDistanceKm, isWithinDistance } = require('../utils/distance')

const shenzhenSam = { latitude: 22.5431, longitude: 114.0579 }
const nearby = { latitude: 22.5531, longitude: 114.0679 }
const farAway = { latitude: 31.2304, longitude: 121.4737 }

assert.equal(calculateDistanceKm(shenzhenSam, shenzhenSam), 0)
assert.equal(isWithinDistance(shenzhenSam, nearby, 2), true)
assert.equal(isWithinDistance(shenzhenSam, farAway, 10), false)
assert.throws(() => calculateDistanceKm({}, nearby), /坐标必须包含有效/)

console.log('distance tests passed')
