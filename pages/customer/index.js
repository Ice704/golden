const { calculateOrderTotal } = require('../../utils/fee')
const { DEFAULT_DELIVERY_FEE } = require('../../config/business')

Page({
  data: {
    storeName: '',
    itemsText: '',
    proxyAmount: '',
    deliveryFee: DEFAULT_DELIVERY_FEE,
    address: '',
    pricing: calculateOrderTotal(0, DEFAULT_DELIVERY_FEE)
  },

  onStoreNameInput(event) {
    this.setData({ storeName: event.detail.value })
  },

  onItemsInput(event) {
    this.setData({ itemsText: event.detail.value })
  },

  onProxyAmountInput(event) {
    this.setData({ proxyAmount: event.detail.value }, this.refreshPricing)
  },

  onDeliveryFeeInput(event) {
    this.setData({ deliveryFee: event.detail.value }, this.refreshPricing)
  },

  onAddressInput(event) {
    this.setData({ address: event.detail.value })
  },

  refreshPricing() {
    const proxyAmount = Number(this.data.proxyAmount || 0)
    const deliveryFee = Number(this.data.deliveryFee || 0)
    this.setData({ pricing: calculateOrderTotal(proxyAmount, deliveryFee) })
  },

  submitOrder() {
    if (!this.data.storeName || !this.data.itemsText || !Number(this.data.proxyAmount) || !this.data.address) {
      wx.showToast({ title: '请补全订单信息', icon: 'none' })
      return
    }

    const order = {
      storeName: this.data.storeName,
      itemsText: this.data.itemsText,
      address: this.data.address,
      pricing: this.data.pricing,
      status: 'pending',
      createdAt: Date.now()
    }

    wx.showModal({
      title: '订单已创建',
      content: `预计支付 ¥${order.pricing.total}，等待附近代购接单。`,
      showCancel: false
    })
  }
})
