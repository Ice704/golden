const assert = require('node:assert/strict')
const { calculateServiceFee, calculateOrderTotal, toCents } = require('../utils/fee')

assert.equal(toCents(12.345), 1235)
assert.equal(calculateServiceFee(300), 30)
assert.equal(calculateServiceFee(99.99), 10)
assert.deepEqual(calculateOrderTotal(300, 8), {
  proxyAmount: 300,
  serviceFee: 30,
  deliveryFee: 8,
  total: 338
})
assert.throws(() => calculateServiceFee(-1), /金额必须是非负数字/)

console.log('fee tests passed')
