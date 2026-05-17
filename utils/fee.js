const { SERVICE_FEE_RATE, DEFAULT_DELIVERY_FEE } = require('../config/business')

function toCents(amount) {
  const numberAmount = Number(amount)

  if (!Number.isFinite(numberAmount) || numberAmount < 0) {
    throw new Error('金额必须是非负数字')
  }

  return Math.round(numberAmount * 100)
}

function fromCents(cents) {
  return Number((cents / 100).toFixed(2))
}

function calculateServiceFee(proxyAmount, rate = SERVICE_FEE_RATE) {
  if (!Number.isFinite(rate) || rate < 0) {
    throw new Error('服务费比例必须是非负数字')
  }

  return fromCents(Math.round(toCents(proxyAmount) * rate))
}

function calculateOrderTotal(proxyAmount, deliveryFee = DEFAULT_DELIVERY_FEE) {
  const proxyCents = toCents(proxyAmount)
  const deliveryCents = toCents(deliveryFee)
  const serviceFee = calculateServiceFee(proxyAmount)
  const totalCents = proxyCents + toCents(serviceFee) + deliveryCents

  return {
    proxyAmount: fromCents(proxyCents),
    serviceFee,
    deliveryFee: fromCents(deliveryCents),
    total: fromCents(totalCents)
  }
}

module.exports = {
  calculateServiceFee,
  calculateOrderTotal,
  toCents
}
