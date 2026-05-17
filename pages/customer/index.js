const { calculateOrderTotal } = require('../../utils/fee')
const { DEFAULT_DELIVERY_FEE } = require('../../config/business')

Page({
  data: {
    storeName: '',
    itemsText: '',
    proxyAmount: '',
    deliveryFee: DEFAULT_DELIVERY_FEE,
    address: '',
    pricing: calculateOrderTotal(0, DEFAULT_DELIVERY_FEE),
    submitting: false
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

  async submitOrder() {
    if (this.data.submitting) {
      return
    }

    if (!this.data.storeName || !this.data.itemsText || !Number(this.data.proxyAmount) || !this.data.address) {
      wx.showToast({ title: '请补全订单信息', icon: 'none' })
      return
    }

    if (!wx.cloud) {
      wx.showToast({ title: '云开发未初始化，无法创建订单', icon: 'none' })
      return
    }

    const db = wx.cloud.database()
    const order = {
      storeName: this.data.storeName,
      itemsText: this.data.itemsText,
      address: this.data.address,
      pricing: this.data.pricing,
      status: 'pending',
      createdAt: db.serverDate()
    }

    this.setData({ submitting: true })

    try {
      const result = await db.collection('orders').add({ data: order })

      wx.showModal({
        title: '订单已创建',
        content: `预计支付 ¥${order.pricing.total}，等待附近代购接单。`,
        showCancel: false
      })

      this.setData({
        storeName: '',
        itemsText: '',
        proxyAmount: '',
        deliveryFee: DEFAULT_DELIVERY_FEE,
        address: '',
        pricing: calculateOrderTotal(0, DEFAULT_DELIVERY_FEE),
        lastOrderId: result._id
      })
    } catch (error) {
      wx.showToast({ title: '订单创建失败，请稍后重试', icon: 'none' })
      console.error('create order failed', error)
    } finally {
      this.setData({ submitting: false })
    }
  }
})
