const { calculateOrderTotal } = require('../../utils/fee')
const { DEFAULT_MAX_DISTANCE_KM } = require('../../config/business')

Page({
  data: {
    maxDistanceKm: DEFAULT_MAX_DISTANCE_KM,
    orders: []
  },

  onLoad() {
    this.loadMockOrders()
  },

  loadMockOrders() {
    this.setData({
      orders: [
        {
          id: 'order_1001',
          storeName: '山姆会员店深圳福田店',
          itemsText: '牛肉卷 2 盒、瑞士卷 1 盒、烤鸡 1 只',
          distanceKm: 3.2,
          pricing: calculateOrderTotal(328, 12)
        },
        {
          id: 'order_1002',
          storeName: '山姆会员店上海真如店',
          itemsText: '鲜奶 2 箱、蛋糕 1 个',
          distanceKm: 8.6,
          pricing: calculateOrderTotal(218, 10)
        }
      ]
    })
  },

  acceptOrder(event) {
    const orderId = event.currentTarget.dataset.id
    const order = this.data.orders.find((item) => item.id === orderId)

    if (!order) {
      wx.showToast({ title: '订单不存在', icon: 'none' })
      return
    }

    wx.showModal({
      title: '接单成功',
      content: `请前往${order.storeName}采购，平台服务费为 ¥${order.pricing.serviceFee}。`,
      showCancel: false
    })
  }
})
