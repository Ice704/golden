# 山姆代购小程序 MVP

这是一个面向山姆会员店代购场景的微信小程序 MVP 方案与代码骨架，核心流程为：

1. 顾客发布代购订单，填写山姆门店、商品清单、预估商品金额、收货地址与期望送达时间。
2. 系统根据代购员当前位置与门店/收货地址距离，向合适的代购员展示可接订单。
3. 代购员接单后完成采购与配送。
4. 平台按代购金额收取 10% 服务费。

## 业务规则

- 服务费 = 代购金额 × 10%。
- 顾客支付总额 = 代购金额 + 服务费 + 配送费。
- 默认仅向距离订单门店 `10km` 内的代购员展示订单，可在 `config/business.js` 修改。
- 代购员接单时需要校验订单仍处于 `pending` 状态，避免重复接单。

## 目录结构

```text
app.js                         小程序入口
app.json                       页面与窗口配置
app.wxss                       全局样式
config/business.js             佣金、距离等业务配置
utils/fee.js                   服务费与总价计算
utils/distance.js              经纬度距离计算
pages/customer/index.*         顾客下单页面
pages/shopper/index.*          代购接单页面
pages/mine/index.*             我的页面
cloudfunctions/matchOrders/    按距离筛选可接订单云函数示例
tests/                         Node.js 单元测试
```

## 本地校验

```bash
node tests/fee.test.js
node tests/distance.test.js
```

## 后续建议

- 接入微信登录、订阅消息、微信支付与退款。
- 增加订单状态机：`pending -> accepted -> shopping -> delivering -> completed/cancelled`。
- 增加代购员资质审核、保证金、黑名单与订单争议处理。
- 接入地图 SDK 获取真实门店距离、路线距离与配送费。
